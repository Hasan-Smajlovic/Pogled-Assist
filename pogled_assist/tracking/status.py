"""Explicit tracking lifecycle for presentation, independent of diagnostic text."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
