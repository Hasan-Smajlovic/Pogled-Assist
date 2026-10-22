"""Synthetic recording screens; previews never start a writer or export files."""

from copy import deepcopy

from PySide6.QtCore import QObject, Signal

from pogled_assist.diagnostic_recording import recording_context
from pogled_assist.tracking.gaze_check_store import GazeCheckStore
from pogled_assist.ui.diagnostics_window import DiagnosticsWindow
from pogled_assist.ui.gaze_check_reports import GazeCheckReports
from pogled_assist.ui.recording_badge import RecordingIndicator


class PreviewRecordings(QObject):
    changed = Signal()
    exported = Signal(str, bool)
    status = None
    entries = ()
    loading = False
    history_error = False
    _exporting = False

    def __init__(self):
        super().__init__()
        self.indicator = RecordingIndicator(self)
        self.changed.connect(self._update_indicator)

    def _update_indicator(self):
        self.indicator.set_status(self.status)

    @property
    def busy(self):
        return bool(self.status and self.status.get("busy"))

    def load(self):
        pass


class CaptureDiagnostics:
    def capture_diagnostics(self):
        service = PreviewRecordings()
        reports = GazeCheckReports(GazeCheckStore(self.output_dir / ".unused-reports"))
        reports.load = lambda: None
        context = recording_context(
            {"eye_tracking_policy": "both", "selection_pause_ms": 250, "dwell_ms": 850},
            {"backend": "mouse-simulation", "logical_screen": (0, 0, 1280, 720)},
            simulated=True,
        )
        context["build"] = {"app_version": "0.1.0", "build_revision": "a" * 40, "build_dirty": True}
        window = DiagnosticsWindow(service, reports, lambda: context, logging_enabled=lambda: False)
        self.widgets.append(window)
        self.capture(window, "diagnostics-ready", "Diagnostics: new recording")
        service.status = {
            "busy": True,
            "id": "a" * 32,
            "state": "recording",
            "minutes": 2,
            "remaining_seconds": 83,
            "bytes": 3250000,
        }
        service.changed.emit()
        self.capture(
            window,
            "diagnostics-recording",
            "Diagnostics: recording independently of normal logging",
        )
        service.status = {**service.status, "state": "finishing"}
        service.changed.emit()
        self.capture(window, "diagnostics-finishing", "Diagnostics: waiting for the writer")
        entry = {
            "id": "a" * 32,
            "started_at": "2026-10-22T12:32:00+02:00",
            "ended_at": "2026-10-22T12:34:00+02:00",
            "duration_seconds": 120,
            "state": "completed",
            "reason": "time",
            "complete": True,
            "session_end_present": True,
            "bytes": 10000000,
            "context": context,
            "health": {"dropped": {}, "writer_errors": 0, "bounded_snapshots": 0},
        }
        service.entries = [entry]
        service.status = {**entry, "busy": False}
        service.changed.emit()
        window._tabs.setCurrentIndex(1)
        self.capture(
            window, "diagnostics-history", "Diagnostics: saved recording and optional check result"
        )
        for name, reason, health in (
            (
                "interrupted",
                "missing_end",
                {"dropped": {"event": 23}, "writer_errors": 0, "bounded_snapshots": 0},
            ),
            ("error", "writer_error", {"dropped": {}, "writer_errors": 1, "bounded_snapshots": 0}),
        ):
            service.entries = [
                {
                    **deepcopy(entry),
                    "state": "error" if reason == "writer_error" else "interrupted",
                    "complete": False,
                    "reason": reason,
                    "session_end_present": False,
                    "health": health,
                }
            ]
            service.status = {**service.entries[0], "busy": False}
            service.changed.emit()
            self.capture(window, "diagnostics-" + name, "Diagnostics: " + name)
        window._status.setText("Izvoz ZIP-a nije uspio. Snimak ostaje dostupan; pokušajte ponovo.")
        self.capture(window, "diagnostics-export-error", "Diagnostics: export failed")
