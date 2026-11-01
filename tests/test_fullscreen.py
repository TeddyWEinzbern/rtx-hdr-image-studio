import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rtx_hdr_studio.ui.fullscreen import FullscreenCanvas
from rtx_hdr_studio.ui.native_preview import HdrSurface, pixmap_to_linear
from rtx_hdr_studio.ui.preview_tasks import prepare_frames
from rtx_hdr_studio.ui.window import StudioWindow


@pytest.fixture
def studio():
    app = QApplication.instance() or QApplication([])
    window = StudioWindow()
    window.show()
    app.processEvents()
    yield window
    window.close()
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def show_preview(window):
    before, after = QPixmap(160, 90), QPixmap(160, 90)
    before.fill(Qt.GlobalColor.red)
    after.fill(Qt.GlobalColor.green)
    window.canvas.set_images(before, after)
    window.update_notice()
    window.fullscreen_button.click()
    QApplication.processEvents()
    return window.fullscreen_preview


def move_mouse(target, position, buttons=Qt.MouseButton.NoButton):
    # Offscreen has no system cursor; dispatch the same Qt event explicitly.
    QApplication.sendEvent(
        target,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(position),
            QPointF(target.mapToGlobal(position)),
            Qt.MouseButton.NoButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_fullscreen_entry_snapshot_and_escape(studio):
    assert not studio.fullscreen_button.isEnabled()
    studio.show_fullscreen_preview()
    assert studio.fullscreen_preview is None
    studio.canvas.mode, studio.canvas.split = "after", 0.73
    viewer = show_preview(studio)
    assert viewer.isFullScreen()
    assert viewer.screen() == studio.canvas.screen()
    assert viewer.canvas.mode == "after" and viewer.canvas.split == 0.73
    assert viewer.canvas.prefer_hdr == studio.canvas.prefer_hdr
    studio.show_fullscreen_preview()
    assert studio.fullscreen_preview is viewer
    # A completed background job can replace the main preview, never the open snapshot.
    studio.canvas.set_images(QPixmap())
    assert viewer.canvas.before.toImage().pixelColor(0, 0) == Qt.GlobalColor.red
    assert viewer.canvas.after.toImage().pixelColor(0, 0) == Qt.GlobalColor.green
    QTest.keyClick(viewer.canvas, Qt.Key.Key_Escape)
    assert studio.fullscreen_preview is None
    assert not viewer.canvas.hint_timer.isActive()
    assert not viewer.canvas.display_timer.isActive()


def test_centered_hint_hides_after_three_seconds_and_mouse_does_not_restore_it(studio):
    viewer = show_preview(studio)
    canvas = viewer.canvas
    assert canvas.hint_rect().center() == canvas.rect().center()
    QTest.qWait(1800)
    assert canvas.hint_visible
    move_mouse(canvas, QPoint(30, 35))
    QTest.qWait(1300)
    assert not canvas.hint_visible
    assert not canvas.hint_timer.isActive()
    move_mouse(canvas, QPoint(45, 40))
    assert not canvas.hint_visible
    assert not canvas.hint_timer.isActive()
    # Single clicks and mouse movement must not restart the one-time hint.
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 60))
    move_mouse(canvas, QPoint(90, 60))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 60))
    assert studio.fullscreen_preview is viewer
    assert not canvas.hint_visible


