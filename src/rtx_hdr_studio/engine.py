"""NVIDIA adapter. GPU imports are intentionally delayed until processing starts."""

from collections.abc import Callable
from typing import Protocol

import numpy as np

from .color import packed_pq_to_scrgb, srgb_to_linear
from .native_vfx import NativeVfx
from .resources import (
    GiB,
    empty_image,
    estimate_gpu_bytes,
    gpu_capacity,
    release_image,
    require_memory,
    strip_rows,
    validate_size,
)
from .runtime import configure_gpu
from .settings import HdrSettings

Progress = Callable[[str], None]


class HdrEngine(Protocol):
    name: str

    def convert(self, rgb: np.ndarray, settings: HdrSettings, progress: Progress) -> np.ndarray: ...
    def close(self) -> None: ...


def prepare_sdr(rgb8: np.ndarray, settings: HdrSettings) -> np.ndarray:
    rgb = rgb8.astype(np.float32) / 255
    linear = srgb_to_linear(rgb) if settings.transfer == "srgb" else rgb**2.2
    linear = np.clip(linear * 2**settings.exposure, 0, 1)
    return np.ascontiguousarray((linear ** (1 / 2.2)).transpose(2, 0, 1), dtype=np.float32)


class NvidiaEngine:
    def __init__(self, device: int = 0):
        configure_gpu()
        try:
            import cupy as cp
            import nvvfx
        except ImportError as error:
            raise RuntimeError(
                "GPU dependencies are missing. Follow the GPU installation section in README."
            ) from error
        if not hasattr(nvvfx, "TrueHDR"):
            raise RuntimeError("nvidia-vfx 0.2.0.0 with TrueHDR support is required.")
        self.cp, self.nvvfx, self.device = cp, nvvfx, device
        cp.cuda.Device(device).use()
        properties = cp.cuda.runtime.getDeviceProperties(device)
        name = properties["name"]
        self.name = name.decode("utf-8", errors="replace") if isinstance(name, bytes) else name
        self.effect = NativeVfx(nvvfx)
        self.failed = False

    def check_resources(self, width, height):
        validate_size(width, height)
        capacity = gpu_capacity(self.device)
        estimate = estimate_gpu_bytes(width, height)
        spill = max(0, estimate - capacity["free"])
        # WDDM can charge commit for dedicated allocations as well as shared
        # backing. Check the full GPU demand against commit, not just overflow.
        require_memory(
            spill + 128 * 1024**2,
            "TrueHDR and shared GPU memory",
            commit_size=estimate + 128 * 1024**2,
            reserve=2 * GiB,
        )

    def convert(self, rgb: np.ndarray, settings: HdrSettings, progress: Progress) -> np.ndarray:
        if settings.device != self.device:
            raise ValueError("Settings device does not match the active GPU.")
        cp = self.cp
        height, width = rgb.shape[:2]
        self.check_resources(width, height)
        # Direct allocations avoid retaining the previous image in CuPy's pool.
        frame = output = None
        try:
            frame = cp.ndarray(
                (height, width),
                cp.uint32,
                memptr=cp.cuda.MemoryPointer(cp.cuda.Memory(height * width * 4), 0),
            )
            output = cp.ndarray(
                (height, width),
                cp.uint32,
                memptr=cp.cuda.MemoryPointer(cp.cuda.Memory(height * width * 4), 0),
            )
            progress("Preparing input color")
            rows = strip_rows(width)
            for y in range(0, height, rows):
                source = rgb[y : y + rows]
                rgba = np.full((*source.shape[:2], 4), 255, np.uint8)
                rgba[..., :3] = np.rint(prepare_sdr(source, settings).transpose(1, 2, 0) * 255)
                cp.cuda.runtime.memcpy(
                    frame.data.ptr + y * width * 4, rgba.ctypes.data, rgba.nbytes, 1
                )
            del rgba, source
            progress("Loading NVIDIA TrueHDR")
            self.effect.load(frame, output, settings)
            progress("Processing on NVIDIA RTX")
            self.effect.run()
            cp.cuda.runtime.deviceSynchronize()
            progress("Reading HDR result")
            packed = empty_image((height, width), np.uint32)
            for y in range(0, height, rows):
                cp.cuda.runtime.memcpy(
                    packed.ctypes.data + y * width * 4,
                    output.data.ptr + y * width * 4,
                    min(rows, height - y) * width * 4,
                    2,
                )
        except Exception:
            # Never reuse a CUDA context after an unclassified native failure.
            self.failed = True
            raise
        finally:
            try:
                cp.cuda.runtime.deviceSynchronize()
            finally:
                self.effect.close()
                del frame, output
        # Release shared GPU backing before touching the larger float32 CPU map.
        progress("Converting BT.2020 / PQ to linear scRGB")
        try:
            scrgb = empty_image((height, width, 3), np.float32)
            for y in range(0, height, rows):
                scrgb[y : y + rows] = packed_pq_to_scrgb(packed[y : y + rows])
            return scrgb
        finally:
            release_image(packed)

    def close(self) -> None:
        if self.effect is not None:
            self.cp.cuda.runtime.deviceSynchronize()
            self.effect.close()
