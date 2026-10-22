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
    "build_dirty",
    "backend",
    "sdk_version",
    "model",
    "firmware_version",
    "logical_screen",
    "device_pixel_ratio",
    "logical_dpi",
    "platform",
)


def _is_finite_nonnegative_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _validate_number(value, *, nullable=False, maximum=None):
    if value is None and nullable:
        return
    if not _is_finite_nonnegative_number(value):
        raise ValueError("Invalid measurement")
    if maximum is not None and value > maximum:
        raise ValueError("Measurement out of range")


def _validate_text(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("Invalid text")


def _validate_point(value, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, (tuple, list)):
        raise ValueError("Invalid point")
    if len(value) != 2:
        raise ValueError("Invalid point")
    for coordinate in value:
        _validate_coordinate(coordinate)


def _validate_coordinate(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid coordinate")


def _validate_attempt(value):
    UUID(value.id)
    for at in (value.started_at, value.ended_at):
        if datetime.fromisoformat(at).utcoffset() is None:
            raise ValueError("Missing timezone")
    _validate_number(value.duration_seconds)
    if value.state not in ("completed", "interrupted"):
        raise ValueError("Invalid state")
    if value.reason is not None:
        _validate_text(value.reason)


def _validate_geometry(value):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("Invalid geometry")
    if any(type(v) is not int for v in value) or min(value[2:]) <= 0:
        raise ValueError("Invalid geometry")


def _validate_context_bool(value):
    if type(value) is not bool:
        raise ValueError("Invalid overlay setting")


def _validate_context_policy(value):
    if not isinstance(value, str) or value not in ("both", "hold", "any"):
        raise ValueError("Invalid policy")


def _validate_context_value(key, value, *, settings):
    if value is None:
        return
    validators = {
        "logical_screen": _validate_geometry,
        "show_interaction_overlay": _validate_context_bool,
        "build_dirty": _validate_context_bool,
        "eye_tracking_policy": _validate_context_policy,
    }
    validator = validators.get(key)
    if validator is not None:
        validator(value)
    elif settings or key in ("device_pixel_ratio", "logical_dpi"):
        _validate_number(value)
    else:
        _validate_text(value)


def _validate_context(mapping, *, settings=False):
    keys = SETTING_KEYS if settings else ENVIRONMENT_KEYS
    if not isinstance(mapping, dict) or set(mapping) - set(keys):
        raise ValueError("Unexpected context")
    for key, value in mapping.items():
        _validate_context_value(key, value, settings=settings)


def _validate_precision_row(row):
    _validate_text(row.name)
    _validate_point(row.target_normalized)
    _validate_point(row.gaze_center_normalized, nullable=True)
    _validate_precision_measurements(row)
    _validate_precision_result(row)


def _validate_precision_measurements(row):
    _validate_number(row.samples, nullable=True)
    _validate_number(row.coverage, nullable=True, maximum=1)
    _validate_number(row.median_error_logical_px, nullable=True)
    _validate_number(row.spread_logical_px, nullable=True)


def _validate_precision_result(row):
    if row.state not in ("measured", "insufficient", "unmeasured"):
        raise ValueError("Invalid target state")
    if row.near is None:
        return
    if type(row.near) is not bool:
        raise ValueError("Invalid target result")
    if row.state != "measured":
        raise ValueError("Unmeasured target has a result")


def _validate_trial_row(row, index):
    _validate_trial_index(row, index)
    _validate_point(row.size_logical_px)
    _validate_trial_result(row)
    _validate_number(row.coverage, nullable=True, maximum=1)
    _validate_number(row.duration_seconds, nullable=True)
    _validate_trial_counters(row)


def _validate_trial_index(row, index):
    if type(row.index) is not int or row.index != index:
        raise ValueError("Invalid trial index")


def _validate_trial_result(row):
    if row.state not in ("measured", "insufficient", "unmeasured"):
        raise ValueError("Invalid trial state")
    if row.selected is not None and type(row.selected) is not bool:
        raise ValueError("Invalid selection")


def _validate_trial_counters(row):
    for value in (row.wrong_selections, row.cancelled_selections, row.departures):
        if type(value) is not int or value < 0:
            raise ValueError("Invalid trial counter")


def _validate_trial(trial):
    _validate_attempt(trial)
    _validate_context(trial.environment)
    if len(trial.rows) != 3:
        raise ValueError("Invalid trial")
    for index, row in enumerate(trial.rows):
        _validate_trial_row(row, index)


_ROW_LABELS = {
    "unmeasured": "Nije izmjereno",
    "insufficient": "Premalo podataka",
    "measured": "Izmjereno",
}


def _precision_report_lines(report):
    lines = ["PRECIZNOST · udaljenosti u Qt logičkim pikselima; koordinate normalizovane"]
    for row in report.precision:
        lines.extend(
            [
                f"{row.name}: {_ROW_LABELS[row.state]}",
                f"  Meta: {_show_value(row.target_normalized)}; sredina pogleda: "
                f"{_show_value(row.gaze_center_normalized)}",
                f"  Uzorci: {_show_value(row.samples)}; pokrivenost (0-1): "
                f"{_show_value(row.coverage)}",
                f"  Odstupanje (medijan px): {_show_value(row.median_error_logical_px)}; "
                f"rasipanje (p90 px): {_show_value(row.spread_logical_px)}; "
                f"blizu: {_show_value(row.near)}",
            ]
        )
    return lines


def _trial_report_lines(trial):
    states = {"completed": "Završeno", "interrupted": "Prekinuto"}
    lines = [
        "",
        f"PROBNI IZBOR · {trial.id} · {states[trial.state]}",
        f"Početak: {trial.started_at}; kraj: {trial.ended_at}; "
        f"trajanje: {trial.duration_seconds:.3f} s",
        f"Razlog prekida: {_show_value(trial.reason)}",
    ]
    lines.extend(f"{key}: {_show_value(trial.environment.get(key))}" for key in ENVIRONMENT_KEYS)
    for row in trial.rows:
        lines.extend(
            [
                f"  Grupa {row.index + 1}: {_ROW_LABELS[row.state]}; veličina: "
                f"{_show_value(row.size_logical_px)} logičkih px",
                f"  Odabrano: {_show_value(row.selected)}; pokrivenost (0-1): "
                f"{_show_value(row.coverage)}; trajanje: {_show_value(row.duration_seconds)} s",
                f"  Pogrešni: {row.wrong_selections}; poništeni: "
                f"{row.cancelled_selections}; izlasci: {row.departures}",
            ]
        )
    return lines


def _show_value(value):
    if value is None:
        return "Nije dostupno"
    if type(value) is bool:
        return "Da" if value else "Ne"
    if isinstance(value, (tuple, list)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    return str(value)


def _decode_precision_rows(rows):
    return [PrecisionRow(**row) for row in rows]


def _decode_trial_rows(trials):
    decoded = []
    for trial in trials:
        value = dict(trial)
        value["rows"] = [TrialRow(**row) for row in trial["rows"]]
        decoded.append(TrialAttempt(**value))
    return decoded


def _has_supported_schema(data) -> bool:
    return (
        isinstance(data, dict)
        and type(data.get("schema_version")) is int
        and data["schema_version"] == SCHEMA_VERSION
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
        if not _has_supported_schema(data):
            raise ValueError("Unsupported report")
        data["precision"] = _decode_precision_rows(data["precision"])
        data["trials"] = _decode_trial_rows(data["trials"])
        report = cls(**data)
        report.validate()
        return report

    def validate(self) -> None:
        _validate_attempt(self)
        if type(self.simulated) is not bool:
            raise ValueError("Invalid simulation flag")
        _validate_context(self.settings, settings=True)
        _validate_context(self.environment)
        if not 0 <= len(self.precision) <= 5:
            raise ValueError("Too many measurements")
        for row in self.precision:
            _validate_precision_row(row)
        for trial in self.trials:
            _validate_trial(trial)


def report_text(report: GazeCheckReport) -> str:
    """Readable companion to JSON, including every stored aggregate and its units."""
    state = {"completed": "Završeno", "interrupted": "Prekinuto"}
    lines = [
        "POGLED ASSIST · PROVJERA POGLEDA",
        f"Format: {report.schema_version}",
        f"ID: {report.id}",
        f"Početak: {report.started_at}",
        f"Kraj: {report.ended_at}",
        f"Trajanje: {report.duration_seconds:.3f} s",
        f"Stanje: {state[report.state]}",
        f"Razlog prekida: {_show_value(report.reason)}",
        f"Simulacija: {_show_value(report.simulated)}",
        "",
    ]
    lines.extend(_precision_report_lines(report))
    for trial in report.trials:
        lines.extend(_trial_report_lines(trial))
    lines.extend(["", "POSTAVKE · nazivi polja odgovaraju JSON podacima"])
    lines.extend(f"{key}: {_show_value(report.settings.get(key))}" for key in SETTING_KEYS)
    lines.extend(["", "OKRUŽENJE · logical_screen: x, y, širina, visina u Qt logičkim px"])
    lines.extend(f"{key}: {_show_value(report.environment.get(key))}" for key in ENVIRONMENT_KEYS)
    lines.extend(
        [
            "",
            "Nema sirovog toka pogleda, poruka, zvuka ni tajnih ključeva.",
            "Pragovi aplikacije nisu klinička procjena ni Tobii certifikat.",
        ]
    )
    return "\n".join(lines) + "\n"
