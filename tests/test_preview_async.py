import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rtx_hdr_studio.graphics.display import DisplayInfo
from rtx_hdr_studio.ui import window as window_module
from rtx_hdr_studio.ui.preview_tasks import (
    LatestTask,
    PreviewDevice,
    image_to_linear,
    prepare_frames,
)
from rtx_hdr_studio.ui.window import StudioWindow


class ControlledJob(QObject):
    event = Signal(dict)
    finished = Signal()

    def __init__(self, request, parent):
        super().__init__(parent)
        self.request = request
        self.log_path = Path(request["job_dir"]) / "worker.log"
        self.outcome = {"cancelled": True}

    def start(self):
        pass

    def cancel(self):
        pass

    def wait(self, timeout):
        return True


@pytest.fixture
def images_window(tmp_path, monkeypatch, wait_until):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(window_module, "JobRunner", ControlledJob)
    window = StudioWindow()
    paths = [str(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    for path, color in zip(paths, ("red", "blue", "green"), strict=True):
        Image.new("RGB", (160, 90), color).save(path)
    for path in (paths[0], paths[2]):
        window.results[path] = {
            "source": path,
            "before": path,
            "after": path,
            "hdr_preview": None,
            "output": None,
            "info": {"width": 160, "height": 90, "input_profile": "sRGB"},
            "settings": window.current_settings().to_dict(),
            "statistics": {"peak_luminance_nits": 650},
        }
    window.show()
    window.add_files(paths)
    wait_until(lambda: not window.loading_preview)
    yield window, paths
    window.close()
    app.processEvents()


def test_processing_locks_only_its_image_and_closes_only_its_fullscreen(images_window, wait_until):
    window, (first, second, third) = images_window
    window.set_view("after")
    window.show_fullscreen_preview()
    assert window.fullscreen_preview.source == first
    window.start_job("preview", [first])
    assert window.fullscreen_preview is None
    assert window.canvas.mode == "before" and window.view_buttons["before"].isChecked()
    assert window.canvas.hdr_suspended
    assert not any(button.isEnabled() for button in window.view_buttons.values())
    assert not window.fullscreen_button.isEnabled()
    window.set_view("after")
    window.show_fullscreen_preview()
    QTest.mouseDClick(
        window.canvas, Qt.LeftButton, pos=window.canvas.image_rect().center().toPoint()
    )
    assert window.fullscreen_preview is None and window.canvas.mode == "before"
    assert window.queue.isEnabled()

    # An unprocessed source is still viewable and can enter fullscreen.
    window.queue.setCurrentRow(1)
    wait_until(lambda: not window.loading_preview)
    assert window.view_buttons["before"].isEnabled()
    assert not window.view_buttons["after"].isEnabled()
    assert window.fullscreen_button.isEnabled()
    window.show_fullscreen_preview()
    second_viewer = window.fullscreen_preview
    window.job.event.emit(
        {
            "event": "progress",
            "source": first,
            "index": 0,
            "total": 1,
            "filename": "a.png",
            "message": "Building preview",
        }
    )
    assert window.fullscreen_preview is second_viewer
    second_viewer.close()

    # A previously processed source keeps all view modes while another source runs.
    window.queue.setCurrentRow(2)
    wait_until(lambda: not window.loading_preview)
    assert all(button.isEnabled() for button in window.view_buttons.values())
    window.set_view("after")
    window.show_fullscreen_preview()
    third_viewer = window.fullscreen_preview
    window.job.event.emit({"event": "file_done", "result": window.results[first]})
    assert window.processing_source is None
    assert window.fullscreen_preview is third_viewer
    assert window.canvas.mode == "after"
    third_viewer.close()
    window.queue.setCurrentRow(0)
    wait_until(lambda: not window.loading_preview)
    assert all(button.isEnabled() for button in window.view_buttons.values())
    assert window.canvas.mode == "split"
    assert window.view_buttons["split"].isChecked()


def test_focus_estimate_and_duplicate_job_guard(images_window, wait_until):
    from rtx_hdr_studio.resources import GiB, estimate_gpu_bytes

    window, (first, second, _) = images_window
    Image.new("RGB", (416, 240), "blue").save(second)
    window.gpu_loader.cancel()
    window.memory_estimate.set_gpu({"device": 0, "name": "Test GPU", "total": 8 * GiB})
    window.start_job("preview", [first])
    runner = window.job
    window.start_job("export", [second])
    assert window.job is runner and runner.request["files"] == [first]
    window.queue.setCurrentRow(1)
    wait_until(lambda: window.memory_estimate.info and window.memory_estimate.info["width"] == 416)
    assert window.processing_source == first
    assert window.memory_estimate.bar.estimate == estimate_gpu_bytes(416, 240)
    assert window.memory_estimate.bar.capacity == 8 * GiB


def test_completed_preview_switches_to_split_after_loading(images_window, wait_until):
    window, (first, _, _) = images_window
    window.start_job("preview", [first])
    assert window.canvas.mode == "before"
    window.job.event.emit({"event": "file_done", "result": window.results[first]})
    assert window.loading_preview
    wait_until(lambda: not window.loading_preview)
    assert window.canvas.mode == "split"
    assert window.view_buttons["split"].isChecked()
    window.set_view("after")
    window.select_file(0)
    wait_until(lambda: not window.loading_preview)
    assert window.canvas.mode == "after"  # Apply once, retaining later user choices.


def test_batch_advances_lock_and_cancellation_restores_controls(images_window, wait_until):
    window, (first, second, third) = images_window
    window.start_job("export", [first, second, third])
    assert window.processing_source == first
    window.queue.setCurrentRow(2)
    wait_until(lambda: not window.loading_preview)
    window.set_view("after")
    window.show_fullscreen_preview()
    window.job.event.emit(
        {
            "event": "progress",
            "index": 2,
            "total": 3,
            "filename": "c.png",
            "message": "Reading image",
        }
    )
    assert window.processing_source == third
    assert window.fullscreen_preview is None
    assert window.canvas.mode == "before"
    assert not window.fullscreen_button.isEnabled()
    window.job.finished.emit()
    assert window.job is None and window.processing_source is None
    assert all(button.isEnabled() for button in window.view_buttons.values())
    assert not window.canvas.hdr_suspended


def test_file_failure_releases_its_viewing_restriction(images_window):
    window, paths = images_window
    window.start_job("preview", [paths[0]])
    window.job.event.emit({"event": "file_error", "source": paths[0], "error": "Synthetic failure"})
    assert window.processing_source is None
    assert window.canvas.mode == "before"
    assert all(button.isEnabled() for button in window.view_buttons.values())
    assert window.fullscreen_button.isEnabled()


def test_status_merges_peak_and_outdated_highlight_then_clears_on_image_change(
    images_window, wait_until
):
    from PySide6.QtGui import QPalette

    window, (first, _, _) = images_window
    window.canvas.display_info = DisplayInfo(hdr_active=True, bits=10)
    window.canvas.hdr_active = True
    window.update_notice()
    assert window.display_status.text() == "HDR Ready | Peak: 650nit"
    original_color = window.display_status.palette().color(QPalette.WindowText)
    window.parameters["contrast"].set_value(105)
    assert window.display_status.text() == "HDR Ready | Peak: 650nit (Outdated)"
    assert window.display_status.palette().color(QPalette.WindowText).name() == "#ff6b6b"
    window.parameters["contrast"].set_value(100)
    assert window.display_status.text() == "HDR Ready | Peak: 650nit"
    assert window.display_status.palette().color(QPalette.WindowText) == original_color
    window.parameters["contrast"].set_value(105)
    window.results[first]["settings"] = window.current_settings().to_dict()
    window.results[first]["statistics"]["peak_luminance_nits"] = 637
    window.update_notice()
    assert window.display_status.text() == "HDR Ready | Peak: 637nit"
    assert window.display_status.palette().color(QPalette.WindowText) == original_color
    window.canvas.hdr_active = False
    window.canvas.prefer_hdr = False
    window.update_notice()
    assert window.display_status.text() == "SDR Ready | Peak: 637nit"
    window.queue.setCurrentRow(1)
    wait_until(lambda: not window.loading_preview)
    assert window.display_status.text() == "SDR Ready"
    assert window.display_status.styleSheet() == ""


def test_preview_loader_drops_old_image_without_blocking_gui(
    images_window, monkeypatch, wait_until
):
    window, (first, second, third) = images_window
    started, release = threading.Event(), threading.Event()
    original = window_module.load_preview
    main_thread = threading.get_ident()
    workers = []

    def slow_load(source, result, background):
        workers.append(threading.get_ident())
        if source == first:
            started.set()
            assert release.wait(5)
        return original(source, result, background)

    monkeypatch.setattr(window_module, "load_preview", slow_load)
    beats = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(True))
    timer.start()
    try:
        window.select_file(0)
        wait_until(started.is_set)
        window.queue.setCurrentRow(1)
        window.queue.setCurrentRow(2)
        wait_until(lambda: len(beats) >= 3, 1000)
        release.set()
        wait_until(lambda: not window.loading_preview)
        assert window._displayed_source == third
        assert window.canvas.before.toImage().pixelColor(0, 0).name() == "#008000"
        assert workers and all(thread != main_thread for thread in workers)
    finally:
        release.set()
        timer.stop()


def test_latest_task_coalesces_requests_and_suppresses_late_results(wait_until):
    app = QApplication.instance() or QApplication([])
    task = LatestTask()
    started, release = threading.Event(), threading.Event()
    called, delivered = [], []
    task.ready.connect(delivered.append)

    def work(value):
        called.append(value)
        if value == 1:
            started.set()
            assert release.wait(5)
        return value

    try:
        task.submit(work, 1)
        wait_until(started.is_set)
        task.submit(work, 2)
        task.submit(work, 3)
        release.set()
        wait_until(lambda: delivered == [3])
        assert called == [1, 3]
        task.close()
        task.submit(work, 4)
        app.processEvents()
        assert called == [1, 3]
    finally:
        release.set()
        task.close()


def test_device_initializes_off_thread_and_is_reused(monkeypatch, wait_until):
    from rtx_hdr_studio.graphics import directx

    app = QApplication.instance() or QApplication([])
    main = threading.get_ident()
    calls = []

    class Device:
        def __init__(self):
            calls.append(("create", threading.get_ident()))

        def close(self):
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(directx, "DeviceResources", Device)
    service = PreviewDevice()
    service.ensure()
    service.ensure()
    wait_until(lambda: service.resources is not None)
    service.ensure()
    assert len(calls) == 1 and calls[0][1] != main
    service.close()
    app.processEvents()
    assert calls[-1] == ("close", main)


def test_background_frame_preparation_preserves_hdr_range():
    before = QImage(17, 13, QImage.Format.Format_RGB32)
    before.fill(Qt.GlobalColor.red)
    linear = image_to_linear(before)
    hdr = np.full((13, 17, 3), [12.5, -0.125, 2.5], np.float16)
    original, processed, y, ih = prepare_frames(linear, hdr, 200, 120, 2.5, "actual", 0)
    np.testing.assert_array_equal(processed[60, 100, :3], [12.5, -0.125, 2.5])
    np.testing.assert_array_equal(original[60, 100, :3], [2.5, 0, 0])
    assert processed.dtype == np.float16 and ih == 13


@pytest.mark.parametrize("shape", [(20, 80), (80, 20), (1, 10000)])
def test_fill_crops_center_and_preserves_hdr_range(shape):
    height, width = shape
    hdr = np.zeros((height, width, 3), np.float16)
    hdr[height // 4 : max(1, height * 3 // 4), width // 4 : width * 3 // 4] = [12.5, -0.125, 2.5]
    if height == 1:
        hdr[0, width // 4 : width * 3 // 4] = [12.5, -0.125, 2.5]
    _, processed, y, ih = prepare_frames(hdr, hdr, 40, 40, 1, "fill", 0)
    assert processed.shape == (40, 40, 4) and (y, ih) == (0, 40)
    np.testing.assert_array_equal(processed[20, 20, :3], [12.5, -0.125, 2.5])
    assert (processed[..., 3] == 1).all()
