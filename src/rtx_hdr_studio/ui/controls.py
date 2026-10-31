"""Small reusable parameter controls; wheel scrolling does not change values."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget


class QuietSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()


class QuietSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class Parameter(QWidget):
    changed = Signal()

    def __init__(self, title: str, low: int, high: int, *, decimals=0, suffix="", help_text=""):
        super().__init__()
        self.scale = 100 if decimals else 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(title), 1)
        self.spin = QuietSpinBox()
        self.spin.setAccessibleName(title)
        self.spin.setDecimals(decimals)
        self.spin.setRange(low, high)
        self.spin.setSuffix(suffix)
        self.spin.setSingleStep(0.1 if decimals else 1)
        self.spin.setFixedWidth(100)
        row.addWidget(self.spin)
        layout.addLayout(row)
        self.slider = QuietSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName(title + " slider")
        self.slider.setRange(low * self.scale, high * self.scale)
        layout.addWidget(self.slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.setToolTip(help_text)

    def _from_spin(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(round(value * self.scale))
        self.slider.blockSignals(False)
        self.changed.emit()

    def _from_slider(self, value):
        self.spin.setValue(value / self.scale)

    def value(self):
        return self.spin.value() if self.scale > 1 else int(self.spin.value())

    def set_value(self, value):
        self.spin.setValue(value)
