"""Versioned, aggregate gaze-check results shared by storage, UI and export."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 10 * 1024 * 1024
SETTING_KEYS = (
    "eye_tracking_policy",
    "eye_tracking_hold_ms",
    "selection_pause_ms",
    "dwell_ms",
    "edge_hold_ms",
    "click_cooldown_ms",
    "show_interaction_overlay",
)
ENVIRONMENT_KEYS = (
    "app_version",
    "build_revision",
    "backend",
    "sdk_version",
    "model",
    "firmware_version",
    "logical_screen",
    "device_pixel_ratio",
    "logical_dpi",
    "platform",
)


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def identity() -> str:
    return str(uuid4())


@dataclass
class PrecisionRow:
    name: str
    target_normalized: tuple[float, float]
    state: str = "unmeasured"
    samples: int | None = None
    coverage: float | None = None
    median_error_logical_px: float | None = None
    spread_logical_px: float | None = None
    near: bool | None = None
    gaze_center_normalized: tuple[float, float] | None = None


@dataclass
class TrialRow:
    index: int
    size_logical_px: tuple[int, int]
    state: str = "unmeasured"
    selected: bool | None = None
    coverage: float | None = None
    duration_seconds: float | None = None
    wrong_selections: int = 0
    cancelled_selections: int = 0
    departures: int = 0


@dataclass
class TrialAttempt:
    id: str
    started_at: str
    ended_at: str
    duration_seconds: float
    state: str
    reason: str | None
    rows: list[TrialRow]
    environment: dict = field(default_factory=dict)


@dataclass
class GazeCheckReport:
    id: str
    started_at: str
    ended_at: str
    duration_seconds: float
    state: str
    reason: str | None
    simulated: bool
    settings: dict
    environment: dict
    precision: list[PrecisionRow]
    trials: list[TrialAttempt] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> bytes:
        payload = json.dumps(asdict(self), ensure_ascii=False, allow_nan=False, indent=2)
        return (payload + "\n").encode("utf-8")

    @classmethod
    def from_json(cls, payload: bytes) -> GazeCheckReport:
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError("Report too large")
        data = json.loads(payload)
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != SCHEMA_VERSION
        ):
            raise ValueError("Unsupported report")
        data["precision"] = [PrecisionRow(**row) for row in data["precision"]]
        data["trials"] = [
            TrialAttempt(**{**trial, "rows": [TrialRow(**row) for row in trial["rows"]]})
            for trial in data["trials"]
        ]
        report = cls(**data)
        report.validate()
        return report

    def validate(self) -> None:
        def number(value, *, nullable=False, maximum=None):
            if value is None and nullable:
                return
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid measurement")
            if maximum is not None and value > maximum:
                raise ValueError("Measurement out of range")

        def text(value):
            if not isinstance(value, str) or len(value) > 256:
                raise ValueError("Invalid text")

        def point(value, *, nullable=False):
            if value is None and nullable:
                return
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                raise ValueError("Invalid point")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
                raise ValueError("Invalid coordinate")

        def attempt(value):
            UUID(value.id)
            for at in (value.started_at, value.ended_at):
                if datetime.fromisoformat(at).utcoffset() is None:
                    raise ValueError("Missing timezone")
            number(value.duration_seconds)
            if value.state not in ("completed", "interrupted"):
                raise ValueError("Invalid state")
            if value.reason is not None:
                text(value.reason)

        attempt(self)
        if type(self.simulated) is not bool:
            raise ValueError("Invalid simulation flag")

        def context(mapping, *, settings=False):
            keys = SETTING_KEYS if settings else ENVIRONMENT_KEYS
            if not isinstance(mapping, dict) or set(mapping) - set(keys):
                raise ValueError("Unexpected context")
            for key, value in mapping.items():
                if value is None:
                    continue
                if key == "logical_screen":
                    if not isinstance(value, (tuple, list)) or len(value) != 4:
                        raise ValueError("Invalid geometry")
                    if any(type(v) is not int for v in value) or min(value[2:]) <= 0:
                        raise ValueError("Invalid geometry")
                elif key == "show_interaction_overlay":
                    if type(value) is not bool:
                        raise ValueError("Invalid overlay setting")
                elif key == "eye_tracking_policy":
                    if not isinstance(value, str) or value not in ("both", "hold", "any"):
                        raise ValueError("Invalid policy")
                elif settings or key in ("device_pixel_ratio", "logical_dpi"):
                    number(value)
                else:
                    text(value)

        context(self.settings, settings=True)
        context(self.environment)
        if not 0 <= len(self.precision) <= 5:
            raise ValueError("Too many measurements")
        for row in self.precision:
            text(row.name)
            point(row.target_normalized)
            point(row.gaze_center_normalized, nullable=True)
            if row.state not in ("measured", "insufficient", "unmeasured"):
                raise ValueError("Invalid target state")
            number(row.samples, nullable=True)
            number(row.coverage, nullable=True, maximum=1)
            number(row.median_error_logical_px, nullable=True)
            number(row.spread_logical_px, nullable=True)
            if row.near is not None and type(row.near) is not bool:
                raise ValueError("Invalid target result")
            if row.state != "measured" and row.near is not None:
                raise ValueError("Unmeasured target has a result")
        for trial in self.trials:
            attempt(trial)
            context(trial.environment)
            if len(trial.rows) != 3:
                raise ValueError("Invalid trial")
            for index, row in enumerate(trial.rows):
                if type(row.index) is not int or row.index != index:
                    raise ValueError("Invalid trial index")
                point(row.size_logical_px)
                if row.state not in ("measured", "insufficient", "unmeasured"):
                    raise ValueError("Invalid trial state")
                if row.selected is not None and type(row.selected) is not bool:
                    raise ValueError("Invalid selection")
                number(row.coverage, nullable=True, maximum=1)
                number(row.duration_seconds, nullable=True)
                for value in (row.wrong_selections, row.cancelled_selections, row.departures):
                    if type(value) is not int or value < 0:
                        raise ValueError("Invalid trial counter")


def report_text(report: GazeCheckReport) -> str:
    """Readable companion to JSON, including every stored aggregate and its units."""
    state = {"completed": "Završeno", "interrupted": "Prekinuto"}
    rows = {
        "unmeasured": "Nije izmjereno",
        "insufficient": "Premalo podataka",
        "measured": "Izmjereno",
    }

    def show(value):
        if value is None:
            return "Nije dostupno"
        if type(value) is bool:
            return "Da" if value else "Ne"
        return str(value)

    lines = [
        "POGLED ASSIST · PROVJERA POGLEDA",
        f"Format: {report.schema_version}",
        f"ID: {report.id}",
        f"Početak: {report.started_at}",
        f"Kraj: {report.ended_at}",
        f"Trajanje: {report.duration_seconds:.3f} s",
        f"Stanje: {state[report.state]}",
        f"Razlog prekida: {show(report.reason)}",
        f"Simulacija: {show(report.simulated)}",
        "",
        "PRECIZNOST · udaljenosti u Qt logičkim pikselima; koordinate normalizovane",
    ]
    for row in report.precision:
        lines.extend(
            [
                f"{row.name}: {rows[row.state]}",
                f"  Meta: {show(row.target_normalized)}; sredina pogleda: {show(row.gaze_center_normalized)}",
                f"  Uzorci: {show(row.samples)}; pokrivenost (0–1): {show(row.coverage)}",
                f"  Odstupanje (medijan px): {show(row.median_error_logical_px)}; "
                f"rasipanje (p90 px): {show(row.spread_logical_px)}; blizu: {show(row.near)}",
            ]
        )
    for trial in report.trials:
        lines.extend(
            [
                "",
                f"PROBNI IZBOR · {trial.id} · {state[trial.state]}",
                f"Početak: {trial.started_at}; kraj: {trial.ended_at}; trajanje: {trial.duration_seconds:.3f} s",
                f"Razlog prekida: {show(trial.reason)}",
            ]
        )
        lines.extend(f"{key}: {show(trial.environment.get(key))}" for key in ENVIRONMENT_KEYS)
        for row in trial.rows:
            lines.extend(
                [
                    f"  Grupa {row.index + 1}: {rows[row.state]}; veličina: {row.size_logical_px} logičkih px",
                    f"  Odabrano: {show(row.selected)}; pokrivenost (0–1): {show(row.coverage)}; "
                    f"trajanje: {show(row.duration_seconds)} s",
                    f"  Pogrešni: {row.wrong_selections}; poništeni: {row.cancelled_selections}; "
                    f"izlasci: {row.departures}",
                ]
            )
    lines.extend(["", "POSTAVKE · nazivi polja odgovaraju JSON podacima"])
    lines.extend(f"{key}: {show(report.settings.get(key))}" for key in SETTING_KEYS)
    lines.extend(["", "OKRUŽENJE · logical_screen: x, y, širina, visina u Qt logičkim px"])
    lines.extend(f"{key}: {show(report.environment.get(key))}" for key in ENVIRONMENT_KEYS)
    lines.extend(
        [
            "",
            "Nema sirovog toka pogleda, poruka, zvuka ni tajnih ključeva.",
            "Pragovi aplikacije nisu klinička procjena ni Tobii certifikat.",
        ]
    )
    return "\n".join(lines) + "\n"
