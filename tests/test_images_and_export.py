import numpy as np
import pytest
from PIL import Image, ImageCms

from rtx_hdr_studio.export import write_jxr
from rtx_hdr_studio.image_io import (
    image_info,
    load_image,
    preview_size,
    resize_linear,
    save_hdr_preview,
    save_sdr_preview,
)


def test_alpha_compositing_and_unicode_paths(tmp_path):
    path = tmp_path / "image-\u00e9.png"
    Image.new("RGBA", (7, 5), (255, 0, 0, 128)).save(path)
    black, info = load_image(path)
    white, _ = load_image(path, "white")
    np.testing.assert_array_equal(black[0, 0], [128, 0, 0])
    np.testing.assert_array_equal(white[0, 0], [255, 127, 127])
    assert info["transparency_composited"]


def test_orientation_and_icc(tmp_path):
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (6, 4), (128, 128, 128))
    exif = Image.Exif()
    exif[274] = 6
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image.save(path, exif=exif, icc_profile=profile)
    rgb, info = load_image(path)
    assert rgb.shape == (6, 4, 3) and "sRGB" in info["input_profile"]


GRAY16 = np.array([[0, 128, 255, 256, 16384, 32768, 65535]], np.uint16)
GRAY16_AS_8BIT = [0, 0, 1, 1, 64, 128, 255]


@pytest.mark.parametrize(
    "name, mode", [("gray.png", "I;16"), ("gray.tiff", "I;16"), ("big.tiff", "I;16B")]
)
def test_unsigned_16bit_grayscale_uses_the_full_input_range(tmp_path, name, mode):
    path = tmp_path / name
    raw = GRAY16.astype(">u2" if mode == "I;16B" else "<u2").tobytes()
    Image.frombytes(mode, GRAY16.shape[::-1], raw).save(path)
    with Image.open(path) as opened:
        assert opened.mode == mode  # Guard the fixture, not only the result.
    rgb, _ = load_image(path)
    np.testing.assert_array_equal(rgb[0], np.repeat(np.array(GRAY16_AS_8BIT)[:, None], 3, 1))


def test_unsigned_16bit_grayscale_preview_keeps_mid_gray(tmp_path):
    path = tmp_path / "large.png"
    Image.fromarray(np.full((2200, 4000), 32768, np.uint16)).save(path)
    rgb, info = load_image(path, preview=True)
    assert rgb.shape == (2112, 3840, 3) and (info["width"], info["height"]) == (4000, 2200)
    assert np.all(rgb == 128)


def test_unsigned_16bit_grayscale_key_transparency_is_composited(tmp_path):
    import struct
    import zlib

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    pixels = np.array([[32768, 65535, 1000]], ">u2")
    path = tmp_path / "keyed.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 1, 16, 0, 0, 0, 0))
        + chunk(b"tRNS", struct.pack(">H", 1000))
        + chunk(b"IDAT", zlib.compress(b"\0" + pixels.tobytes()))
        + chunk(b"IEND", b"")
    )
    black, info = load_image(path)
    white, _ = load_image(path, "white")
    assert info["transparency_composited"]
    assert black[0, :, 0].tolist() == [128, 255, 0]
    assert white[0, :, 0].tolist() == [128, 255, 255]


@pytest.mark.parametrize("array", [GRAY16.astype(np.float32), GRAY16.astype(np.int32)])
def test_signed_and_floating_point_inputs_are_rejected_instead_of_clipped(tmp_path, array):
    path = tmp_path / "unsupported.tiff"
    Image.fromarray(array).save(path)
    for read in (image_info, load_image):
        with pytest.raises(ValueError, match="Unsupported pixel format"):
            read(path)


def test_content_sniffing_is_limited_to_supported_decoders(tmp_path):
    path = tmp_path / "holiday.png"
    Image.new("RGB", (8, 8), "red").save(path, format="EPS")
    with Image.open(path) as unrestricted:
        assert unrestricted.format == "EPS"  # Pillow would hand this to Ghostscript.
    for read in (image_info, load_image):
        with pytest.raises(ValueError, match="not a readable"):
            read(path)


def test_multi_picture_camera_jpeg_still_opens(tmp_path):
    path = tmp_path / "camera.jpg"
    Image.new("RGB", (8, 6), "red").save(
        path, format="MPO", save_all=True, append_images=[Image.new("RGB", (8, 6), "blue")]
    )
    rgb, info = load_image(path)
    assert rgb.shape == (6, 8, 3) and info["width"] == 8


def test_export_preserves_hdr_and_odd_dimensions_without_overwriting(tmp_path):
    import imagecodecs

    pixels = np.full((13, 17, 3), [12.5, -0.125, 2.5], np.float32)
    path = write_jxr(tmp_path / "image.jxr", pixels)
    original = path.read_bytes()
    duplicate = write_jxr(path, pixels)
    assert duplicate != path and path.read_bytes() == original
    restored = imagecodecs.jpegxr_decode(original)
    assert restored.dtype == np.float16 and restored.shape == (13, 17, 4)
    np.testing.assert_array_equal(restored[..., :3], pixels.astype(np.float16))
    np.testing.assert_array_equal(restored[..., 3], 1)


@pytest.mark.parametrize("value", [np.nan, np.inf, 70000])
def test_export_rejects_invalid_samples_before_publishing(tmp_path, value):
    path = tmp_path / "bad.jxr"
    with pytest.raises(ValueError):
        write_jxr(path, np.full((2, 2, 3), value, np.float32))
    assert not path.exists()


def test_preview_resize_retains_negative_and_highlight_values(tmp_path):
    pixels = np.full((19, 4000, 3), [12.5, -0.125, 2.5], np.float32)
    resized = resize_linear(pixels, 33, 17)
    np.testing.assert_array_equal(resized[0, 0], [12.5, -0.125, 2.5])
    path = tmp_path / "cache.npy"
    save_hdr_preview(path, pixels)
    preview = np.load(path, allow_pickle=False)
    assert preview.shape[1] == 3840
    np.testing.assert_array_equal(preview[0, 0], [12.5, -0.125, 2.5])


@pytest.mark.parametrize(
    "size, expected",
    [
        ((3840, 2160), (3840, 2160)),
        ((1920, 1080), (1920, 1080)),
        ((2000, 2000), (2000, 2000)),
        ((4000, 2000), (3840, 1920)),
        ((3000, 2400), (2700, 2160)),
        ((7680, 4320), (3840, 2160)),
        ((2160, 3840), (1215, 2160)),
    ],
)
def test_preview_bounds_preserve_aspect_ratio_without_upscaling(size, expected):
    assert preview_size(*size) == expected


@pytest.mark.parametrize("size", [(4000, 19), (19, 2400), (2001, 19), (19, 19)])
def test_sdr_and_hdr_caches_use_identical_bounds(tmp_path, size):
    width, height = size
    sdr = np.full((height, width, 3), 128, np.uint8)
    hdr = np.full((height, width, 3), [12.5, -0.125, 2.5], np.float32)
    sdr_path, hdr_path = tmp_path / "sdr.png", tmp_path / "hdr.npy"
    save_sdr_preview(sdr_path, sdr)
    save_hdr_preview(hdr_path, hdr)
    expected = preview_size(width, height)
    with Image.open(sdr_path) as preview:
        assert preview.size == expected
    restored = np.load(hdr_path, allow_pickle=False)
    assert restored.shape == (expected[1], expected[0], 3)
    assert restored.dtype == np.float16
    np.testing.assert_array_equal(restored[0, 0], [12.5, -0.125, 2.5])
