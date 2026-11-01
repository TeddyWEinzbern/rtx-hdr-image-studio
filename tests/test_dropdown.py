import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QVBoxLayout, QWidget

from rtx_hdr_studio.ui.dropdown import Dropdown, popup_geometry
from rtx_hdr_studio.ui.window import STYLE


@pytest.mark.parametrize(
    "anchor, screen, height, expected",
    [
        (QRect(100, 100, 200, 32), QRect(0, 0, 800, 600), 138, QRect(100, 135, 200, 138)),
        (QRect(100, 550, 200, 32), QRect(0, 0, 800, 600), 138, QRect(100, 409, 200, 138)),
        (QRect(700, 100, 200, 32), QRect(0, 0, 800, 600), 138, QRect(600, 135, 200, 138)),
        (QRect(100, 300, 200, 32), QRect(0, 0, 800, 600), 900, QRect(100, 0, 200, 297)),
        (
            QRect(-1400, 100, 200, 32),
            QRect(-1600, 0, 1600, 900),
            138,
            QRect(-1400, 135, 200, 138),
        ),
    ],
)
def test_popup_fits_available_screen(anchor, screen, height, expected):
    assert popup_geometry(anchor, screen, height) == expected


@pytest.fixture
def dropdown():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.setStyleSheet(STYLE)
    host.setGeometry(50, 50, 300, 100)
    layout = QVBoxLayout(host)
    combo = Dropdown()
    combo.addItems(["Original", "Processed", "Split view"])
    layout.addWidget(combo)
    host.show()
    app.processEvents()
    yield combo
    combo.hidePopup()
    host.close()
    app.processEvents()


def test_popup_matches_control_dimensions_font_and_rounding(dropdown):
    combo = dropdown
    for current in (0, 2):
        combo.setCurrentIndex(current)
        combo.showPopup()
        QTest.qWait(200)  # Check the final position after any native popup animation.
        view, popup = combo.view(), combo.view().window()
        anchor = combo.mapToGlobal(QPoint())
        assert popup.width() == combo.width()
        assert popup.x() == anchor.x()
        assert popup.y() == anchor.y() + combo.height() + 3
        assert view.font() == combo.font()
        for row in range(combo.count()):
            index = combo.model().index(row, 0)
            assert view.visualRect(index).height() == combo.height()
            option = QStyleOptionViewItem()
            combo.itemDelegate().initStyleOption(option, index)
            assert option.font == combo.font()
            assert option.fontMetrics.height() == QFontMetrics(combo.font()).height()
        assert not popup.mask().isEmpty()
        assert not popup.mask().contains(QPoint(0, 0))
        assert popup.mask().contains(popup.rect().center())
        combo.hidePopup()


def test_popup_keeps_keyboard_selection_and_escape_cancel(dropdown):
    spy = QSignalSpy(dropdown.activated)
    dropdown.showPopup()
    QTest.keyClick(dropdown.view(), Qt.Key.Key_Down)
    QTest.keyClick(dropdown.view(), Qt.Key.Key_Return)
    assert dropdown.currentIndex() == 1
    assert spy.count() == 1
    assert not dropdown.view().window().isVisible()
    dropdown.showPopup()
    QTest.keyClick(dropdown.view(), Qt.Key.Key_Down)
    QTest.keyClick(dropdown.view(), Qt.Key.Key_Escape)
    assert dropdown.currentIndex() == 1
    assert spy.count() == 1
    assert not dropdown.view().window().isVisible()


def test_popup_mouse_selection_retains_item_data(dropdown):
    dropdown.setItemData(2, "split")
    spy = QSignalSpy(dropdown.activated)
    dropdown.showPopup()
    # Qt ignores an immediate release after programmatic opening to avoid
    # accidentally accepting the click which opened the popup.
    QTest.qWait(QApplication.doubleClickInterval() + 20)
    index = dropdown.model().index(2, 0)
    QTest.mouseClick(
        dropdown.view().viewport(),
        Qt.MouseButton.LeftButton,
        pos=dropdown.view().visualRect(index).center(),
    )
    assert dropdown.currentData() == "split"
    assert spy.count() == 1
    assert not dropdown.view().window().isVisible()


def test_popup_dismisses_on_outside_click(dropdown):
    dropdown.showPopup()
    QTest.mouseClick(dropdown.view().window(), Qt.MouseButton.LeftButton, pos=QPoint(-5, -5))
    assert not dropdown.view().window().isVisible()


def test_long_popup_scrolls_without_changing_row_height(dropdown):
    dropdown.addItems([f"Option {index}" for index in range(30)])
    dropdown.setCurrentIndex(dropdown.count() - 1)
    dropdown.showPopup()
    QTest.qWait(200)
    view = dropdown.view()
    assert view.verticalScrollBar().isVisible()
    index = dropdown.model().index(dropdown.currentIndex(), 0)
    assert view.visualRect(index).height() == dropdown.height()
    assert view.viewport().rect().contains(view.visualRect(index).center())
    assert view.window().width() == dropdown.width()


@pytest.mark.parametrize("near_bottom", [False, True])
def test_popup_uses_final_position_without_jumping_after_opening(dropdown, near_bottom):
    host = dropdown.window()
    if near_bottom:
        host.move(host.x(), dropdown.screen().availableGeometry().bottom() - host.height() + 1)
    QApplication.processEvents()
    animation = QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    dropdown.showPopup()
    popup = dropdown.view().window()
    anchor = QRect(dropdown.mapToGlobal(QPoint()), dropdown.size())
    expected = popup_geometry(anchor, dropdown.screen().availableGeometry(), 106)
    assert popup.geometry() == expected
    assert dropdown.screen().availableGeometry().contains(popup.geometry())
    if near_bottom:
        assert popup.geometry().bottom() < anchor.top()
    else:
        assert popup.geometry().top() > anchor.bottom()
    QTest.qWait(250)
    assert popup.geometry() == expected
    assert QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo) == animation
