from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.checks import check_policy

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


@pytest.fixture
def policy_repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "pogled_assist").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "change",
    [
        lambda config: config.replace(
            "[tool.ruff.lint.per-file-ignores]\n",
            "[tool.ruff.lint.per-file-ignores]\n'pogled_assist/probe.py' = [\"ALL\"]\n",
        ),
        lambda config: (
            config
            + '\n[tool.ruff.lint.extend-per-file-ignores]\n"pogled_assist/probe.py" = ["ALL"]\n'
        ),
        lambda config: config.replace(
            '"scripts/speech_suggestions/prepare_speech_model.py" = ["S324"]',
            '"scripts/speech_suggestions/prepare_speech_model.py" = ["ALL"]',
        ),
        lambda config: config.replace('"scripts/**" = ["T20"]', '"scripts/**" = ["T20", "S"]'),
        lambda config: config.replace('    "S101",', '    "ALL",'),
        lambda config: config.replace("[tool.ruff]\n", '[tool.ruff]\nextend = "other.toml"\n'),
        lambda config: config.replace(
            "[tool.ruff.lint]\n", '[tool.ruff.lint]\nextend-ignore = ["S"]\n'
        ),
    ],
)
def test_configuration_rejects_unapproved_exceptions(policy_repo, change):
    (policy_repo / "pyproject.toml").write_text(change(CONFIG), encoding="utf-8")

    assert check_policy.check(policy_repo)


def test_toml_formatting_and_removing_exceptions_are_allowed(policy_repo):
    config = CONFIG.replace('"scripts/**" = ["T20"]', "'scripts/**'=['T20']")
    config = config.replace('"S324"', "").replace('"S101",', "")
    (policy_repo / "pyproject.toml").write_text(config, encoding="utf-8")

    assert check_policy.check(policy_repo) == []


@pytest.mark.parametrize(
    "path", ["ruff.toml", ".ruff.toml", "pogled_assist/ruff.toml", "pogled_assist/pyproject.toml"]
)
def test_alternate_configuration_is_rejected(policy_repo, path):
    (policy_repo / path).write_text('[lint]\nignore = ["ALL"]\n', encoding="utf-8")

    assert any(path in error for error in check_policy.check(policy_repo))


@pytest.mark.parametrize(
    ("comment", "allowed"),
    [
        ("# noqa", False),
        ("# noqa: F401", False),
        ("# noqa: F401 - ", False),
        ("# noqa: F401, S101 - documented boundary", True),
        ("# ruff: noqa: F401", False),
        ("#ruff:noqa: F401 - a reason still cannot exempt a whole file", False),
        ("# flake8: noqa", False),
        ("# ruff: ignore[F401]", False),
        ("# ruff: file-ignore[F401]", False),
        ("# ruff: disable[F401]", False),
        ("# ruff: enable[F401]", False),
        ("# isort: skip_file", False),
        ("# isort: off", False),
        ("# normal comment", True),
    ],
)
def test_suppression_policy_checks_actual_comment_tokens(policy_repo, comment, allowed):
    source = policy_repo / "pogled_assist" / "probe.py"
    source.write_text(f"import math  {comment}\n", encoding="utf-8")

    assert (check_policy.check(policy_repo) == []) is allowed


def test_suppression_examples_in_strings_are_not_directives(policy_repo):
    (policy_repo / "pogled_assist" / "probe.py").write_text(
        'EXAMPLE = "# ruff: noqa: F401"\n', encoding="utf-8"
    )

    assert check_policy.check(policy_repo) == []


def test_cli_rejects_a_file_suppression_that_ruff_accepts(policy_repo):
    source = policy_repo / "pogled_assist" / "probe.py"
    source.write_text("# ruff: noqa: F401\nimport math\n", encoding="utf-8")
    script = policy_repo / "scripts" / "checks" / "check_policy.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "checks" / "check_policy.py", script)
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(source)],
        cwd=policy_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    policy = subprocess.run(
        [sys.executable, "-B", "-m", "scripts.checks.check_policy"],
        cwd=policy_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    assert policy.returncode == 1, policy.stdout + policy.stderr
    assert "pogled_assist/probe.py:1" in policy.stdout
