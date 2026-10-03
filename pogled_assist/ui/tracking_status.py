"""Passive tracking status that stays inside the hotbar."""

from __future__ import annotations

import time
from dataclasses import dataclass

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..tracking.gaze_provider import GAZE_DELIVERY_GAP_SECONDS
from ..tracking.status import TrackingState, TrackingStatus


@dataclass(frozen=True)
class TrackingStatusView:
    title: str
    detail: str
    icon: str
    color: str


def tracking_status_view(
    status: TrackingStatus,
    eyes: tuple[bool, bool] | None,
    last_gaze_at: float | None,
    now: float,
) -> TrackingStatusView:
    fixed = {
        TrackingState.CONNECTING: (
            "Povezivanje…",
            "Tražim Tobii uređaj",
            "hourglass-half",
            "#f2ce76",
        ),
        TrackingState.WAITING: (
            "Čekam podatke",
            "Podaci o očima kasne",
            "hourglass-half",
            "#f2ce76",
        ),
        TrackingState.RETRYING: ("Uređaj nije povezan", "Pokušavam ponovo", "plug", "#ffa0a8"),
        TrackingState.STOPPED: (
            "Praćenje zaustavljeno",
            "Praćenje nije pokrenuto",
            "stop-circle",
            "#bec9d9",
        ),
        TrackingState.SIMULATING: (
            "Simulacija mišem",
            "Upravljanje mišem",
            "mouse-pointer",
            "#a0cef3",
        ),
        TrackingState.UNAVAILABLE: (
            "Simulacija nedostupna",
            "Glavni ekran nije dostupan",
            "exclamation-circle",
            "#ffa0a8",
        ),
    }
    if status.state in fixed:
        return TrackingStatusView(*fixed[status.state])
    if eyes is None:
        return TrackingStatusView(
            "Čekam podatke", "Čekam stanje očiju", "hourglass-half", "#f2ce76"
        )
    detail = f"Lijevo {'✓' if eyes[0] else '—'}    Desno {'✓' if eyes[1] else '—'}"
    if not all(eyes):
        return TrackingStatusView("Praćenje pauzirano", detail, "pause-circle", "#f2ce76")
    if last_gaze_at is None or now - last_gaze_at >= GAZE_DELIVERY_GAP_SECONDS:
        detail = "Čekam podatke o pogledu" if last_gaze_at is None else "Podaci o pogledu kasne"
        return TrackingStatusView("Čekam podatke", detail, "hourglass-half", "#f2ce76")
    return TrackingStatusView("Praćenje spremno", detail, "check-circle", "#70dfa1")


class TrackingStatusWidget(QWidget):
    """Report readiness without creating an action, overlay, or input gate."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trackingStatus")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(210, 58)
        self.setFocusPolicy(Qt.NoFocus)
        self._status = TrackingStatus(TrackingState.CONNECTING)
        self._eyes: tuple[bool, bool] | None = None
        self._last_gaze_at: float | None = None
        self._view: TrackingStatusView | None = None
        self._accessible_name: str | None = None
        self._tooltip: str | None = None
        self._icon = QLabel(self)
        self._icon.setObjectName("trackingIcon")
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setFixedSize(QSize(18, 18))
        self._title = QLabel(self)
        self._detail = QLabel(self)
        self._title.setObjectName("trackingTitle")
        self._detail.setObjectName("trackingDetail")
        for label in (self._title, self._detail):
            label.setTextFormat(Qt.PlainText)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        title_row.addWidget(self._icon)
        title_row.addWidget(self._title, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 0, 5)
        layout.setSpacing(3)
        layout.addStretch()
        layout.addLayout(title_row)
        layout.addWidget(self._detail)
        layout.addStretch()
        self._freshness_timer = QTimer(self)
        self._freshness_timer.setInterval(100)
        self._freshness_timer.timeout.connect(self._refresh)
        self._refresh()

    def set_tracking_status(self, status: TrackingStatus) -> None:
        self._status = status
        if status.state != TrackingState.CONNECTED:
            self._last_gaze_at = None
            self._freshness_timer.stop()
            if status.state != TrackingState.WAITING:
                self._eyes = None
        else:
            self._freshness_timer.start()
        self._refresh()

    def set_eye_status(self, left_valid: bool, right_valid: bool) -> None:
        self._eyes = (bool(left_valid), bool(right_valid))
        if not all(self._eyes):
            self._last_gaze_at = None
        self._refresh()

    def handle_gaze(self, _x: float, _y: float, _timestamp: object) -> None:
        if self._status.state == TrackingState.CONNECTED and self._eyes == (True, True):
            self._last_gaze_at = time.monotonic()
            self._refresh()

    def _refresh(self) -> None:
        view = tracking_status_view(self._status, self._eyes, self._last_gaze_at, time.monotonic())
        if view != self._view:
            self._view = view
            self._title.setText(view.title)
            self._detail.setText(view.detail)
            try:
                self._icon.setPixmap(qta.icon(f"fa5s.{view.icon}", color=view.color).pixmap(18, 18))
            except Exception:
                # A font-loading failure must not prevent the hotbar from opening.
                symbols = {
                    "check-circle": "✓",
                    "pause-circle": "Ⅱ",
                    "stop-circle": "Ⅱ",
                    "hourglass-half": "◷",
                    "mouse-pointer": "↖",
                }
                self._icon.setText(symbols.get(view.icon, "!"))
            self.setStyleSheet(
                f"QWidget#trackingStatus {{background: transparent; border-left: 2px solid {view.color};}}"
                "QLabel {background: transparent; color: #eef2f8;}"
                "QLabel#trackingTitle {font-size: 15px; font-weight: 600;}"
                "QLabel#trackingDetail {font-size: 13px; color: #bec9d9;}"
                f"QLabel#trackingIcon {{font-size: 18px; color: {view.color};}}"
            )
        accessible = f"{view.title}. {view.detail}"
        if self._eyes is not None and self._status.state == TrackingState.CONNECTED:
            accessible = (
                accessible
                + ". "
                + ". ".join(
                    f"{label} oko: {'podatak validan' if valid else 'nema validnog podatka'}"
                    for label, valid in zip(("Lijevo", "Desno"), self._eyes, strict=True)
                )
            )
        if accessible != self._accessible_name:
            self._accessible_name = accessible
            self.setAccessibleName(accessible)
        tooltip = f"{accessible}\n{self._status.detail}".strip()
        if tooltip != self._tooltip:
            self._tooltip = tooltip
            self.setToolTip(tooltip)
