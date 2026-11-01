"""SDR loading and preview caches, independent of NVIDIA and Qt."""

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

SUPPORTED = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})
MAX_PIXELS = 40_000_000
PREVIEW_BOUNDS = (3840, 2160)


def load_image(path: str | Path, background: str = "black") -> tuple[np.ndarray, dict]:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Choose a PNG, JPEG, WebP, BMP, or TIFF image.")
    if background not in ("black", "white"):
        raise ValueError("Background must be black or white.")
    with Image.open(path) as opened:
        if opened.width * opened.height > MAX_PIXELS:
            raise ValueError("Input exceeds 40 megapixels. Resize the source before processing.")
        icc = opened.info.get("icc_profile")
        image = ImageOps.exif_transpose(opened)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        alpha = image.convert("RGBA").getchannel("A") if has_alpha else None
        rgb = image.convert("RGB")
        profile_name = "Untagged; interpreted as sRGB"
        if icc:
            try:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                profile_name = ImageCms.getProfileName(profile).strip()
                source = image if image.mode in ("CMYK", "LAB") else rgb
                rgb = ImageCms.profileToProfile(
                    source, profile, ImageCms.createProfile("sRGB"), outputMode="RGB"
                )
            except (OSError, ValueError, ImageCms.PyCMSError) as error:
                raise ValueError(
                    "Invalid ICC profile. Convert the source to sRGB first."
                ) from error
        if alpha is not None:
            canvas = Image.new("RGB", rgb.size, background)
            canvas.paste(rgb, mask=alpha)
            rgb = canvas
        return np.asarray(rgb, dtype=np.uint8).copy(), {
            "filename": path.name,
            "width": rgb.width,
            "height": rgb.height,
            "input_profile": profile_name,
            "transparency_composited": has_alpha,
        }


def resize_linear(rgb: np.ndarray, width: int, height: int, box=None) -> np.ndarray:
    """Bilinear filtering in linear light, retaining negative and >1 samples."""
    if box is None and rgb.shape[:2] == (height, width):
        return np.asarray(rgb, dtype=np.float32)
    return np.stack(
        [
            np.asarray(
                Image.fromarray(np.asarray(rgb[..., c], np.float32)).resize(
                    (width, height), Image.Resampling.BILINEAR, box=box
                )
            )
            for c in range(3)
        ],
        axis=-1,
    )


def preview_size(width: int, height: int) -> tuple[int, int]:
    """Fit inside the preview bounds without upscaling or changing orientation."""
    scale = min(1.0, PREVIEW_BOUNDS[0] / width, PREVIEW_BOUNDS[1] / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def save_sdr_preview(path: Path, rgb: np.ndarray) -> None:
    image = Image.fromarray(rgb)
    size = preview_size(*image.size)
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(path, format="PNG", icc_profile=profile)


def save_hdr_preview(path: Path, scrgb: np.ndarray) -> None:
    height, width = scrgb.shape[:2]
    preview = resize_linear(scrgb, *preview_size(width, height))
    np.save(path, preview.astype(np.float16), allow_pickle=False)
