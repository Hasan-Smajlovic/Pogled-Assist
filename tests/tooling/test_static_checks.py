from __future__ import annotations

import re
import tokenize
from pathlib import Path

import pytest

from scripts.checks import static_checks

FAILING = ("first", static_checks.PYTHON, ("-c", "raise SystemExit(3)"))
PASSING = ("second", static_checks.PYTHON, ("-c", "print('second ran')"))
MISSING = ("third", "tool-that-is-not-installed", ())
REPO_ROOT = Path(__file__).resolve().parents[2]
# Ruff rules may be switched off for a whole path only here. The model script is listed because
# the bundled speech model records its SHA-256, so a comment on the line would change that hash.
RUFF_PATH_EXCEPTIONS = {
    "tests/**",
    "scripts/**",
    "scripts/speech_suggestions/prepare_speech_model.py",
}
SUPPRESSION = re.compile(r"#\s*noqa", re.IGNORECASE)
EXPLAINED_SUPPRESSION = re.compile(r"# noqa: [A-Z]+[0-9]+(?:, [A-Z]+[0-9]+)* - \S")


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


def test_ruff_rules_are_switched_off_for_listed_paths_only() -> None:
    settings = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = settings.split("[tool.ruff.lint.per-file-ignores]\n")[1].split("\n[")[0]

    assert set(re.findall(r'^"([^"]+)" = ', section, flags=re.MULTILINE)) == RUFF_PATH_EXCEPTIONS


def test_every_suppressed_finding_names_its_rule_and_reason() -> None:
    sources = [REPO_ROOT / "run_gaze_mouse.py"]
    for folder in ("pogled_assist", "scripts", "tests"):
        sources.extend(sorted((REPO_ROOT / folder).rglob("*.py")))

    unexplained = []
    for source in sources:
        with tokenize.open(source) as stream:
            unexplained.extend(
                f"{source.relative_to(REPO_ROOT).as_posix()}:{token.start[0]}"
                for token in tokenize.generate_tokens(stream.readline)
                if token.type == tokenize.COMMENT
                and SUPPRESSION.search(token.string)
                and not EXPLAINED_SUPPRESSION.search(token.string)
            )

    assert unexplained == []
