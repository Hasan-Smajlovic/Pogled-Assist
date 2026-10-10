"""Explicit tracking lifecycle for presentation, independent of diagnostic text."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

GAZE_DELIVERY_GAP_SECONDS = 0.5


class TrackingState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    WAITING = "waiting"
    RETRYING = "retrying"
    STOPPED = "stopped"
    SIMULATING = "simulating"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TrackingStatus:
    state: TrackingState
    detail: str = ""
