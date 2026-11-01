import os
import sys

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

native_only = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("RTX_HDR_RUN_NATIVE") != "1",
    reason="Windows and explicit native opt-in required",
)


@pytest.mark.native
@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("RTX_HDR_RUN_NATIVE") != "1",
    reason="Windows and explicit native opt-in required",
)
def test_fp16_gpu_readback_and_resize():
    from rtx_hdr_studio.graphics.directx import Presenter

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(127, 83)
    renderer = Presenter(int(window.winId()), 127, 83)
    try:
        for w, h in ((127, 83), (211, 119)):
            renderer.resize(w, h)
            pixels = np.full((h, w, 4), [12.5, -0.125, 2.5, 1], np.float16)
            renderer.upload(pixels)
            np.testing.assert_array_equal(renderer.readback(), pixels)
            renderer.present()
    finally:
        renderer.close()
        window.close()
        app.processEvents()


@pytest.mark.native
@native_only
def test_fullscreen_native_hdr_rendering_and_exit(tmp_path, wait_until):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPixmap
    from PySide6.QtTest import QTest

    from rtx_hdr_studio.graphics.display import query_display
    from rtx_hdr_studio.ui.window import StudioWindow

    app = QApplication.instance() or QApplication([])
    if app.platformName() != "windows":
        pytest.skip("Set QT_QPA_PLATFORM=windows for actual full-screen HDR validation")
    window = StudioWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    try:
        assert QTest.qWaitForWindowActive(window, 3000)
        if not query_display(int(window.canvas.winId())).hdr_active:
            pytest.skip("Actual full-screen HDR validation requires Windows HDR enabled")
        image = QPixmap(128, 72)
        image.fill(QColor(128, 128, 128))
        cache = tmp_path / "hdr.npy"
        np.save(cache, np.full((72, 128, 3), [12.5, -0.125, 2.5], np.float16))
        window.canvas.set_images(image, image, cache)
        device_pointer = None
        for mode, method, scaling in (
            ("after", "doubleclick", "fit"),
            ("after", "escape", "fill"),
            ("split", "escape", "stretch"),
            ("before", "deactivate", "actual"),
        ):
            window.canvas.mode = mode
            window.fullscreen_scale.setCurrentIndex(window.fullscreen_scale.findData(scaling))
            if method == "doubleclick":
                QTest.mouseDClick(
                    window.canvas.hdr_surface,
                    Qt.MouseButton.LeftButton,
                    pos=window.canvas.image_rect().center().toPoint(),
                )
            else:
                window.fullscreen_button.click()
            viewer = window.fullscreen_preview
            assert QTest.qWaitForWindowActive(viewer, 3000)
            canvas = viewer.canvas
            wait_until(lambda: canvas.hdr_active and canvas.hdr_surface.renderer is not None, 10000)
            assert canvas.scale_mode == scaling
            assert canvas.hdr_active and not canvas.hdr_error
            surface = canvas.hdr_surface
            assert surface.renderer is not None and surface.renderer.frames > 0
            pointer = surface.renderer.device.value
            if device_pointer is not None:
                assert pointer == device_pointer
            device_pointer = pointer
            assert pointer == window.preview_device.resources.device.value
            if not window._fullscreen_hint_seen:
                assert canvas.hint_visible
                QTest.qWait(3100)
                assert window._fullscreen_hint_seen
            else:
                assert not canvas.hint_visible
                assert not canvas.hint_timer.isActive()
            assert not canvas.hint_visible
            if mode == "split":
                area = canvas.image_rect()
                start = area.center().toPoint()
                end = QPoint(round(area.x() + area.width() * 0.7), start.y())
                QTest.mousePress(surface, Qt.MouseButton.LeftButton, pos=start)
                app.sendEvent(
                    surface,
                    QMouseEvent(
                        QEvent.Type.MouseMove,
                        QPointF(end),
                        QPointF(surface.mapToGlobal(end)),
                        Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier,
                    ),
                )
                QTest.mouseRelease(surface, Qt.MouseButton.LeftButton, pos=end)
                assert canvas.split == pytest.approx(end.x() / canvas.width())
                assert window.canvas.split == 0.5
            # Flip-discard backbuffers are undefined after Present. Read our frame
            # immediately before presentation, as the buffer-only test does.
            captured = []
            present = surface.renderer.present

            def capture_and_present():
                captured.append(surface.renderer.readback())
                present()

            surface.renderer.present = capture_and_present
            surface.update()
            QTest.qWait(50)
            surface.renderer.present = present
            assert captured
            buffer = captured[-1]
            original = np.append(
                surface.before_linear[0, 0] * canvas.display_info.sdr_white_nits / 80, 1
            ).astype(np.float16)
            processed = np.array([12.5, -0.125, 2.5, 1], np.float16)
            rect = canvas.image_rect()
            ratio = canvas.devicePixelRatioF()
            for fraction in (0.25, 0.75):
                sample = buffer[
                    round(rect.center().y() * ratio),
                    round((rect.x() + rect.width() * fraction) * ratio),
                ]
                expected = (
                    processed
                    if mode == "after" or (mode == "split" and fraction > 0.5)
                    else original
                )
                np.testing.assert_array_equal(sample, expected)
            if mode == "split":
                sample = buffer[
                    round((rect.y() + rect.height() * 0.25) * ratio),
                    round((rect.x() + rect.width() * 0.6) * ratio),
                ]
                np.testing.assert_array_equal(sample, original)
            if scaling == "actual":
                assert round(rect.width() * ratio) == 128
                assert round(rect.height() * ratio) == 72
                assert np.all(buffer[..., :3] == original[:3], axis=2).sum() == 128 * 72
            # Moving over the native child after the one-time hint expires must
            # not restore it or restart its timer.
            position = QPoint(30, 40)
            if QCursor.pos() == surface.mapToGlobal(position):
                position = QPoint(80, 90)
            QTest.mouseMove(surface, position)
            QTest.qWait(30)
            assert not canvas.hint_visible
            assert not canvas.hint_timer.isActive()
            assert window.fullscreen_preview is viewer
            if method == "doubleclick":
                QTest.mouseDClick(
                    surface, Qt.MouseButton.LeftButton, pos=canvas.image_rect().center().toPoint()
                )
            elif method == "escape":
                surface.setFocus()
                QTest.keyClick(surface, Qt.Key.Key_Escape)
            else:
                other = QWidget()
                other.setWindowTitle("Full-screen focus validation")
                other.show()
                other.activateWindow()
                try:
                    assert QTest.qWaitForWindowActive(other, 3000)
                    QTest.qWait(30)
                    assert window.fullscreen_preview is None
                finally:
                    other.close()
            assert window.fullscreen_preview is None
            assert surface.renderer is None
            app.processEvents()
            window.activateWindow()
            assert QTest.qWaitForWindowActive(window, 3000)
        # A new image must reuse the main surface's swap chain and shared device.
        wait_until(
            lambda: window.canvas.hdr_active and window.canvas.hdr_surface.renderer is not None
        )
        main_renderer = window.canvas.hdr_surface.renderer
        window.canvas.set_images(image.copy(), image.copy(), cache)
        wait_until(lambda: window.canvas.hdr_active)
        assert window.canvas.hdr_surface.renderer is main_renderer
        assert main_renderer.device.value == device_pointer
    finally:
        window.close()
        app.processEvents()


