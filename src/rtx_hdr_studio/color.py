from __future__ import annotations

import numpy as np

BT2020_TO_709 = np.array(
    [
        [1.6604910021, -0.5876411388, -0.0728498633],
        [-0.1245504745, 1.1328998971, -0.0083494226],
        [-0.0181507634, -0.1005788980, 1.1187296614],
    ],
    dtype=np.float64,
)
LUMA_709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float32)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.maximum(np.asarray(rgb, dtype=np.float32), 0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)


def pq_to_nits(code: np.ndarray) -> np.ndarray:
    m1, m2 = 2610 / 16384, 2523 / 32
    c1, c2, c3 = 3424 / 4096, 2413 / 128, 2392 / 128
    p = np.clip(np.asarray(code, dtype=np.float64), 0, 1) ** (1 / m2)
    return 10000 * (np.maximum(p - c1, 0) / (c2 - c3 * p)) ** (1 / m1)


def packed_pq_to_scrgb(packed: np.ndarray) -> np.ndarray:
    """Full-range little-endian RGB10A2/PQ BT.2020 -> linear scRGB, 1 = 80 nits."""
    if packed.dtype != np.uint32 or packed.ndim != 2:
        raise ValueError("TrueHDR output must be a two-dimensional uint32 RGB10A2 array.")
    lut = pq_to_nits(np.arange(1024, dtype=np.float64) / 1023)
    height, width = packed.shape
    output = np.empty((height, width, 3), dtype=np.float32)
    for y in range(0, height, 128):
        pixels = packed[y : y + 128]
        rgb = np.stack(
            (lut[pixels & 1023], lut[(pixels >> 10) & 1023], lut[(pixels >> 20) & 1023]), axis=-1
        )
        output[y : y + 128] = (rgb @ BT2020_TO_709.T) / 80
    return output


def sdr_preview(scrgb: np.ndarray, peak_nits: float = 650) -> np.ndarray:
    """Luminance-based SDR tonemap for the UI; this is deliberately not HDR output."""
    rgb = np.maximum(scrgb, 0) * (80 / 203)
    luminance = rgb @ LUMA_709
    white = max(float(peak_nits) / 203, 1)
    mapped = luminance * (1 + luminance / (white * white)) / (1 + luminance)
    rgb *= (mapped / np.maximum(luminance, 1e-8))[..., None]
    return np.round(np.clip(linear_to_srgb(rgb), 0, 1) * 255).astype(np.uint8)


def hdr_statistics(scrgb: np.ndarray) -> dict:
    luminance = np.maximum(scrgb @ LUMA_709, 0) * 80
    return {
        "peak_luminance_nits": round(float(luminance.max()), 3),
        "average_luminance_nits": round(float(luminance.mean()), 3),
        "negative_channel_fraction": round(float(np.mean(scrgb < 0)), 6),
        "above_sdr_white_fraction": round(float(np.mean(luminance > 203)), 6),
    }
