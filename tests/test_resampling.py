import numpy as np
import pytest
from PIL import Image
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from rtx_hdr_studio import image_io
from rtx_hdr_studio.image_io import resize_linear
from rtx_hdr_studio.resources import ScratchSpace
from rtx_hdr_studio.ui.canvas import CompareCanvas


def test_sdr_canvas_minification_filters_checkerboard(wait_until):
    app = QApplication.instance() or QApplication([])
    pixels = ((np.indices((1024, 1280)).sum(axis=0) & 1) * 255).astype(np.uint8)
    image = QImage(pixels.data, 1280, 1024, 1280, QImage.Format.Format_Grayscale8).copy()
    canvas = CompareCanvas()
    canvas.prefer_hdr = False
    canvas.mode = "before"
    canvas.scale_mode = "stretch"
    canvas.image_margin = 0
    canvas.resize(281, 263)
    canvas.set_images(QPixmap.fromImage(image))
    canvas.show()
    app.processEvents()
    try:
        wait_until(lambda: canvas._sdr_prepared is not None)
        rendered = canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        data = np.frombuffer(rendered.constBits(), np.uint8).reshape(
            rendered.height(), rendered.bytesPerLine()
        )
        gray = data[:, : rendered.width() * 4].reshape(rendered.height(), rendered.width(), 4)[
            4:-4, 4:-4, 0
        ]
        assert abs(float(gray.mean()) - 127.5) < 2
        assert float(gray.std()) < 5  # Nearest-neighbor rendering was about 127.5.
        token = canvas.sdr_task._generation
        canvas.split = 0.7
        canvas.mode = "split"
        canvas.update()
        app.processEvents()
        assert canvas.sdr_task._generation == token  # Divider/view changes reuse filtered pixels.
    finally:
        canvas.shutdown()
        canvas.close()
        app.processEvents()


def test_hdr_minification_averages_subpixel_detail_and_preserves_range():
    checker = (np.indices((1103, 2071)).sum(axis=0) & 1).astype(np.float32)
    pixels = np.stack(
        [checker * 12.5, np.full_like(checker, -0.125), np.full_like(checker, 2.5)], -1
    )
    resized = resize_linear(pixels, 103, 59)
    np.testing.assert_allclose(resized[4:-4, 4:-4, 0], 6.25, atol=0.002)
    np.testing.assert_allclose(resized[..., 1], -0.125, atol=1e-6)
    np.testing.assert_allclose(resized[..., 2], 2.5, atol=1e-6)
    # No-scaling mode must not blur original pixels.
    np.testing.assert_array_equal(resize_linear(pixels, 2071, 1103), pixels)


@pytest.mark.parametrize("size", [(43, 37), (311, 229)])
def test_bounded_lanczos_has_no_strip_seams(tmp_path, monkeypatch, size):
    monkeypatch.setattr(image_io, "LARGE_IMAGE_PIXELS", 1)
    pixels = np.random.default_rng(42).uniform(-0.5, 12.5, (913, 721, 3)).astype(np.float32)
    with ScratchSpace(tmp_path):
        actual = resize_linear(pixels, *size)
    reference = np.stack(
        [
            np.asarray(
                Image.fromarray(pixels[..., c]).resize(
                    size, Image.Resampling.LANCZOS, reducing_gap=3.0
                )
            )
            for c in range(3)
        ],
        -1,
    )
    np.testing.assert_allclose(actual, reference, atol=3e-6)


def test_fill_crop_lanczos_uses_visible_source_region():
    pixels = np.zeros((100, 1000, 3), np.float32)
    pixels[:, 475:525] = [12.5, -0.125, 2.5]
    cropped = resize_linear(pixels, 100, 100, box=(450, 0, 550, 100))
    np.testing.assert_array_equal(cropped[50, 50], [12.5, -0.125, 2.5])
    np.testing.assert_array_equal(cropped[50, 10], [0, 0, 0])
