"""Attempt lifecycle and aggregate results, independent of Qt widgets."""

import time

from .. import diagnostics
from .gaze_check import EyeTrackingResult
from .gaze_check_report import (
    ENVIRONMENT_KEYS,
    SETTING_KEYS,
    EyeTrackingSummary,
    GazeCheckReport,
    PrecisionRow,
    TrialAttempt,
    identity,
    timestamp,
)


class GazeCheckSession:
    def __init__(self, settings, targets, *, simulated: bool = False) -> None:
        self.settings = {key: getattr(settings, key, None) for key in SETTING_KEYS}
        self.targets = targets
        self.simulated = simulated
        self.report: GazeCheckReport | None = None
        self.environment: dict = {}
        self.attempt_id: str | None = None
        self._started_at = ""
        self._started_mono = 0.0

    def begin(self) -> None:
        self.attempt_id = identity()
        self._started_at = timestamp()
        self._started_mono = time.monotonic()

    def set_environment(self, environment: dict) -> None:
        self.environment = {
            key: value for key, value in environment.items() if key in ENVIRONMENT_KEYS
        }

    def _finish_attempt(self, reason: str | None = None) -> dict:
        if self.attempt_id is None:
            raise RuntimeError("The attempt has already finished.")
        attempt_id, self.attempt_id = self.attempt_id, None
        return {
            "id": attempt_id,
            "started_at": self._started_at,
            "ended_at": timestamp(),
            "duration_seconds": max(0, time.monotonic() - self._started_mono),
            "state": "interrupted" if reason else "completed",
            "reason": reason,
        }

    def finish_precision(
        self, measurement, eyes: EyeTrackingSummary | None, reason: str | None = None
    ) -> GazeCheckReport:
        targets = measurement.targets if measurement is not None else self.targets
        results = measurement.results if measurement is not None else []
        rows = [PrecisionRow(name, (x, y)) for name, x, y in targets]
        for index, result in enumerate(results):
            rows[index] = PrecisionRow(
                result.name,
                rows[index].target_normalized,
                "insufficient" if result.near is None else "measured",
                result.samples,
                result.coverage,
                result.median_error,
                result.spread,
                result.near,
                result.gaze_center,
            )
        self.report = GazeCheckReport(
            **self._finish_attempt(reason),
            simulated=self.simulated,
            settings=self.settings.copy(),
            environment=self.environment.copy(),
            precision=rows,
            precision_eyes=eyes,
        )
        observe_fixations(results)
        return self.report

    def finish_trial(
        self, rows, *, word: str, eyes: EyeTrackingSummary | None, reason: str | None = None
    ) -> GazeCheckReport:
        attempt = self._finish_attempt(reason)
        if self.report is None:
            self.report = GazeCheckReport(
                identity(),
                self._started_at,
                attempt["ended_at"],
                0,
                "interrupted",
                "Preciznost nije pokrenuta",
                self.simulated,
                self.settings.copy(),
                self.environment.copy(),
                [PrecisionRow(name, (x, y)) for name, x, y in self.targets],
            )
        self.report.trials.append(
            TrialAttempt(
                **attempt,
                rows=list(rows),
                environment=self.environment.copy(),
                word=word,
                eyes=eyes,
            )
        )
        return self.report


def finish_eye_run(run, stage: str, policy: str) -> EyeTrackingSummary | None:
    if run is None:
        return None
    result = run.result(time.monotonic())
    diagnostics.emit(
        "gaze_check_eye_tracking",
        priority=True,
        stage=stage,
        observed_seconds=round(result.observed_seconds, 3),
        left_fraction=round(result.left, 4),
        right_fraction=round(result.right, 4),
        both_fraction=round(result.both, 4),
        interruptions=result.interruptions,
        longest_interruption_seconds=round(result.longest_interruption, 3),
        agreement_supported=result.agreement_supported,
        agreement_samples=result.agreement_samples,
        median_separation_px=result.median_separation,
        agreement_fraction=result.agreement_fraction,
        agreement_threshold_px=result.threshold,
        eye_tracking_policy=policy,
    )
    return eye_summary(result)


def eye_summary(result: EyeTrackingResult) -> EyeTrackingSummary:
    return EyeTrackingSummary(
        result.observed_seconds,
        result.left,
        result.right,
        result.both,
        result.interruptions,
        result.longest_interruption,
        result.agreement_supported,
        result.agreement_samples,
        result.agreement_fraction,
        result.median_separation,
    )


def observe_fixations(results) -> None:
    if diagnostics.tracing():
        for index, result in enumerate(results):
            diagnostics.emit(
                "fixation_result",
                trace=True,
                priority=True,
                target_index=index,
                samples=result.samples,
                coverage=result.coverage,
                median_error_logical_px=result.median_error,
                spread_logical_px=result.spread,
                near=result.near,
                gaze_center_normalized=result.gaze_center,
            )
