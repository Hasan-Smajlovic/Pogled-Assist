from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import static_checks

FAILING = ("first", static_checks.PYTHON, ("-c", "raise SystemExit(3)"))
PASSING = ("second", static_checks.PYTHON, ("-c", "print('second ran')"))
MISSING = ("third", "tool-that-is-not-installed", ())


def test_every_stage_runs_after_a_failure_and_failures_are_named(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    failed = static_checks.run_stages((FAILING, PASSING, MISSING), tmp_path)

    output = capfd.readouterr().out
    assert failed == ["first", "third"]
    assert "second ran" in output
    assert "Finished: first (FAILED with exit code 3" in output
    assert "Finished: second (passed" in output
    assert "tool-that-is-not-installed is not installed" in output


@pytest.mark.parametrize(("stages", "exit_code"), [((PASSING,), 0), ((PASSING, FAILING), 1)])
def test_main_fails_when_any_stage_fails(
    monkeypatch: pytest.MonkeyPatch, stages: tuple, exit_code: int
) -> None:
    monkeypatch.setattr(static_checks, "STAGES", stages)

    assert static_checks.main() == exit_code
