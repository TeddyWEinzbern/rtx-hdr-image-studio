"""Consistent rounded combo popups, retaining Qt selection and keyboard handling."""

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QListView,
    QProxyStyle,
    QStyle,
    QStyledItemDelegate,
)


def popup_geometry(anchor, available, preferred_height, gap=3):
    """Align with the control; flip above it or scroll when screen space is limited."""
    width = min(anchor.width(), available.width())
    below_y = anchor.bottom() + 1 + gap
    below = max(0, available.bottom() - below_y + 1)
    above = max(0, anchor.top() - gap - available.top())
    if preferred_height <= below or below >= above:
        height = min(preferred_height, max(1, below))
        y = below_y
    else:
        height = min(preferred_height, max(1, above))
        y = anchor.top() - gap - height
    x = max(available.left(), min(anchor.left(), available.right() - width + 1))
    y = max(available.top(), min(y, available.bottom() - height + 1))
    return QRect(x, y, width, height)


class DropdownStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, return_data=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0  # Use a list below the control, rather than a selected-row overlay.
        if hint == QStyle.StyleHint.SH_ComboBox_PopupFrameStyle:
            return QFrame.Shape.NoFrame
        return super().styleHint(hint, option, widget, return_data)


class DropdownDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.font = self.parent().font()
        option.fontMetrics = QFontMetrics(option.font)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(self.parent().height())
        return size


class Dropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        style = DropdownStyle("Fusion")
        style.setParent(self)
        self.setStyle(style)
        self.setView(QListView(self))
        self.setItemDelegate(DropdownDelegate(self))
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view().setUniformItemSizes(True)
        popup = self.view().window()
        popup.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def showPopup(self):
        if not self.count():
            return
        self.view().setFont(self.font())
        self.view().doItemsLayout()
        super().showPopup()
        popup = self.view().window()
        popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.layout().setContentsMargins(0, 0, 0, 0)
        anchor = QRect(self.mapToGlobal(QPoint()), self.size())
        screen = QGuiApplication.screenAt(anchor.center()) or self.screen()
        height = min(self.count(), self.maxVisibleItems()) * self.height() + 10
        popup.setGeometry(popup_geometry(anchor, screen.availableGeometry(), height))
        self.view().doItemsLayout()
        self.view().scrollTo(self.view().currentIndex())
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(popup.rect()), 5, 5)
        popup.setMask(QRegion(outline.toFillPolygon().toPolygon()))
