"""A fixed-capacity estimate for the focused image, independent of job progress."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..resources import GiB, estimate_gpu_bytes


def pressure_color(estimate, capacity):
    ratio = estimate / capacity if capacity else 0
    return "#ff6b6b" if ratio >= 0.9 else "#efc75e" if ratio >= 0.8 else "#8bd89a"


class MemoryBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.estimate = self.capacity = 0
        self.setFixedHeight(7)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#283241"))
        rect = QRectF(self.rect())
        painter.drawRoundedRect(rect, 3, 3)
        if self.capacity and self.estimate:
            painter.setClipRect(rect)
            rect.setWidth(rect.width() * min(1, self.estimate / self.capacity))
            painter.setBrush(QColor(pressure_color(self.estimate, self.capacity)))
            painter.drawRoundedRect(rect, 3, 3)


class MemoryEstimate(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.info = self.gpu = None
        self.error = ""
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.value = QLabel()
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.bar = MemoryBar()
        self.bar.setAccessibleName("Estimated GPU memory")
        self.overflow = QLabel()
        self.overflow.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.overflow.setWordWrap(True)
        for widget in (self.value, self.bar, self.overflow):
            layout.addWidget(widget)
        self.refresh()

    def set_image(self, info):
        self.info = info
        self.refresh()

    def set_gpu(self, gpu, error=""):
        self.gpu, self.error = gpu, error
        self.refresh()

    def refresh(self):
        estimate = estimate_gpu_bytes(self.info["width"], self.info["height"]) if self.info else 0
        capacity = self.gpu["total"] if self.gpu else 0
        self.bar.estimate, self.bar.capacity = estimate, capacity
        self.bar.update()
        self.bar.setAccessibleDescription(f"{estimate} estimated bytes; {capacity} capacity bytes")
        self.value.setText(
            f"Est. GPU: ~{estimate / GiB:.2f} / {capacity / GiB:.2f} GiB"
            if estimate and capacity
            else "Est. GPU: unavailable"
            if estimate
            else "Est. GPU: —"
        )
        extra = max(0, estimate - capacity) if capacity else 0
        self.overflow.setText(f"~{extra / GiB:.2f} GiB shared memory expected" if extra else "")
        self.overflow.setVisible(bool(extra))
        self.overflow.setStyleSheet("color: #ff6b6b;")
        text = (
            "Focused image only. Approximate native TrueHDR allocation demand, not live usage.\n"
            "Measured model: 247 MiB + 32.068 bytes/pixel. Alignment, extreme aspect ratios,\n"
            "other GPUs/SDKs and other applications can change residency and peak usage.\n"
            "The scale is dedicated VRAM capacity; shared RAM is excluded.\n"
            "CPU buffers require additional RAM and scratch disk space."
        )
        if self.gpu:
            text += f"\nGPU {self.gpu['device']}: {self.gpu['name']}"
        if self.error:
            text += f"\n{self.error}"
        self.setToolTip(text)