@pytest.mark.native
@native_only
def test_gpu_side_split_composition_matches_the_cpu_reference():
    from rtx_hdr_studio.graphics.directx import Presenter
    from rtx_hdr_studio.ui.composition import (
        composition_plan,
        divider_color,
        present_plan,
        render_region,
    )

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(211, 119)
    renderer = Presenter(int(window.winId()), 211, 119)
    try:
        rng = np.random.default_rng(8)
        before = rng.normal(1, 2, (119, 211, 4)).astype(np.float16)
        after = rng.normal(5, 3, (119, 211, 4)).astype(np.float16)
        before[..., 3] = after[..., 3] = 1
        key = object()
        renderer.set_sources(key, before, after)
        textures = [texture.value for texture in renderer.sources]
        renderer.set_sources(key, before, after)  # Same frame: no second upload.
        assert [texture.value for texture in renderer.sources] == textures
        color = divider_color(240)
        for mode, split in (("split", 0.3), ("split", 0.0), ("after", 0.5), ("before", 0.5)):
            copies, divider = composition_plan(mode, 211, split, 7, 100, 2)
            present_plan(renderer, 211, copies, divider, color)
            patch = render_region((before, after), copies, divider, color, 50, 40, 60, 20)
            patch[..., :3] += 1
            renderer.upload_region(50, 40, patch)
            expected = render_region((before, after), copies, divider, color, 0, 0, 211, 119)
            expected[40:60, 50:110] = patch
            # Flip-discard buffers are undefined after Present; read back first.
            np.testing.assert_array_equal(renderer.readback(), expected)
            renderer.present()
    finally:
        renderer.close()
        window.close()
        app.processEvents()


@pytest.mark.native
@native_only
def test_device_loss_rebuilds_the_hdr_preview_and_other_errors_fall_back(tmp_path, wait_until):
    """AUD-004 fault injection: Present reports DXGI_ERROR_DEVICE_REMOVED once."""
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtTest import QTest

    from rtx_hdr_studio.graphics.directx import DirectXError
    from rtx_hdr_studio.graphics.display import query_display
    from rtx_hdr_studio.ui.window import StudioWindow

    app = QApplication.instance() or QApplication([])
    if app.platformName() != "windows":
        pytest.skip("Set QT_QPA_PLATFORM=windows for native HDR validation")
    window = StudioWindow()
    window.show()
    try:
        assert QTest.qWaitForWindowActive(window, 3000)
        if not query_display(int(window.canvas.winId())).hdr_active:
            pytest.skip("Native HDR validation requires Windows HDR enabled")
        image = QPixmap(128, 72)
        image.fill(QColor(128, 128, 128))
        cache = tmp_path / "hdr.npy"
        np.save(cache, np.full((72, 128, 3), [12.5, -0.125, 2.5], np.float16))
        window.canvas.set_images(image, image, cache)
        canvas = window.canvas
        wait_until(lambda: canvas.hdr_active and canvas.hdr_surface.renderer is not None, 10000)
        surface = canvas.hdr_surface
        old_renderer, old_device = surface.renderer, window.preview_device.resources

        def removed():
            raise DirectXError("Present HDR frame", 0x887A0005 - 2**32)

        old_renderer.present = removed
        surface.update()
        wait_until(
            lambda: (
                window.preview_device.resources not in (None, old_device)
                and canvas.hdr_active
                and surface.renderer not in (None, old_renderer)
                and surface.renderer.frames > 0
            ),
            10000,
        )
        assert not old_renderer.swap and not canvas.hdr_error
        assert surface.renderer.device.value == window.preview_device.resources.device.value

        # Any other failure keeps the SDR fallback and does not rebuild the device.
        device = window.preview_device.resources

        def other():
            raise DirectXError("Present HDR frame", 0x8007000E - 2**32)

        surface.renderer.present = other
        surface.update()
        wait_until(lambda: bool(canvas.hdr_error), 5000)
        assert not canvas.hdr_active and window.preview_device.resources is device
    finally:
        window.close()
        app.processEvents()
