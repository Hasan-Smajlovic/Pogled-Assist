"""Synthetic gaze-check states for the UI gallery."""

import time
from dataclasses import replace

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication

from pogled_assist.tracking.gaze_check import CheckSnapshot, FixationCheck, FixationResult
from pogled_assist.tracking.status import TrackingState, TrackingStatus
from pogled_assist.ui.gaze_check_views import TARGETS
from pogled_assist.ui.gaze_check_window import GazeCheckWindow


class CaptureGazeCheck:
    def capture_gaze_check(self) -> None:
        window = GazeCheckWindow(self.gaze_settings)
        self.widgets.append(window)
        size = min(self.size[0], 1280), min(self.size[1], 720)
        # Static synthetic data and frozen UI ticks keep the gallery deterministic.
        window._timer.timeout.disconnect(window._tick)
        self.capture(window, "gaze-check-unavailable", "Gaze check: data unavailable", size=size)
        window._snapshot = CheckSnapshot(position_supported=False)
        window._render_position()
        self.capture(
            window, "gaze-check-unsupported", "Gaze check: eye positions unsupported", size=size
        )
        window.handle_tracking_status(TrackingStatus(TrackingState.RETRYING))
        self.capture(window, "gaze-check-disconnected", "Gaze check: disconnected", size=size)
        window.handle_tracking_status(TrackingStatus(TrackingState.CONNECTED))
        window._snapshot = CheckSnapshot(
            True,
            True,
            (0.6, 0.5, 0.45),
            (0.4, 0.5, 0.45),
            gaze=(0.5, 0.5),
            observed_seconds=10,
            available_fraction=0.98,
            longest_loss_seconds=0.15,
        )
        window._render_position()
        self.capture(window, "gaze-check-position", "Gaze check: live position", size=size)
        window._position_help.show_help()
        self.capture_dialog(window._position_help.popup, "information-position", "Position help")
        window._position_help.popup.close()
        window._recording_badge.set_status(
            {"busy": True, "state": "recording", "remaining_seconds": 83}
        )
        self.capture(window, "gaze-check-recording", "Gaze check: recording status", size=size)
        window._recording_badge.set_status(None)
        window._snapshot = replace(
            window._snapshot,
            left=False,
            right=False,
            gaze=None,
            available_fraction=0.6,
            longest_loss_seconds=1.1,
        )
        window._render_position()
        self.capture(
            window,
            "gaze-check-position-without-gaze",
            "Gaze check: eye positions without valid gaze",
            size=size,
        )
        waiting_snapshot = window._snapshot
        for name, title, left, right in (
            ("too-close", "move display away", (0.6, 0.5, -0.2), (0.4, 0.5, -0.1)),
            ("too-far", "move display closer", (0.6, 0.5, 1.2), (0.4, 0.5, 1.1)),
            ("outside-frame", "align display", (1.2, -0.1, 0.5), (1.1, -0.1, 0.5)),
        ):
            window._snapshot = replace(waiting_snapshot, left_position=left, right_position=right)
            window._render_position()
            self.capture(window, f"gaze-check-{name}", f"Gaze check: {title}", size=size)
        window._snapshot = replace(
            waiting_snapshot,
            left=True,
            right_position=None,
        )
        window._render_position()
        self.capture(window, "gaze-check-interrupted", "Gaze check: eye loss", size=size)
        self._capture_precision(window, size)
        self._capture_trial(window, size)
        self._capture_reports(window, size)
        self._capture_free(window, size)
        single = GazeCheckWindow(replace(self.gaze_settings, eye_tracking_policy="any"))
        self.widgets.append(single)
        single.resize(*size)
        single._timer.timeout.disconnect(single._tick)
        single.show()
        self.app.processEvents()
        single._start_free()
        single._snapshot = CheckSnapshot(True, False, gaze=(0.5, 0.5), gaze_at=time.monotonic())
        single._render_free()
        self.capture(single, "gaze-check-one-eye-free", "Gaze check: one-eye free view", size=size)
        held = GazeCheckWindow(replace(self.gaze_settings, eye_tracking_policy="hold"))
        self.widgets.append(held)
        held.resize(*size)
        held._timer.timeout.disconnect(held._tick)
        held.show()
        self.app.processEvents()
        held._start_trial()
        held._target.progress = 0.65
        held._target.progress_target = held._target.expected_button
        held._target.paused = True
        held._set_trial_hint("Na čekanju · čuvam napredak do povratka oba oka.")
        self.capture(held, "gaze-check-trial-held", "Gaze check: paused trial", size=size)

    def _capture_precision(self, window, size):
        window._start_precision()
        self.capture(window, "gaze-check-precision", "Gaze check: fixation target", size=size)
        window._snapshot = CheckSnapshot(True, False)
        window._snapshot_at = time.monotonic()
        window._check.started_at = time.monotonic() - 1.2
        window._tick()
        self.capture(
            window, "gaze-check-precision-waiting", "Gaze check: fixation eye loss", size=size
        )
        targets = list(TARGETS)
        window._check = FixationCheck(targets, size, 36, 0)
        window._check.results = [
            FixationResult(name, 90, 0.9 if near is not None else 0.2, error, spread, near, center)
            for name, error, spread, near, center in (
                ("Sredina", 12, 8, True, (0.51, 0.5)),
                ("Gore lijevo", 14, 10, True, (0.05, 0.07)),
                ("Gore desno", 48, 12, False, (0.92, 0.09)),
                ("Dolje lijevo", 18, 9, True, (0.05, 0.93)),
                ("Dolje desno", None, None, None, None),
            )
        ]
        window._show_results()
        self.capture(window, "gaze-check-results", "Gaze check: measured results", size=size)
        window._details_button.click()
        self.capture(
            window, "gaze-check-results-details", "Gaze check: optional measurements", size=size
        )
        window._details_button.click()
        window._check.results[-1] = FixationResult(
            "Dolje desno", 90, 0.9, 48, 12, False, (0.92, 0.9)
        )
        window._phase = "precision"
        window._begin_attempt()
        window._show_results()
        self.capture(window, "gaze-check-results-misses", "Gaze check: measured misses", size=size)
        window._check.results = [
            FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in targets
        ]
        window._phase = "precision"
        window._begin_attempt()
        window._show_results()
        self.capture(window, "gaze-check-results-ready", "Gaze check: targets passed", size=size)

    def _capture_trial(self, window, size):
        window._start_trial()
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(window, "gaze-check-trial", "Gaze check: local dwell trial", size=size)
        window._selection.update(
            window._target.expected_button,
            time.monotonic() * 1000,
            pause_ms=500,
            dwell_ms=500,
        )
        window.handle_eye_status(True, False)
        self.capture(
            window, "gaze-check-trial-interrupted", "Gaze check: cancelled selection", size=size
        )
        wrong = window._target.mapToGlobal(window._target.button_rect(0).center())
        screen = QGuiApplication.primaryScreen().geometry()
        gaze = (
            (wrong.x() - screen.left()) / (screen.width() - 1),
            (wrong.y() - screen.top()) / (screen.height() - 1),
        )
        start = time.monotonic()
        duration = (self.gaze_settings.selection_pause_ms + self.gaze_settings.dwell_ms) / 1000
        for sample in range(round(duration / 0.02) + 3):
            at = start + sample * 0.02
            window._trial_sample(CheckSnapshot(True, True, gaze=gaze, gaze_at=at), at)
        self.capture(window, "gaze-check-trial-wrong", "Gaze check: neighbor selected", size=size)
        window._finish_trial_target(True, time.monotonic())
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(
            window, "gaze-check-trial-keyboard", "Gaze check: keyboard-sized neighbors", size=size
        )
        window._finish_trial_target(True, time.monotonic())
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(
            window, "gaze-check-trial-words", "Gaze check: suggestion-sized neighbors", size=size
        )
        window._finish_trial_target(False, time.monotonic())
        for row in window._report.trials[-1].rows:
            row.state, row.coverage = "measured", 0.9
        window._render_report()
        self.capture(
            window, "gaze-check-trial-results", "Gaze check: trial needs adjustment", size=size
        )
        window._trial_results = [True] * 3
        window._trial_losses = window._trial_wrong_selections = 0
        for row in window._report.trials[-1].rows:
            row.selected = True
            row.wrong_selections = row.cancelled_selections = 0
        window._render_report()
        self.capture(
            window, "gaze-check-results-complete", "Gaze check: targets and trial passed", size=size
        )
        window._start_trial()
        for _ in range(3):
            window._finish_trial_target(False, time.monotonic())
        self.capture(
            window, "gaze-check-trial-no-gaze", "Gaze check: trial without gaze data", size=size
        )

    def _capture_free(self, window, size):
        window._start_free()
        screen = QGuiApplication.primaryScreen().geometry()
        point = window._target.mapToGlobal(window._target.rect().center() + QPoint(16, -10))
        window._snapshot = CheckSnapshot(
            True,
            True,
            gaze=(
                (point.x() - screen.left()) / (screen.width() - 1),
                (point.y() - screen.top()) / (screen.height() - 1),
            ),
            gaze_at=time.monotonic(),
        )
        window._render_free()
        self.capture(window, "gaze-check-free", "Gaze check: nine live targets", size=size)
        window._test_recording_badge.set_status(
            {"busy": True, "state": "recording", "remaining_seconds": 83}
        )
        self.capture(
            window, "gaze-check-free-recording", "Gaze check: recording in free view", size=size
        )
        window._test_recording_badge.set_status(None)
        window._snapshot = CheckSnapshot()
        window._render_free()
        self.capture(
            window, "gaze-check-free-waiting", "Gaze check: free check waiting for gaze", size=size
        )

    def _capture_reports(self, window, size):
        window._view_report = window._report
        window._render_report()
        window._result_tabs.setCurrentIndex(1)
        self.capture(
            window, "gaze-check-report-trials", "Gaze check: saved trial attempts", size=size
        )
        window._result_tabs.setCurrentIndex(2)
        self.capture(
            window, "gaze-check-report-context", "Gaze check: settings and environment", size=size
        )
        window._result_tabs.setCurrentIndex(0)
        window._reports.states[window._report.id] = "error"
        window._render_storage()
        self.capture(
            window, "gaze-check-save-error", "Gaze check: save failed, export available", size=size
        )
        window._reports.states[window._report.id] = "saving"
        window._render_storage()
        self.capture(window, "gaze-check-saving", "Gaze check: saving in background", size=size)
        window._reports.states[window._report.id] = "memory"
        window._render_storage()
        self.capture(window, "gaze-check-logging-off", "Gaze check: session-only result", size=size)
        window._export_token = "synthetic-export"
        window._export_finished("synthetic-export", False)
        self.capture(window, "gaze-check-export-error", "Gaze check: export failed", size=size)
        window._export_status.hide()
        window._start_precision()
        self.app.processEvents()
        window._test_back_button.click()
        self.capture(
            window, "gaze-check-result-interrupted", "Gaze check: interrupted precision", size=size
        )
        # Populate history from session fixtures without touching the developer's logs.
        window._reports.load = lambda: None
        window._open_history()
        self.capture(window, "gaze-check-history", "Gaze check: report history", size=size)
        window._open_selected_report()
        self.capture(
            window, "gaze-check-archived", "Gaze check: read-only archived report", size=size
        )
        window._reports.reports.clear()
        window._open_history()
        self.capture(window, "gaze-check-history-empty", "Gaze check: no stored reports", size=size)
        window._reports.history_error = True
        window._refresh_history()
        self.capture(
            window, "gaze-check-history-error", "Gaze check: history read error", size=size
        )
        window.reset_check()