@pytest.mark.parametrize("scaling", ["fit", "fill", "stretch", "actual"])
@pytest.mark.parametrize("native", [False, True])
def test_fullscreen_drag_updates_comparison_in_each_scaling_mode(studio, scaling, native):
    studio.fullscreen_scale.setCurrentIndex(studio.fullscreen_scale.findData(scaling))
    viewer = show_preview(studio)
    canvas = viewer.canvas
    canvas.hint_timer.stop()
    canvas.hint_timer.timeout.emit()
    area = canvas.image_rect()
    target = canvas
    if native:
        target = HdrSurface(canvas)
        target.setGeometry(canvas.rect())
        target.before_linear = pixmap_to_linear(canvas.before)
        target.after_linear = np.full((90, 160, 3), [12.5, -0.125, 2.5], np.float16)
    start = area.center().toPoint()
    end = QPoint(round(area.x() + area.width() * 0.75), start.y())
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=start)
    move_mouse(target, end, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.split == pytest.approx(end.x() / canvas.width())
    assert studio.canvas.split == 0.5
    assert studio.fullscreen_preview is viewer
    assert not canvas.hint_visible and not canvas.hint_timer.isActive()
    # The newly exposed original region was on the processed side before the drag.
    x = round(area.x() + area.width() * 0.6)
    y = round(area.y() + area.height() * 0.25)
    ratio = canvas.devicePixelRatioF()
    if native:
        target.prepared = prepare_frames(
            target.before_linear,
            target.after_linear,
            round(canvas.width() * ratio),
            round(canvas.height() * ratio),
            canvas.display_info.sdr_white_nits / 80,
            canvas.scale_mode,
            0,
        )
        frame = target.compose(round(canvas.width() * ratio), round(canvas.height() * ratio))
        white = canvas.display_info.sdr_white_nits / 80
        np.testing.assert_array_equal(
            frame[round(y * ratio), round(x * ratio), :3], np.array([white, 0, 0], np.float16)
        )
    else:
        image = canvas.grab().toImage()
        assert image.pixelColor(round(x * ratio), round(y * ratio)) == Qt.GlobalColor.red
    # Passive movement after releasing the button must not continue dragging.
    split = canvas.split
    move_mouse(target, start)
    assert canvas.split == split
    QTest.mouseDClick(target, Qt.MouseButton.LeftButton, pos=start)
    assert studio.fullscreen_preview is None


@pytest.mark.parametrize("scaling", ["actual", "fill"])
def test_fullscreen_drag_stays_inside_image_and_ignores_letterboxing(studio, scaling):
    studio.fullscreen_scale.setCurrentIndex(studio.fullscreen_scale.findData(scaling))
    canvas = show_preview(studio).canvas
    area = canvas.image_rect().intersected(canvas.rect().toRectF())
    start = area.center().toPoint()
    if scaling == "actual":
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        move_mouse(canvas, start, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=start)
        assert canvas.split == 0.5
    for x, expected in (
        (-500, area.left() + area.width() * 0.02),
        (canvas.width() + 500, area.right() - area.width() * 0.02),
    ):
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        end = QPoint(x, start.y())
        move_mouse(canvas, end, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        assert canvas.split == pytest.approx(expected / canvas.width())


@pytest.mark.parametrize(
    "mode, button", [("before", Qt.LeftButton), ("after", Qt.LeftButton), ("split", Qt.RightButton)]
)
def test_fullscreen_drag_only_changes_split_comparison_with_left_button(studio, mode, button):
    studio.canvas.mode = mode
    canvas = show_preview(studio).canvas
    area = canvas.image_rect()
    start = area.center().toPoint()
    end = QPoint(round(area.x() + area.width() * 0.7), start.y())
    QTest.mousePress(canvas, button, pos=start)
    move_mouse(canvas, end, button)
    QTest.mouseRelease(canvas, button, pos=end)
    assert canvas.split == 0.5


def test_double_click_image_enters_and_exits_fullscreen(studio):
    viewer = show_preview(studio)
    QTest.keyClick(viewer.canvas, Qt.Key.Key_Escape)
    QApplication.processEvents()
    # Letterboxing and right-button double clicks are not image activation.
    QTest.mouseDClick(studio.canvas, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert studio.fullscreen_preview is None
    center = studio.canvas.image_rect().center().toPoint()
    QTest.mouseDClick(studio.canvas, Qt.MouseButton.RightButton, pos=center)
    assert studio.fullscreen_preview is None
    QTest.mouseDClick(studio.canvas, Qt.MouseButton.LeftButton, pos=center)
    QApplication.processEvents()
    viewer = studio.fullscreen_preview
    assert viewer is not None and viewer.isFullScreen()
    assert viewer.canvas.hint_visible
    QTest.mouseDClick(viewer.canvas, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert studio.fullscreen_preview is viewer
    QTest.mouseDClick(
        viewer.canvas,
        Qt.MouseButton.LeftButton,
        pos=viewer.canvas.image_rect().center().toPoint(),
    )
    assert studio.fullscreen_preview is None


def test_application_deactivation_exits_without_reopening(studio):
    viewer = show_preview(studio)
    QApplication.sendEvent(viewer, QEvent(QEvent.Type.WindowActivate))
    QApplication.instance().applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert studio.fullscreen_preview is None
    assert not viewer.isVisible()
    QApplication.instance().applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert studio.fullscreen_preview is None


def test_closing_main_window_closes_preview(studio):
    viewer = show_preview(studio)
    studio.close()
    assert studio.fullscreen_preview is None
    assert not viewer.isVisible()
    assert not viewer.canvas.hint_timer.isActive()


def test_single_click_on_hint_is_not_an_exit_button(studio):
    viewer = show_preview(studio)
    QTest.mouseClick(
        viewer.canvas, Qt.MouseButton.LeftButton, pos=viewer.canvas.hint_rect().center()
    )
    assert studio.fullscreen_preview is viewer


def test_hdr_hint_blends_only_its_rectangle_and_does_not_modify_cached_frame(studio):
    canvas = show_preview(studio).canvas
    width, height = (
        round(canvas.width() * canvas.devicePixelRatioF()),
        round(canvas.height() * canvas.devicePixelRatioF()),
    )
    frame = np.full((height, width, 4), [12.5, -0.125, 2.5, 1], np.float16)
    result = canvas.composite_overlay(frame)
    np.testing.assert_array_equal(frame[0, 0], [12.5, -0.125, 2.5, 1])
    left = round(canvas.hint_rect().left() * canvas.devicePixelRatioF())
    np.testing.assert_array_equal(result[:, :left], frame[:, :left])
    x = round(canvas.hint_rect().center().x() * canvas.devicePixelRatioF())
    y = round(canvas.hint_rect().center().y() * canvas.devicePixelRatioF())
    assert not np.array_equal(result[y, x], frame[y, x])
    assert np.all(result[..., 3] == 1)
    assert np.all(frame[..., 0] == 12.5)
    canvas.hint_timer.timeout.emit()
    assert canvas.composite_overlay(frame) is frame


def test_native_surface_forwards_double_click_entry_and_exit(studio):
    viewer = show_preview(studio)
    QTest.keyClick(viewer.canvas, Qt.Key.Key_Escape)
    source_surface = HdrSurface(studio.canvas)
    source_surface.setGeometry(studio.canvas.rect())
    QTest.mouseDClick(
        source_surface,
        Qt.MouseButton.LeftButton,
        pos=studio.canvas.image_rect().center().toPoint(),
    )
    QApplication.processEvents()
    assert studio.fullscreen_preview is not None
    canvas = studio.fullscreen_preview.canvas
    surface = HdrSurface(canvas)
    surface.setGeometry(canvas.rect())
    canvas.hint_timer.timeout.emit()
    move_mouse(surface, QPoint(32, 39))
    assert not canvas.hint_visible
    QTest.mouseDClick(
        surface, Qt.MouseButton.LeftButton, pos=canvas.image_rect().center().toPoint()
    )
    assert studio.fullscreen_preview is None


def test_generated_view_buttons_follow_selected_image_results(studio, tmp_path, wait_until):
    from PIL import Image

    first, second, processed = [
        tmp_path / name for name in ("first.png", "second.png", "after.png")
    ]
    for path in (first, second, processed):
        Image.new("RGB", (160, 90), (128, 128, 128)).save(path)
    assert not any(button.isEnabled() for button in studio.view_buttons.values())
    studio.add_files([str(first), str(second)])
    wait_until(lambda: not studio.loading_preview)
    assert studio.view_buttons["before"].isEnabled()
    assert studio.fullscreen_button.isEnabled()
    assert studio.view_buttons["before"].isChecked()
    assert not studio.view_buttons["after"].isEnabled()
    assert not studio.view_buttons["split"].isEnabled()
    studio.set_view("before")
    studio.view_buttons["after"].click()
    assert studio.canvas.mode == "before"
    studio.job_event(
        {
            "event": "file_done",
            "result": {
                "source": str(first),
                "before": str(first),
                "after": str(processed),
                "hdr_preview": None,
                "output": None,
                "info": {"width": 160, "height": 90, "input_profile": "sRGB"},
                "settings": studio.current_settings().to_dict(),
                "statistics": {"peak_luminance_nits": 650},
            },
        }
    )
    wait_until(lambda: not studio.loading_preview)
    assert all(button.isEnabled() for button in studio.view_buttons.values())
    assert studio.canvas.mode == "split"
    assert studio.view_buttons["split"].isChecked()
    studio.view_buttons["after"].click()
    assert studio.canvas.mode == "after"
    assert studio.view_buttons["after"].isChecked()
    assert not studio.view_buttons["before"].isChecked()
    studio.queue.setCurrentRow(1)
    wait_until(lambda: not studio.loading_preview)
    assert not studio.view_buttons["after"].isEnabled()
    assert not studio.view_buttons["split"].isEnabled()
    assert studio.view_buttons["before"].isEnabled()
    assert studio.view_buttons["before"].isChecked()
    studio.queue.setCurrentRow(0)
    wait_until(lambda: not studio.loading_preview)
    assert studio.view_buttons["after"].isEnabled()
    studio.clear_files()
    assert not any(button.isEnabled() for button in studio.view_buttons.values())
    assert not any(button.isChecked() for button in studio.view_buttons.values())


def test_preview_buttons_show_the_current_mode_and_keep_their_width_on_resize(studio):
    viewer = show_preview(studio)
    QTest.keyClick(viewer, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert studio.view_buttons["split"].isChecked()
    for mode in ("before", "after", "split"):
        studio.view_buttons[mode].click()
        assert studio.canvas.mode == mode
        assert [name for name, button in studio.view_buttons.items() if button.isChecked()] == [
            mode
        ]
    widths = [button.width() for button in studio.view_buttons.values()]
    fullscreen_width = studio.fullscreen_button.width()
    studio.resize(2300, 1000)
    QApplication.processEvents()
    assert [button.width() for button in studio.view_buttons.values()] == widths
    assert studio.fullscreen_button.width() == fullscreen_width
    assert (
        studio.view_buttons["before"].mapTo(studio, QPoint()).x()
        == studio.canvas.mapTo(studio, QPoint()).x()
    )
    positions = [
        studio.view_buttons[mode].mapTo(studio, QPoint()).x()
        for mode in ("before", "after", "split")
    ]
    assert positions[0] < positions[1] < positions[2]
    assert (
        studio.fullscreen_scale.mapTo(studio, QPoint()).x()
        == studio.fullscreen_button.mapTo(studio, QPoint()).x()
    )
    assert studio.fullscreen_scale.width() == studio.fullscreen_button.width()
    assert (
        studio.fullscreen_button.mapTo(studio, QPoint()).x() + studio.fullscreen_button.width()
        == studio.canvas.mapTo(studio, QPoint()).x() + studio.canvas.width()
    )


@pytest.mark.parametrize("mode", ["fit", "fill", "stretch", "actual"])
def test_fullscreen_scaling_matches_between_sdr_pixels_and_native_composition(studio, mode):
    studio.fullscreen_scale.setCurrentIndex(studio.fullscreen_scale.findData(mode))
    studio.canvas.mode = "after"
    canvas = show_preview(studio).canvas
    assert canvas.scale_mode == mode
    canvas.hint_timer.timeout.emit()
    image = canvas.grab().toImage()
    from PySide6.QtGui import QImage

    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    rgba = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.width(), 4)
    sdr_mask = np.all(rgba[..., :3] == [0, 255, 0], axis=2)
    surface = HdrSurface(canvas)
    surface.before_linear = pixmap_to_linear(canvas.before)
    surface.after_linear = np.full((90, 160, 3), [12.5, -0.125, 2.5], np.float16)
    surface.prepared = prepare_frames(
        surface.before_linear,
        surface.after_linear,
        image.width(),
        image.height(),
        canvas.display_info.sdr_white_nits / 80,
        canvas.scale_mode,
        0,
    )
    hdr = surface.compose(image.width(), image.height())
    hdr_mask = np.all(hdr[..., :3] == [12.5, -0.125, 2.5], axis=2)
    np.testing.assert_array_equal(hdr_mask, sdr_mask)
    assert sdr_mask.any()
    if mode in ("stretch", "fill"):
        assert sdr_mask.all()
    elif mode == "actual":
        assert sdr_mask.sum() == 160 * 90
    else:
        assert sdr_mask.sum() > 160 * 90 and not sdr_mask.all()


def test_no_scaling_uses_physical_pixels_at_fractional_display_scaling(studio, monkeypatch):
    source = QPixmap(400, 200)
    source.fill(Qt.GlobalColor.red)
    studio.canvas.set_images(source)
    canvas = FullscreenCanvas(studio.canvas, "actual")
    canvas.resize(800, 600)
    monkeypatch.setattr(canvas, "devicePixelRatioF", lambda: 1.5)
    rect = canvas.image_rect()
    assert rect.width() * 1.5 == 400
    assert rect.height() * 1.5 == 200
    canvas.stop()
