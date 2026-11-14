"""Shared presentation for caregiver check and diagnostics surfaces."""

from PySide6.QtWidgets import QScrollArea, QWidget

CHECK_SURFACE_STYLE = """
QWidget#gazeCheck, QWidget#diagnostics { background: #15191f; color: #edf2f7; font-family: Segoe UI; }
QLabel { color: #edf2f7; background: transparent; font-size: 17px; }
QLabel#checkTitle { font-size: 29px; font-weight: 650; }
QLabel#cardTitle { font-size: 23px; font-weight: 600; }
QLabel#checkHint { font-size: 15px; color: #b8c5d2; }
QLabel#checkSimulation { font-size: 13px; color: #efd092; }
QFrame#checkHeader { border: 0; border-bottom: 1px solid #394959; }
QFrame#checkContext { border: 0; border-left: 1px solid #394959; }
QFrame#checkCard { background: #1d242d; border: 1px solid #394959; border-radius: 12px; }
QFrame#checkEyes { border: 0; border-top: 1px solid #394959; }
QPushButton { background: #283442; color: #edf2f7; border: 1px solid #71869b;
    border-radius: 9px; padding: 10px 16px; font-size: 18px; font-weight: 600; }
QPushButton:hover { background: #334355; border-color: #84c5d9; }
QPushButton:focus { border: 2px solid #84c5d9; }
QFrame#checkResources, QFrame#checkDeviceActions { border: 0; border-right: 1px solid #394959; }
QPushButton#checkPrimary { background: #2e6478; border-color: #84c5d9; }
QPushButton:disabled, QPushButton#checkPrimary:disabled { background: #222b35;
    border-color: #455363; color: #8595a6; }
QProgressBar { background: #394959; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #84c5d9; border-radius: 3px; }
QScrollArea, QScrollArea QWidget { background: #1d242d; border: none; }
QComboBox { background: #334355; color: #edf2f7; padding: 8px; font-size: 17px; }
QComboBox QAbstractItemView { background: #334355; color: #edf2f7; }
"""


def scroll_content(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setWidget(widget)
    return scroll
