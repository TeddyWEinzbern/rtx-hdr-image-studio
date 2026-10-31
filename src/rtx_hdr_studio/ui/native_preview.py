"""Native scRGB child surface used inside the Qt comparison canvas."""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from ..color import srgb_to_linear
from ..graphics.directx import Presenter
from ..image_io import resize_linear


def pixmap_to_linear(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    data = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    rgb = data[:, : image.width() * 4].reshape(image.height(), image.width(), 4)[..., :3]
    return srgb_to_linear(rgb / 255)


class HdrSurface(QWidget):
    failed = Signal(str)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.renderer = None
        self.prepared = None
        self.before_linear = None
        self.after_linear = None
        self._failed = False
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setAccessibleName("Native HDR comparison. Drag to move the divider.")

    def paintEngine(self):
        return None

    def set_images(self):
        self.before_linear = pixmap_to_linear(self.canvas.before)
        data = np.load(self.canvas.hdr_path, allow_pickle=False)
        if (
            data.ndim != 3
            or data.shape[2] != 3
            or data.dtype != np.float16
            or not np.isfinite(data).all()
        ):
            raise ValueError("Invalid HDR preview cache. Generate the preview again.")
        self.after_linear = data
        self.prepared = None
        self._failed = False

    def invalidate(self):
        self.prepared = None
        self.update()

    def close_renderer(self):
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        self.prepared = None

    def _prepare(self, width, height):
        white = self.canvas.display_info.sdr_white_nits / 80
        frame = np.empty((height, width, 4), dtype=np.float16)
        frame[..., :3] = srgb_to_linear(np.array([16, 21, 27]) / 255) * white
        frame[..., 3] = 1
        h, w = self.after_linear.shape[:2]
        margin = round(12 * self.devicePixelRatioF())
        scale = min(max(1, width - margin * 2) / w, max(1, height - margin * 2) / h)
        iw, ih = max(1, min(width, round(w * scale))), max(1, min(height, round(h * scale)))
        x, y = (width - iw) // 2, (height - ih) // 2
        before = frame.copy()
        before[y : y + ih, x : x + iw, :3] = resize_linear(self.before_linear, iw, ih) * white
        after = frame.copy()
        after[y : y + ih, x : x + iw, :3] = resize_linear(self.after_linear, iw, ih)
        self.prepared = (before, after, y, ih)

    def compose(self, width, height):
        if self.prepared is None or self.prepared[0].shape[:2] != (height, width):
            self._prepare(width, height)
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
            if self.renderer is None:
                self.renderer = Presenter(int(self.winId()), width, height)
            else:
                self.renderer.resize(width, height)
            self.renderer.upload(self.compose(width, height))
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

    def hideEvent(self, event):
        self.close_renderer()
        super().hideEvent(event)
