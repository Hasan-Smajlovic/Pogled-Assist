"""Shared control states for the reviewed calm dark design."""

from PySide6.QtWidgets import QWidget


def apply_theme(widget: QWidget, stylesheet: str) -> None:
    widget.setStyleSheet(stylesheet + CONTROL_STATES)


CONTROL_STATES = """
QPushButton:focus, QToolButton:focus, QCheckBox:focus,
QComboBox:focus, QLineEdit:focus {
    border: 2px solid #84c5d9;
}
QDialog#speechDialog QPushButton#dialogConfirmButton[gazeTarget="true"],
QDialog#speechDialog QPushButton#dialogCancelButton[gazeTarget="true"],
QDialog#sleepDialog QPushButton#wakeButton[gazeTarget="true"],
QToolButton#navButton[gazeTarget="true"], QToolButton#primaryButton[gazeTarget="true"],
QToolButton#dangerButton[gazeTarget="true"], QToolButton#adjustButton[gazeTarget="true"],
QToolButton#utilityButton[gazeTarget="true"], QToolButton#tabButton[gazeTarget="true"],
QToolButton#checkButton[gazeTarget="true"], QToolButton#hideButton[gazeTarget="true"],
QToolButton#restoreHotbarButton[gazeTarget="true"],
QPushButton[gazeTarget="true"], QToolButton[gazeTarget="true"],
QCheckBox[gazeTarget="true"], QComboBox[gazeTarget="true"] {
    border: 3px solid #84c5d9;
    color: #edf2f7;
}
QToolButton#sectionTab {
    background: transparent;
    color: #b8c5d2;
    border: 0;
    border-bottom: 3px solid #394959;
    border-radius: 0;
    font-size: 17px;
    font-weight: 500;
}
QToolButton#sectionTab:checked {
    color: #edf2f7;
    border-bottom-color: #84c5d9;
    font-weight: 600;
}
QToolButton#sectionTab[gazeTarget="true"] {
    border: 3px solid #84c5d9;
}
QFrame#settingsGroup {
    border: 1px solid #394959;
    border-radius: 10px;
    background: #1d242d;
}
QGroupBox {
    color: #b8c5d2;
    border: 1px solid #394959;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 12px;
    font-size: 16px;
    font-weight: 600;
}
QSlider::groove:horizontal { height: 6px; background: #394959; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #84c5d9; border-radius: 3px; }
QSlider::handle:horizontal { width: 18px; margin: -6px 0; background: #84c5d9; border-radius: 9px; }
QScrollBar:vertical { width: 12px; background: #1d242d; }
QScrollBar::handle:vertical { min-height: 40px; background: #71869b; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
"""
