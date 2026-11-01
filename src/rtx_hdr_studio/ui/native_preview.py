"""Native scRGB child surface used inside the Qt comparison canvas."""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

from ..color import srgb_to_linear
from ..graphics.directx import Presenter
from .preview_tasks import LatestTask, image_to_linear, load_hdr, prepare_frames


def pixmap_to_linear(pixmap):
    return image_to_linear(pixmap.toImage())


class HdrSurface(QWidget):
    failed = Signal(str)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.renderer = None
        self.prepared = None
        self.before_linear = None
        self.after_linear = None
        self.data = None
        self.enabled = False
        self._data_key = None
        self._frame_key = None
        self.data_task = LatestTask(self)
        self.frame_task = LatestTask(self)
        self.data_task.ready.connect(self._data_ready)
        self.frame_task.ready.connect(self._frame_ready)
        self.data_task.failed.connect(self._async_failed)
        self.frame_task.failed.connect(self._async_failed)
        self.canvas.preview_device.ready.connect(self._activate)
        self.canvas.preview_device.failed.connect(self._async_failed)
        self._failed = False
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setCursor(canvas.cursor())
        self.setMouseTracking(canvas.hasMouseTracking())
        self.setAccessibleName(canvas.accessibleName())

    def paintEngine(self):
        return None

    def set_images(self):
        self.enabled = True
        self._failed = False
        key = (self.canvas.before.cacheKey(), str(self.canvas.hdr_path))
        if self.canvas.preview_device.error:
            self._async_failed(self.canvas.preview_device.error)
            return
        self.canvas.preview_device.ensure()
        if key != self._data_key:
            self._data_key = key
            self.data_task.cancel()
            self.frame_task.cancel()
            self.data = None
            self.prepared = None
            self._frame_key = None
            if self.canvas.hdr_data is not None:
                self._data_ready(self.canvas.hdr_data)
            else:
                self.data_task.submit(load_hdr, self.canvas.before.toImage(), self.canvas.hdr_path)
        else:
            self.request_frame()

    def _data_ready(self, data):
        self.data = data
        self.before_linear, self.after_linear = data
        self.canvas.hdr_data = data
        self.request_frame()

    def pixel_size(self):
        rect = W.RECT()
        C.windll.user32.GetClientRect(W.HWND(int(self.winId())), C.byref(rect))
        return rect.right, rect.bottom

    def request_frame(self):
        if not self.enabled or self.data is None or not self.canvas.isVisible():
            return
        width, height = self.pixel_size()
        if width < 1 or height < 1:
            return
        white = self.canvas.display_info.sdr_white_nits / 80
        margin = round(self.canvas.image_margin * self.devicePixelRatioF())
        key = (self._data_key, width, height, white, self.canvas.scale_mode, margin)
        if self._frame_key == key:
            self._activate()
            return
        self._frame_key = key
        self.prepared = None
        self.frame_task.submit(
            prepare_frames, *self.data, width, height, white, self.canvas.scale_mode, margin
        )

    def _frame_ready(self, prepared):
        self.prepared = prepared
        self._activate()

    def _activate(self):
        if (
            not self.enabled
            or self.prepared is None
            or self.canvas.preview_device.resources is None
        ):
            return
        if not self.canvas.isVisible():
            return
        self.canvas.hdr_loading = False
        self.canvas.hdr_active = True
        self.show()
        self.update()
        self.canvas.display_changed.emit()

    def _async_failed(self, message):
        if self.enabled:
            self._failed = True
            self.failed.emit(message)

    def suspend(self):
        self.enabled = False
        self.data_task.cancel()
        self.frame_task.cancel()
        if self.data is None:
            self._data_key = None
        self._frame_key = None
        self.hide()

    def shutdown(self):
        self.enabled = False
        self.data_task.close()
        self.frame_task.close()
        self.hide()
        self.close_renderer()

    def invalidate(self):
        self.request_frame()

    def close_renderer(self):
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        self.prepared = None

    def compose(self, width, height):
        if self.prepared is None or self.prepared[0].shape[:2] != (height, width):
            self.request_frame()
            return None
        before, after, y, ih = self.prepared
        if self.canvas.mode == "after":
            return after
        if self.canvas.mode == "before":
            return before
        boundary = min(width - 1, max(0, round(width * self.canvas.split)))
        frame = before.copy()
        frame[:, boundary:] = after[:, boundary:]
        color = (
            srgb_to_linear(np.array([152, 223, 164]) / 255)
            * self.canvas.display_info.sdr_white_nits
            / 80
        )
        frame[y : y + ih, boundary : boundary + max(1, round(self.devicePixelRatioF())), :3] = color
        return frame

    def paintEvent(self, event):
        if self._failed or self.after_linear is None:
            return
        try:
            rect = W.RECT()
            C.windll.user32.GetClientRect(W.HWND(int(self.winId())), C.byref(rect))
            width, height = rect.right, rect.bottom
            if width < 1 or height < 1:
                return
            frame = self.compose(width, height)
            if frame is None:
                return
            if self.renderer is None:
                resources = self.canvas.preview_device.resources
                if resources is None:
                    return
                self.renderer = Presenter(int(self.winId()), width, height, resources)
            else:
                self.renderer.resize(width, height)
            self.renderer.upload(self.canvas.composite_overlay(frame))
            self.renderer.present()
        except Exception as error:
            self._failed = True
            # Leave paintEvent before hiding/releasing the native child.
            message = str(error)
            QTimer.singleShot(0, lambda: self.failed.emit(message))

    def mousePressEvent(self, event):
        self.canvas.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.canvas.mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.canvas.mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self.canvas.mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.canvas.wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.request_frame()
