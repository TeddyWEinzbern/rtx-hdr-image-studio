"""Native scRGB child surface used inside the Qt comparison canvas."""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

from ..graphics.directx import Presenter
from .composition import composition_plan, divider_color, present_plan, render_region
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
        self.canvas.preview_device.lost.connect(self._device_lost)
        self._failed = False
        self._lost_pending = False
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
        self._lost_pending = False
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

    def release_renderer(self):
        """Release the swap chain and source textures; keep the prepared frames."""
        if self.renderer:
            self.renderer.close()
            self.renderer = None

    def close_renderer(self):
        self.release_renderer()
        self.prepared = None

    def _device_lost(self):
        """The shared device is being rebuilt: drop every object created on it."""
        self.release_renderer()
        self._lost_pending = False
        if self.enabled and self.canvas.hdr_active:
            self.hide()
            self.canvas.hdr_active = False
            self.canvas.hdr_loading = True
            self.canvas.update()
            self.canvas.display_changed.emit()

    def _report_device_lost(self, message):
        self.release_renderer()
        self._lost_pending = False
        self.canvas.preview_device.report_lost(message)

    def _plan(self, width):
        _, _, top, image_height = self.prepared
        return composition_plan(
            self.canvas.mode,
            width,
            self.canvas.split,
            top,
            image_height,
            max(1, round(self.devicePixelRatioF())),
        )

    def _divider_color(self):
        return divider_color(self.canvas.display_info.sdr_white_nits)

    def compose(self, width, height):
        """CPU reference of exactly what paintEvent asks the GPU to present."""
        if self.prepared is None or self.prepared[0].shape[:2] != (height, width):
            self.request_frame()
            return None
        copies, divider = self._plan(width)
        return render_region(
            self.prepared[:2], copies, divider, self._divider_color(), 0, 0, width, height
        )

    def paintEvent(self, event):
        if self._failed or self._lost_pending or self.after_linear is None:
            return
        try:
            rect = W.RECT()
            C.windll.user32.GetClientRect(W.HWND(int(self.winId())), C.byref(rect))
            width, height = rect.right, rect.bottom
            if width < 1 or height < 1:
                return
            if self.prepared is None or self.prepared[0].shape[:2] != (height, width):
                self.request_frame()
                return
            if self.renderer is None:
                resources = self.canvas.preview_device.resources
                if resources is None:
                    return
                self.renderer = Presenter(int(self.winId()), width, height, resources)
            else:
                self.renderer.resize(width, height)
            # Full frames are uploaded once per prepared frame; a repaint (for example
            # while dragging the divider) is GPU copies plus a few small patches.
            before, after, _, _ = self.prepared
            self.renderer.set_sources(self.prepared, before, after)
            copies, divider = self._plan(width)
            color = self._divider_color()
            present_plan(self.renderer, width, copies, divider, color)
            if overlay := self.canvas.overlay_rect(width, height):
                x, y, w, h = overlay
                patch = render_region((before, after), copies, divider, color, x, y, w, h)
                self.canvas.blend_overlay(patch)
                self.renderer.upload_region(x, y, patch)
            self.renderer.present()
        except Exception as error:
            message = str(error)
            if getattr(error, "device_lost", False):
                # Driver reset or device removal: rebuild instead of falling back to
                # SDR for the rest of the session. Leave paintEvent first.
                self._lost_pending = True
                QTimer.singleShot(0, lambda: self._report_device_lost(message))
                return
            self._failed = True
            # Leave paintEvent before hiding/releasing the native child.
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
