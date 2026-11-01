"""Verified FP16 scRGB JPEG XR export with collision-safe publication."""

import os
import tempfile
from pathlib import Path

import imagecodecs
import numpy as np

from .resources import empty_image, release_image, require_memory, strip_rows


def write_jxr(path: Path, scrgb: np.ndarray) -> Path:
    """Keep original dimensions and every FP16 sample; never replace an existing file."""
    if scrgb.ndim != 3 or scrgb.shape[2] != 3 or 0 in scrgb.shape:
        raise ValueError("Export requires a non-empty H x W x 3 linear scRGB array.")
    rows = strip_rows(scrgb.shape[1])
    for y in range(0, len(scrgb), rows):
        pixels = scrgb[y : y + rows]
        if not np.isfinite(pixels).all() or np.max(np.abs(pixels)) > np.finfo(np.float16).max:
            raise ValueError("Image contains non-finite or out-of-range FP16 values.")
    # The codec still uses a whole compressed blob. Reserve worst-case payload
    # headroom instead of assuming that a low-detail test image compresses well.
    require_memory(scrgb.shape[0] * scrgb.shape[1] * 8, "JPEG XR encoding")
    rgba = empty_image((*scrgb.shape[:2], 4), np.float16)
    decoded = None
    try:
        for y in range(0, len(scrgb), rows):
            rgba[y : y + rows, :, :3] = scrgb[y : y + rows]
            rgba[y : y + rows, :, 3] = 1
        blob = imagecodecs.jpegxr_encode(rgba, level=1.0, hasalpha=True)
        decoded = empty_image(rgba.shape, np.float16)
        restored = imagecodecs.jpegxr_decode(blob, out=decoded)
        if restored.dtype != np.float16 or restored.shape != rgba.shape:
            raise RuntimeError("JPEG XR verification failed; no output was published.")
        for y in range(0, len(rgba), rows):
            if not np.array_equal(restored[y : y + rows], rgba[y : y + rows]):
                raise RuntimeError("JPEG XR verification failed; no output was published.")
        del restored
    finally:
        release_image(decoded)
        release_image(rgba)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".rtx-hdr-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        for index in range(10_000):
            candidate = path if index == 0 else path.with_stem(f"{path.stem}_{index + 1}")
            try:
                # Windows rename is atomic and refuses existing destinations;
                # this also works on removable filesystems without hard links.
                if os.name == "nt":
                    os.rename(temporary, candidate)
                else:
                    os.link(temporary, candidate)
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError("Too many filename collisions. Choose a different output directory.")
    finally:
        Path(temporary).unlink(missing_ok=True)
