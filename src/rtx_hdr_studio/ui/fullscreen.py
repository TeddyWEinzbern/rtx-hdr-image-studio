"""Full-screen image snapshot with an adjustable divider and a brief exit hint."""

import numpy as np
from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ..color import srgb_to_linear
from .canvas import CompareCanvas


class FullscreenCanvas(CompareCanvas):
    exit_requested = Signal()

    def __init__(self, source, scale_mode="fit"):
        super().__init__(device=source.preview_device)
        self.mode = source.mode
        self.split = source.split
        self.show_split_handle = self.mode == "split" and not source.after.isNull()
        self._dragging_split = False
        self.scale_mode = scale_mode
        self.image_margin = 0
        self.prefer_hdr = source.prefer_hdr
        self.hint_visible = True
        self._hint_started = False
        self._hint_image = None
        self._hint_linear = None
        self.setCursor(
            Qt.CursorShape.SplitHCursor if self.show_split_handle else Qt.CursorShape.ArrowCursor
        )
        self.setAccessibleName(
            "Full-screen image preview. Drag to move the comparison divider. "
            "Double-click the image or press Escape to exit."
        )
        self.hint_timer = QTimer(self)
        self.hint_timer.setSingleShot(True)
        self.hint_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.hint_timer.setInterval(3000)
        self.hint_timer.timeout.connect(self._hide_hint)
        self.set_images(
            QPixmap(source.before), QPixmap(source.after), source.hdr_path, source.hdr_data
        )

    def start_hint(self):
        if not self._hint_started:
            self._hint_started = True
            self.hint_timer.start()

    def _hide_hint(self):
        self.hint_visible = False
        self.update()

    def hint_rect(self):
        rect = QRect(0, 0, min(460, self.width() - 40), 72)
        rect.moveCenter(self.rect().center())
        return rect

    def _prepare_hint(self):
        ratio = self.devicePixelRatioF()
        size = self.hint_rect().size()
        if self._hint_image is not None:
            if (
                self._hint_image.devicePixelRatio() == ratio
                and self._hint_image.deviceIndependentSize().toSize() == size
            ):
                return
        image = QImage(
            round(size.width() * ratio), round(size.height() * ratio), QImage.Format.Format_RGBA8888
        )
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(28, 34, 43, 235))
        painter.drawRoundedRect(0, 0, size.width(), size.height(), 10, 10)
        painter.setPen(QColor("#e6eaf1"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(
            QRect(12, 0, size.width() - 24, size.height()),
            Qt.AlignmentFlag.AlignCenter,
            "Double-click the image\nor press Esc to exit fullscreen",
        )
        painter.end()
        self._hint_image = image
        pixels = (
            np.frombuffer(image.constBits(), np.uint8)
            .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 4]
            .reshape(image.height(), image.width(), 4)
        )
        self._hint_linear = (srgb_to_linear(pixels[..., :3] / 255), pixels[..., 3:4] / 255)

    def paint_overlay(self, painter):
        if not self.hint_visible:
            return
        self._prepare_hint()
        painter.drawImage(self.hint_rect().topLeft(), self._hint_image)

    def composite_overlay(self, frame):
        if not self.hint_visible:
            return frame
        self._prepare_hint()
        rgb, alpha = self._hint_linear
        ratio = self.devicePixelRatioF()
        x, y = round(self.hint_rect().x() * ratio), round(self.hint_rect().y() * ratio)
        h, w = rgb.shape[:2]
        # Restrict blending to the hint, preserving the rest of the HDR frame exactly.
        w, h = min(w, frame.shape[1] - x), min(h, frame.shape[0] - y)
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            return frame
        result = frame.copy()
        patch = result[y : y + h, x : x + w, :3]
        opacity = alpha[:h, :w]
        white = self.display_info.sdr_white_nits / 80
        patch[...] = patch.astype(np.float32) * (1 - opacity) + rgb[:h, :w] * white * opacity
        return result

    def mouseMoveEvent(self, event):
        if self._dragging_split:
            if event.buttons() & Qt.MouseButton.LeftButton:
                area = self.image_rect().intersected(self.rect().toRectF())
                margin = area.width() * 0.02
                x = min(area.right() - margin, max(area.left() + margin, event.position().x()))
                self.split = x / max(self.width(), 1)
                self.update()
            else:
                self._dragging_split = False
        event.accept()

    def mousePressEvent(self, event):
        self._dragging_split = (
            event.button() == Qt.MouseButton.LeftButton
            and self.mode == "split"
            and not self.after.isNull()
            and self.image_rect().contains(event.position())
        )
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_split = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self._dragging_split = False
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(
            event.position()
        ):
            event.accept()
            self.exit_requested.emit()

    def wheelEvent(self, event):
        event.accept()

    def stop(self):
        self._dragging_split = False
        self.hint_timer.stop()
        self.shutdown()


class FullscreenPreview(QWidget):
    closed = Signal()

    def __init__(self, source, owner, scale_mode="fit"):
        super().__init__(owner, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Full-screen preview")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._armed = False
        self._closed = False
        self.canvas = FullscreenCanvas(source, scale_mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.canvas.exit_requested.connect(self.close)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self.escape.setAutoRepeat(False)
        QApplication.instance().applicationStateChanged.connect(self._application_state_changed)
        self.setScreen(source.screen())

    def showEvent(self, event):
        super().showEvent(event)
        self.canvas.start_hint()

    def event(self, event):
        if event.type() == QEvent.Type.WindowActivate:
            self._armed = True
        elif event.type() == QEvent.Type.WindowDeactivate and self._armed:
            # Let native-child focus changes settle before deciding whether focus was lost.
            QTimer.singleShot(0, self._close_if_inactive)
        return super().event(event)

    def _close_if_inactive(self):
        if not self._closed and not self.isActiveWindow():
            self.close()

    def _application_state_changed(self, state):
        if self._armed and state != Qt.ApplicationState.ApplicationActive:
            self.close()

    def closeEvent(self, event):
        if not self._closed:
            self._closed = True
            self.canvas.stop()
            QApplication.instance().applicationStateChanged.disconnect(
                self._application_state_changed
            )
            self.closed.emit()
        event.accept()
