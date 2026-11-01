"""SDR loading and preview caches, independent of NVIDIA and Qt."""

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .resources import (
    MAX_PIXELS,
    empty_image,
    release_image,
    require_memory,
    strip_rows,
    validate_size,
)

SUPPORTED = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})
# Pillow identifies files by content, not by extension. Restrict identification to
# the decoders this application supports so that a renamed EPS, PSD, FITS, PDF, etc.
# can never reach Ghostscript or a rarely used decoder. (JPEG still covers MPO.)
PIL_FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "TIFF")
# Unsigned 16-bit grayscale is scaled from the full 0..65535 range (AUD-001).
UINT16_GRAY = frozenset({"I;16", "I;16L", "I;16B", "I;16N"})
# 8-bit modes that Pillow converts to RGB without changing their numeric range.
EIGHT_BIT_MODES = frozenset(
    {"1", "L", "LA", "La", "P", "PA", "RGB", "RGBA", "RGBa", "RGBX", "CMYK", "YCbCr", "LAB"}
)
# A finite decoder guard, shared by workers and background GUI loaders.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
PREVIEW_BOUNDS = (3840, 2160)
LARGE_IMAGE_PIXELS = 40_000_000  # Switch to bounded resampling, not an input limit.
PREVIEW_FILTER = Image.Resampling.LANCZOS
REDUCING_GAP = 3.0  # Area prefilter for large reductions, then a Lanczos-3 finish.


def _open(path: Path):
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Choose a PNG, JPEG, WebP, BMP, or TIFF image.")
    try:
        return Image.open(path, formats=PIL_FORMATS)
    except UnidentifiedImageError as error:
        raise ValueError(
            f"{path.name} is not a readable PNG, JPEG, WebP, BMP, or TIFF image."
        ) from error


def _check_mode(opened):
    if opened.mode not in UINT16_GRAY and opened.mode not in EIGHT_BIT_MODES:
        raise ValueError(
            f"Unsupported pixel format ({opened.mode}). Convert the image to 8-bit or "
            "unsigned 16-bit RGB or grayscale first."
        )


