from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import check_policy, static_checks

FAILING = ("first", static_checks.PYTHON, ("-c", "raise SystemExit(3)"))
PASSING = ("second", static_checks.PYTHON, ("-c", "print('second ran')"))
MISSING = ("third", "tool-that-is-not-installed", ())
REPO_ROOT = Path(__file__).resolve().parents[2]


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

    assert static_checks.main([]) == exit_code


def test_repository_check_exceptions_follow_the_policy() -> None:
    assert check_policy.check(REPO_ROOT) == []


@pytest.mark.parametrize("base", ["base", "a" * 40])
def test_shared_runner_invokes_policy_and_passes_comparison_ref(monkeypatch, base):
    seen = []
    monkeypatch.setattr(
        static_checks, "run_stages", lambda stages, _root: seen.extend(stages) or []
    )
    assert static_checks.main(["--base-ref", base]) == 0
    commands = {name: arguments for name, _launcher, arguments in seen}
    assert commands["Exception policy"] == ("-m", "scripts.checks.check_policy")
    assert commands["Type baseline"] == (
        "-m",
        "scripts.checks.check_type_baseline",
        "--base-ref",
        base,
    )


@pytest.mark.parametrize(
    ("environment", "expected"), [("ci-base", "ci-base"), ("", "origin/development")]
)
def test_shared_runner_uses_ci_comparison_ref(monkeypatch, environment, expected):
    seen = []
    monkeypatch.setenv("STATIC_CHECK_BASE_REF", environment)
    monkeypatch.setattr(
        static_checks, "run_stages", lambda stages, _root: seen.extend(stages) or []
    )
    assert static_checks.main([]) == 0
    assert next(args for name, _, args in seen if name == "Type baseline")[-1] == expected
