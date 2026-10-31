"""Verified FP16 scRGB JPEG XR export with collision-safe publication."""

import os
import tempfile
from pathlib import Path

import imagecodecs
import numpy as np


def write_jxr(path: Path, scrgb: np.ndarray) -> Path:
    """Keep original dimensions and every FP16 sample; never replace an existing file."""
    if scrgb.ndim != 3 or scrgb.shape[2] != 3 or 0 in scrgb.shape:
        raise ValueError("Export requires a non-empty H x W x 3 linear scRGB array.")
    if not np.isfinite(scrgb).all() or np.max(np.abs(scrgb)) > np.finfo(np.float16).max:
        raise ValueError("Image contains non-finite or out-of-range FP16 values.")
    rgba = np.ones((*scrgb.shape[:2], 4), np.float16)
    rgba[..., :3] = scrgb.astype(np.float16)
    blob = imagecodecs.jpegxr_encode(rgba, level=1.0, hasalpha=True)
    decoded = imagecodecs.jpegxr_decode(blob)
    if decoded.dtype != np.float16 or not np.array_equal(decoded, rgba):
        raise RuntimeError("JPEG XR verification failed; no output was published.")
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