def _uint16_gray_to_l(image, transparency=None):
    """Full-range unsigned 16-bit gray -> 8-bit L (+ optional tRNS alpha)."""
    values = np.asarray(image).astype(np.uint32, copy=False)
    # round(v * 255 / 65535) in exact integer arithmetic; 65535 is odd, so no ties.
    gray = ((values * 510 + 65535) // 131070).astype(np.uint8)
    alpha = None
    if isinstance(transparency, int):
        alpha = Image.fromarray(np.where(values == transparency, 0, 255).astype(np.uint8))
    return Image.fromarray(gray), alpha


def _info(opened, path):
    _check_mode(opened)
    width, height = opened.size
    validate_size(width, height)
    # PNG's getexif override decodes IDAT when eXIf is absent. Header queries
    # must never decode pixels, especially before resource/size validation.
    if Image.Image.getexif(opened).get(274) in (5, 6, 7, 8):
        width, height = height, width
    validate_size(width, height)
    profile = None
    name = "Untagged; interpreted as sRGB"
    if icc := opened.info.get("icc_profile"):
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            name = ImageCms.getProfileName(profile).strip()
        except (OSError, ValueError, ImageCms.PyCMSError) as error:
            raise ValueError("Invalid ICC profile. Convert the source to sRGB first.") from error
    return {
        "filename": path.name,
        "width": width,
        "height": height,
        "input_profile": name,
        "transparency_composited": "A" in opened.getbands() or "transparency" in opened.info,
    }, profile


def image_info(path):
    path = Path(path)
    with _open(path) as opened:
        return _info(opened, path)[0]


def load_image(
    path: str | Path, background: str = "black", *, preview=False
) -> tuple[np.ndarray, dict]:
    path = Path(path)
    if background not in ("black", "white"):
        raise ValueError("Background must be black or white.")
    with _open(path) as opened:
        info, profile = _info(opened, path)
        orientation = Image.Image.getexif(opened).get(274, 1)
        if preview:
            bounds = PREVIEW_BOUNDS[::-1] if orientation in (5, 6, 7, 8) else PREVIEW_BOUNDS
            opened.draft("RGB", bounds)
        require_memory(opened.width * opened.height * 8, "image decoding")
        opened.load()
        # PNG may contain EXIF after IDAT. It is now safe to inspect it.
        if opened.format == "PNG":
            opened._exif = None
        actual_orientation = opened.getexif().get(274, 1)
        if (actual_orientation in (5, 6, 7, 8)) != (orientation in (5, 6, 7, 8)):
            info["width"], info["height"] = info["height"], info["width"]
        orientation = actual_orientation
        if preview:
            bounds = PREVIEW_BOUNDS[::-1] if orientation in (5, 6, 7, 8) else PREVIEW_BOUNDS
            opened.thumbnail(bounds, PREVIEW_FILTER, reducing_gap=REDUCING_GAP)
        ImageOps.exif_transpose(opened, in_place=True)
        transform = None
        if profile:
            try:
                mode = opened.mode if opened.mode in ("CMYK", "LAB") else "RGB"
                transform = ImageCms.buildTransform(
                    profile, ImageCms.createProfile("sRGB"), mode, "RGB"
                )
            except (OSError, ValueError, ImageCms.PyCMSError) as error:
                raise ValueError(
                    "Invalid ICC profile. Convert the source to sRGB first."
                ) from error
        rgb = empty_image((opened.height, opened.width, 3), np.uint8)
        rows = strip_rows(opened.width)
        for y in range(0, opened.height, rows):
            strip = opened.crop((0, y, opened.width, min(y + rows, opened.height)))
            if strip.mode in UINT16_GRAY:
                # Pillow's direct I;16 -> RGB conversion clips at 255 instead of scaling.
                strip, alpha = _uint16_gray_to_l(strip, opened.info.get("transparency"))
            else:
                alpha = (
                    strip.convert("RGBA").getchannel("A")
                    if info["transparency_composited"]
                    else None
                )
            source = strip if strip.mode in ("CMYK", "LAB") else strip.convert("RGB")
            converted = (
                ImageCms.applyTransform(source, transform) if transform else source.convert("RGB")
            )
            if alpha is not None:
                canvas = Image.new("RGB", converted.size, background)
                canvas.paste(converted, mask=alpha)
                converted = canvas
            rgb[y : y + rows] = np.asarray(converted)
        return rgb, info


def resize_linear(rgb: np.ndarray, width: int, height: int, box=None) -> np.ndarray:
    """Scale-aware Lanczos-3 with area prefilter; retain negative/HDR samples."""
    if box is None and rgb.shape[:2] == (height, width):
        return np.asarray(rgb, dtype=np.float32)
    if box is None and rgb.shape[0] * rgb.shape[1] > LARGE_IMAGE_PIXELS:
        # Separable filtering keeps all PIL F images small, even for huge sources.
        intermediate = empty_image((rgb.shape[0], width, 3), np.float32)
        rows = strip_rows(rgb.shape[1])
        try:
            for y in range(0, rgb.shape[0], rows):
                band = rgb[y : y + rows]
                for c in range(3):
                    intermediate[y : y + rows, :, c] = np.asarray(
                        Image.fromarray(np.asarray(band[..., c], np.float32)).resize(
                            (width, len(band)), PREVIEW_FILTER, reducing_gap=REDUCING_GAP
                        )
                    )
            output = np.empty((height, width, 3), np.float32)
            columns = strip_rows(rgb.shape[0])
            for x in range(0, width, columns):
                for c in range(3):
                    plane = np.asarray(intermediate[:, x : x + columns, c], np.float32)
                    output[:, x : x + columns, c] = np.asarray(
                        Image.fromarray(plane).resize(
                            (plane.shape[1], height), PREVIEW_FILTER, reducing_gap=REDUCING_GAP
                        )
                    )
            return output
        finally:
            release_image(intermediate)
    return np.stack(
        [
            np.asarray(
                Image.fromarray(np.asarray(rgb[..., c], np.float32)).resize(
                    (width, height), PREVIEW_FILTER, box=box, reducing_gap=REDUCING_GAP
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
    size = preview_size(rgb.shape[1], rgb.shape[0])
    if rgb.shape[0] * rgb.shape[1] > LARGE_IMAGE_PIXELS:
        rgb = np.clip(np.rint(resize_linear(rgb, *size)), 0, 255).astype(np.uint8)
    image = Image.fromarray(rgb)
    if image.size != size:
        image = image.resize(size, PREVIEW_FILTER, reducing_gap=REDUCING_GAP)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(path, format="PNG", icc_profile=profile)


def save_hdr_preview(path: Path, scrgb: np.ndarray) -> None:
    height, width = scrgb.shape[:2]
    preview = resize_linear(scrgb, *preview_size(width, height))
    np.save(path, preview.astype(np.float16), allow_pickle=False)
