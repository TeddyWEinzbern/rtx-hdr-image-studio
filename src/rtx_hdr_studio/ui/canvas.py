"""Comparison widget with automatic native HDR/SDR switching."""

import logging

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ..graphics.display import DisplayInfo, query_display


class CompareCanvas(QWidget):
    display_changed = Signal()

    def __init__(self):
        super().__init__()
        self.before = QPixmap()
        self.after = QPixmap()
        self.split = 0.5
        self.mode = "split"
        self.prefer_hdr = True
        self.hdr_path = None
        self.hdr_surface = None
        self.hdr_active = False
        self.hdr_error = ""
        self.display_info = DisplayInfo()
        self.setMinimumSize(280, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Image comparison. Drag to move the divider.")
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(1500)
        self.display_timer.timeout.connect(self.refresh_display)
        self.display_timer.start()

    def set_images(self, before: QPixmap, after: QPixmap | None = None, hdr_path=None):
        self._disable_hdr()
        self.before = before
        self.after = after or QPixmap()
        self.hdr_path = hdr_path
        self.hdr_error = ""
        self.refresh_display()
        self.update()

    def set_hdr_preference(self, enabled):
        self.prefer_hdr = enabled
        self.hdr_error = ""
        self.refresh_display()

    def refresh_display(self):
        if not self.isVisible():
            return
        # The offscreen renderer has no native Windows display surface.
        if QApplication.platformName() == "offscreen":
            current = DisplayInfo(error="Offscreen rendering uses SDR preview")
        else:
            current = query_display(int(self.winId()))
        changed = current != self.display_info
        if changed:
            if (current.name, current.color_mode) != (
                self.display_info.name,
                self.display_info.color_mode,
            ):
                self._disable_hdr()
                self.hdr_error = ""
            self.display_info = current
            if self.hdr_surface:
                self.hdr_surface.invalidate()
        wanted = (
            self.prefer_hdr
            and current.hdr_active
            and self.hdr_path
            and not self.before.isNull()
            and not self.hdr_error
        )
        if wanted and not self.hdr_active:
            try:
                if self.hdr_surface is None:
                    from .native_preview import HdrSurface

                    self.hdr_surface = HdrSurface(self)
                    self.hdr_surface.failed.connect(self._hdr_failed)
                self.hdr_surface.setGeometry(self.rect())
                self.hdr_surface.set_images()
                self.hdr_surface.show()
                self.hdr_active = True
                changed = True
            except Exception as error:
                self._hdr_failed(str(error))
        elif not wanted and self.hdr_active:
            self._disable_hdr()
            changed = True
        if changed:
            self.display_changed.emit()

    def _disable_hdr(self):
        self.hdr_active = False
        if self.hdr_surface:
            self.hdr_surface.hide()

    def _hdr_failed(self, message):
        self.hdr_error = message
        self._disable_hdr()
        logging.getLogger(__name__).warning("HDR preview failed: %s", message)
        self.update()
        self.display_changed.emit()

    def update(self, *args):
        super().update(*args)
        if self.hdr_active and self.hdr_surface:
            self.hdr_surface.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.hdr_surface:
            self.hdr_surface.setGeometry(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh_display)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.split = min(0.98, max(0.02, event.position().x() / max(self.width(), 1)))
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10151b"))
        if self.before.isNull():
            painter.setPen(QColor("#d6dde7"))
            painter.setFont(QFont("Segoe UI", 13))
            painter.drawText(
                self.rect().adjusted(20, -30, -20, 0),
                Qt.AlignmentFlag.AlignCenter,
                "Drop images here",
            )
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#7e8b9e"))
            painter.drawText(
                self.rect().adjusted(20, 28, -20, 0),
                Qt.AlignmentFlag.AlignCenter,
                "Or choose Add images - PNG / JPEG / WebP / BMP / TIFF",
            )
            return
        area = self.rect().adjusted(12, 12, -12, -12)
        size = self.before.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        image_rect = QRectF(
            area.center().x() - size.width() / 2,
            area.center().y() - size.height() / 2,
            size.width(),
            size.height(),
        )
        if self.mode == "after" and not self.after.isNull():
            painter.drawPixmap(image_rect, self.after, QRectF(self.after.rect()))
        else:
            painter.drawPixmap(image_rect, self.before, QRectF(self.before.rect()))
            if self.mode == "split" and not self.after.isNull():
                boundary = self.width() * self.split
                painter.save()
                painter.setClipRect(QRectF(boundary, 0, self.width() - boundary, self.height()))
                painter.drawPixmap(image_rect, self.after, QRectF(self.after.rect()))
                painter.restore()
                painter.setPen(QPen(QColor("#d1ebd7"), 1))
                painter.drawLine(
                    int(boundary), int(image_rect.top()), int(boundary), int(image_rect.bottom())
                )
                painter.setBrush(QColor("#98dfa4"))
                painter.drawEllipse(int(boundary) - 12, int(image_rect.center().y()) - 12, 24, 24)
                painter.setPen(QColor("#15291a"))
                painter.drawText(
                    QRectF(boundary - 12, image_rect.center().y() - 13, 24, 24),
                    Qt.AlignmentFlag.AlignCenter,
                    "↔",
                )
