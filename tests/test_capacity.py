import ctypes
import os
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from rtx_hdr_studio import image_io, resources
from rtx_hdr_studio.color import LUMA_709, hdr_statistics
from rtx_hdr_studio.export import write_jxr
from rtx_hdr_studio.image_io import image_info, load_image, resize_linear
from rtx_hdr_studio.native_vfx import ImageDescriptor
from rtx_hdr_studio.resources import MAX_PIXELS, GiB, ProcessingLock, ScratchSpace
from rtx_hdr_studio.ui.memory_usage import MemoryEstimate, pressure_color


def header_png(path, width, height):
    def chunk(name, data):
        return (
            struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


def test_frontend_limit_checks_headers_before_decoding(tmp_path):
    path = tmp_path / "huge.png"
    header_png(path, 30720, 30720)
    assert image_info(path)["width"] * image_info(path)["height"] == MAX_PIXELS
    assert Image.MAX_IMAGE_PIXELS == MAX_PIXELS
    header_png(path, 30721, 30720)
    with pytest.warns(Image.DecompressionBombWarning):
        with pytest.raises(ValueError, match="943.72 MP"):
            load_image(path)


def test_gpu_admission_checks_commit_independently_from_ram(monkeypatch):
    monkeypatch.setattr(resources, "memory_available", lambda: (32 * GiB, 2 * GiB))
    with pytest.raises(MemoryError, match="commit headroom"):
        resources.require_memory(GiB, "GPU allocation", commit_size=3 * GiB, reserve=0)
    monkeypatch.setattr(resources, "memory_available", lambda: (2 * GiB, 32 * GiB))
    with pytest.raises(MemoryError):
        resources.require_memory(3 * GiB, "CPU allocation", reserve=0)


def test_preview_decode_preserves_source_metadata_and_orientation(tmp_path):
    path = tmp_path / "large.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (4400, 2200), "red").save(path, exif=exif)
    pixels, info = load_image(path, preview=True)
    assert (info["width"], info["height"]) == (2200, 4400)
    assert pixels.shape[:2] == (2160, 1080)
    assert pixels[0, 0, 0] > 250


def test_mapped_buffers_are_verified_released_and_removed(tmp_path, monkeypatch):
    import imagecodecs

    monkeypatch.setattr(resources, "MAP_THRESHOLD", 1)
    with ScratchSpace(tmp_path) as scratch:
        data = resources.empty_image((19, 23, 3), np.float32)
        assert isinstance(data, np.memmap)
        data[:] = [12.5, -0.125, 2.5]
        result = write_jxr(tmp_path / "mapped.jxr", data)
        restored = imagecodecs.jpegxr_decode(result.read_bytes())
        np.testing.assert_array_equal(restored[..., :3], data.astype(np.float16))
        assert sum(a is not None for a in scratch.arrays) == 1
        directory = scratch.temp.name
    assert not os.path.exists(directory)


def test_separable_resize_and_chunked_statistics(tmp_path, monkeypatch):
    monkeypatch.setattr(image_io, "LARGE_IMAGE_PIXELS", 20)
    monkeypatch.setattr(resources, "MAP_THRESHOLD", 1)
    rng = np.random.default_rng(10)
    pixels = rng.uniform(-1, 12, (113, 97, 3)).astype(np.float32)
    with ScratchSpace(tmp_path) as scratch:
        actual = resize_linear(pixels, 31, 29)
        assert all(a is None for a in scratch.arrays)
    expected = np.stack(
        [
            np.asarray(
                Image.fromarray(pixels[..., c]).resize(
                    (31, 29), Image.Resampling.LANCZOS, reducing_gap=3.0
                )
            )
            for c in range(3)
        ],
        axis=-1,
    )
    np.testing.assert_allclose(actual, expected, atol=2e-6)
    luminance = np.maximum(pixels @ LUMA_709, 0) * 80
    stats = hdr_statistics(pixels)
    assert stats["average_luminance_nits"] == pytest.approx(float(luminance.mean()), abs=0.001)
    assert stats["negative_channel_fraction"] == pytest.approx(float(np.mean(pixels < 0)), abs=1e-6)


@pytest.mark.parametrize(
    "ratio,color",
    [
        (0, "#8bd89a"),
        (0.7999, "#8bd89a"),
        (0.8, "#efc75e"),
        (0.8999, "#efc75e"),
        (0.9, "#ff6b6b"),
        (1.5, "#ff6b6b"),
    ],
)
def test_memory_colors(ratio, color):
    assert pressure_color(ratio * 8 * GiB, 8 * GiB) == color


def test_memory_bar_keeps_fixed_capacity_and_full_overflow():
    app = QApplication.instance() or QApplication([])
    widget = MemoryEstimate()
    widget.set_gpu({"device": 0, "name": "Test GPU", "total": 8 * GiB})
    widget.set_image({"width": 20000, "height": 20000})
    assert widget.bar.capacity == 8 * GiB
    assert widget.bar.estimate > 12 * GiB
    assert "12.19 / 8.00" in widget.value.text()
    assert "4.19 GiB shared" in widget.overflow.text()
    widget.set_image({"width": 10000, "height": 10000})
    assert widget.bar.capacity == 8 * GiB and not widget.overflow.isVisible()
    widget.set_gpu(None, "Driver unavailable")
    assert "unavailable" in widget.value.text() and widget.bar.capacity == 0
    assert "Driver unavailable" in widget.toolTip()
    widget.close()
    app.processEvents()


@pytest.mark.skipif(os.name != "nt", reason="Windows processing mutex")
def test_simultaneous_worker_is_rejected_and_lock_released():
    def enter():
        with ProcessingLock():
            return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        with ProcessingLock():
            with pytest.raises(RuntimeError, match="already running"):
                pool.submit(enter).result(timeout=5)
        assert pool.submit(enter).result(timeout=5)
    assert ctypes.sizeof(ImageDescriptor) == 64
