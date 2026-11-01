"""NVIDIA adapter. GPU imports are intentionally delayed until processing starts."""

import logging
from collections.abc import Callable
from typing import Protocol

import numpy as np

from .color import HdrStatistics, packed_pq_to_scrgb, srgb_to_linear
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


def sdr_lut(settings: HdrSettings) -> np.ndarray:
    """The whole per-channel input chain as a 256-entry table (byte-identical)."""
    codes = np.arange(256, dtype=np.uint8).reshape(1, 256, 1)
    return np.rint(prepare_sdr(codes, settings)[0, 0] * 255).astype(np.uint8)


class NvidiaEngine:
    # The TrueHDR PQ table is finite and |scRGB| <= 125 * 2.33 < 300, far below the
    # FP16 limit, so export may skip its full-size range pre-scan for this engine.
    output_range_trusted = True

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
        self.last_statistics = None

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
        self.last_statistics = None
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
            lut = sdr_lut(settings)
            input_rows = strip_rows(width, 8)
            staging = np.empty((min(input_rows, height), width, 4), np.uint8)
            staging[..., 3] = 255
            for y in range(0, height, input_rows):
                strip = staging[: min(input_rows, height - y)]
                strip[..., :3] = lut[rgb[y : y + len(strip)]]
                # cudaMemcpy host->device is synchronous, so the buffer can be reused.
                cp.cuda.runtime.memcpy(
                    frame.data.ptr + y * width * 4, strip.ctypes.data, strip.nbytes, 1
                )
            del staging, strip
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
            # After a failure the context may hold a sticky error; synchronizing
            # again would replace the original NVIDIA message with a CUDA one.
            try:
                if not self.failed:
                    cp.cuda.runtime.deviceSynchronize()
            except Exception:
                self.failed = True
                raise
            finally:
                self.effect.close()
                del frame, output
        # Release shared GPU backing before touching the larger float32 CPU map.
        progress("Converting BT.2020 / PQ to linear scRGB")
        try:
            scrgb = empty_image((height, width, 3), np.float32)
            statistics = HdrStatistics()
            for y in range(0, height, rows):
                strip = packed_pq_to_scrgb(packed[y : y + rows])
                scrgb[y : y + rows] = strip
                # Same strips as hdr_statistics(), while the data is still in cache.
                statistics.add(strip)
            self.last_statistics = statistics.result()
            return scrgb
        finally:
            release_image(packed)

    def close(self) -> None:
        if self.effect is None:
            return
        try:
            if not self.failed:
                self.cp.cuda.runtime.deviceSynchronize()
        except Exception:
            logging.getLogger(__name__).exception("CUDA synchronize during close failed")
        finally:
            self.effect.close()
