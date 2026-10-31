"""NVIDIA adapter. GPU imports are intentionally delayed until processing starts."""

from collections.abc import Callable
from typing import Protocol

import numpy as np

from .color import packed_pq_to_scrgb, srgb_to_linear
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
        self.effect = None

    def convert(self, rgb: np.ndarray, settings: HdrSettings, progress: Progress) -> np.ndarray:
        if settings.device != self.device:
            raise ValueError("Settings device does not match the active GPU.")
        cp = self.cp
        progress("Preparing input color")
        frame = cp.asarray(prepare_sdr(rgb, settings))
        cp.cuda.runtime.deviceSynchronize()
        parameters = {
            "contrast": settings.contrast,
            "saturation": settings.saturation,
            "middle_gray": settings.middle_gray,
            "luminance": settings.luminance,
            "debanding_off": int(not settings.debanding),
        }
        if self.effect is None:
            progress("Loading NVIDIA TrueHDR")
            self.effect = self.nvvfx.TrueHDR(**parameters, device=self.device)
        else:
            for key, value in parameters.items():
                setattr(self.effect, key, value)
        progress("Processing on NVIDIA RTX")
        result = self.effect.run(frame)
        # The raw capsule is SDK-owned. Synchronize its producer and finish the
        # host copy before the next run() or close() invalidates that storage.
        cp.cuda.runtime.deviceSynchronize()
        view = cp.from_dlpack(result.image)
        packed = cp.asnumpy(view)
        cp.cuda.runtime.deviceSynchronize()
        del view, result, frame
        if packed.shape != rgb.shape[:2] or packed.dtype != np.uint32:
            raise RuntimeError("Unexpected TrueHDR RGB10A2 output layout.")
        progress("Converting BT.2020 / PQ to linear scRGB")
        scrgb = packed_pq_to_scrgb(packed)
        if not np.isfinite(scrgb).all():
            raise RuntimeError("TrueHDR produced non-finite values.")
        return scrgb

    def close(self) -> None:
        if self.effect is not None:
            self.cp.cuda.runtime.deviceSynchronize()
            self.effect.close()
            self.effect = None
