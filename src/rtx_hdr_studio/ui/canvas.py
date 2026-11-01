"""Comparison widget with automatic native HDR/SDR switching."""

import logging

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ..graphics.display import DisplayInfo, query_display
from .geometry import image_placement
from .preview_tasks import LatestTask, PreviewDevice, prepare_sdr_frames


class CompareCanvas(QWidget):
    display_changed = Signal()
    fullscreen_requested = Signal()

    def __init__(self, device=None):
        super().__init__()
        self._owns_device = device is None
        self.preview_device = device if device is not None else PreviewDevice(self)
        self.before = QPixmap()
        self.after = QPixmap()
        self.sdr_task = LatestTask(self)
        self.sdr_task.ready.connect(self._sdr_ready)
        self.sdr_task.failed.connect(self._sdr_failed)
        self._sdr_key = None
        self._sdr_prepared = None
        self._sdr_sources = (None, None)
        self.split = 0.5
        self.mode = "split"
        self.show_split_handle = True
        self.scale_mode = "fit"
        self.image_margin = 12
        self.prefer_hdr = True
        self.hdr_path = None
        self.hdr_surface = None
        self.hdr_active = False
        self.hdr_loading = False
        self.hdr_suspended = False
        self.hdr_data = None
        self.hdr_error = ""
        self.display_info = DisplayInfo()
        self.setMinimumSize(280, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(
            "Image comparison. Drag to move the divider. Double-click the image for fullscreen."
        )
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(1500)
        self.display_timer.timeout.connect(self.refresh_display)
        self.display_timer.start()

    def set_images(
        self, before: QPixmap, after: QPixmap | None = None, hdr_path=None, hdr_data=None
    ):
        self._disable_hdr()
        self.before = before
        self.after = after or QPixmap()
        self.sdr_task.cancel()
        self._sdr_key = self._sdr_prepared = None
        self._sdr_sources = (self.before.toImage(), self.after.toImage())
        self.hdr_path = hdr_path
        self.hdr_data = hdr_data
        self.hdr_error = ""
        self.refresh_display()
        self.update()

    def set_hdr_preference(self, enabled):
        self.prefer_hdr = enabled
        self.hdr_error = ""
        if enabled:
            self.preview_device.retry()
        self.refresh_display()

    def set_hdr_suspended(self, suspended):
        self.hdr_suspended = suspended
        self.refresh_display()

    def shutdown(self):
        self.sdr_task.close()
        self.display_timer.stop()
        self.hdr_active = False
        self.hdr_loading = False
        if self.hdr_surface:
            self.hdr_surface.shutdown()
        if self._owns_device:
            self.preview_device.close()

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
            and not self.hdr_suspended
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
                if not self.hdr_loading and not self.hdr_active and not self.hdr_error:
                    self.hdr_loading = True
                    changed = True
            except Exception as error:
                self._hdr_failed(str(error))
        elif not wanted and (self.hdr_active or self.hdr_loading):
            self._disable_hdr()
            changed = True
        if changed:
            self.display_changed.emit()

    def _disable_hdr(self):
        self.hdr_active = False
        self.hdr_loading = False
        if self.hdr_surface:
            self.hdr_surface.suspend()

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

    def _request_sdr_frame(self):
        if self.before.isNull() or self.hdr_active:
            return
        ratio = self.devicePixelRatioF()
        width, height = round(self.width() * ratio), round(self.height() * ratio)
        margin = round(self.image_margin * ratio)
        key = (
            self.before.cacheKey(),
            self.after.cacheKey(),
            width,
            height,
            self.scale_mode,
            margin,
        )
        if key == self._sdr_key:
            return
        self._sdr_key, self._sdr_prepared = key, None
        self.sdr_task.submit(
            prepare_sdr_frames, *self._sdr_sources, width, height, self.scale_mode, margin
        )

    def _sdr_ready(self, prepared):
        x, y, width, height, before, after = prepared
        self._sdr_prepared = (
            x,
            y,
            width,
            height,
            QPixmap.fromImage(before),
            QPixmap.fromImage(after),
        )
        self.update()

    def _sdr_failed(self, message):
        logging.getLogger(__name__).warning("SDR resampling failed: %s", message)

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

    def image_rect(self):
        if self.before.isNull():
            return QRectF()
        ratio = self.devicePixelRatioF()
        x, y, width, height = image_placement(
            self.before.width(),
            self.before.height(),
            round(self.width() * ratio),
            round(self.height() * ratio),
            self.scale_mode,
            round(self.image_margin * ratio),
        )
        return QRectF(x / ratio, y / ratio, width / ratio, height / ratio)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(
            event.position()
        ):
            event.accept()
            self.fullscreen_requested.emit()

    def paint_overlay(self, painter):
        """Paint optional controls over the SDR image."""

    def composite_overlay(self, frame):
        """Composite optional controls in linear light over a native HDR frame."""
        return frame

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#10151b"))
        if self.before.isNull():
            painter.setPen(QColor("#d6dde7"))
            painter.setFont(QFont("Segoe UI", 13))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Drop images here",
            )
            return
        if self.hdr_active:
            return  # The native child surface owns the visible pixels.
        self._request_sdr_frame()
        image_rect = self.image_rect()
        before, after = self.before, self.after
        if self._sdr_prepared is not None:
            x, y, width, height, before, after = self._sdr_prepared
            ratio = self.devicePixelRatioF()
            image_rect = QRectF(x / ratio, y / ratio, width / ratio, height / ratio)
        if self.mode == "after" and not self.after.isNull():
            painter.drawPixmap(image_rect, after, QRectF(after.rect()))
        else:
            painter.drawPixmap(image_rect, before, QRectF(before.rect()))
            if self.mode == "split" and not self.after.isNull():
                boundary = self.width() * self.split
                painter.save()
                painter.setClipRect(QRectF(boundary, 0, self.width() - boundary, self.height()))
                painter.drawPixmap(image_rect, after, QRectF(after.rect()))
                painter.restore()
                painter.setPen(QPen(QColor("#d1ebd7"), 1))
                painter.drawLine(
                    int(boundary), int(image_rect.top()), int(boundary), int(image_rect.bottom())
                )
                if self.show_split_handle:
                    painter.setBrush(QColor("#98dfa4"))
                    painter.drawEllipse(
                        int(boundary) - 12, int(image_rect.center().y()) - 12, 24, 24
                    )
                    painter.setPen(QColor("#15291a"))
                    painter.drawText(
                        QRectF(boundary - 12, image_rect.center().y() - 13, 24, 24),
                        Qt.AlignmentFlag.AlignCenter,
                        "↔",
                    )
        self.paint_overlay(painter)
