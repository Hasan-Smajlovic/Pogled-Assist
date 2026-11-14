from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from scripts.checks import check_type_baseline as baseline

FINDING = {
    "code": "reportReturnType",
    "range": {"startColumn": 11, "endColumn": 16, "lineCount": 1},
}


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()


def _write(root, findings, path="./probe.py"):
    target = root / baseline.BASELINE
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps({"files": {path: findings}}), encoding="utf-8")


def _commit(root):
    _git(root, "add", ".")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "test snapshot")


@pytest.fixture
def baseline_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Baseline Test")
    _git(tmp_path, "config", "user.email", "baseline@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _write(tmp_path, [FINDING])
    _commit(tmp_path)
    _git(tmp_path, "branch", "base")
    return tmp_path


@pytest.mark.parametrize("findings", [[], [FINDING]])
def test_equal_or_reduced_inventory_passes(baseline_repo, findings):
    _write(baseline_repo, findings)

    assert baseline.check(baseline_repo, "base") == []


@pytest.mark.parametrize(
    ("findings", "path"),
    [
        ([FINDING, FINDING], "./probe.py"),
        ([dict(FINDING, code="reportArgumentType")], "./probe.py"),
        ([FINDING], "./other.py"),
        ([dict(FINDING, range=dict(FINDING["range"], endColumn=17))], "./probe.py"),
    ],
)
@pytest.mark.parametrize("committed", [False, True])
def test_added_or_replaced_entries_fail_even_with_equal_total(
    baseline_repo, findings, path, committed
):
    _write(baseline_repo, findings, path)
    if committed:
        _commit(baseline_repo)

    assert baseline.check(baseline_repo, "base")


def test_invalid_base_fails_closed(baseline_repo, monkeypatch, capsys):
    monkeypatch.setattr(baseline, "ROOT", baseline_repo)

    assert baseline.main(["--base-ref", "missing-base"]) == 1
    assert "Cannot verify type baseline" in capsys.readouterr().out


def test_shallow_history_is_rejected(baseline_repo, monkeypatch, capsys):
    (baseline_repo / ".git" / "shallow").write_text(
        _git(baseline_repo, "rev-parse", "HEAD") + "\n", encoding="ascii"
    )
    assert _git(baseline_repo, "rev-parse", "--is-shallow-repository") == "true"
    monkeypatch.setattr(baseline, "ROOT", baseline_repo)

    assert baseline.main(["--base-ref", "HEAD"]) == 1
    assert "full Git history" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["{}", "not json", '{"files":{"./probe.py":[{}]}}'])
def test_invalid_inventory_fails_closed(baseline_repo, monkeypatch, content):
    (baseline_repo / baseline.BASELINE).write_text(content, encoding="utf-8")
    monkeypatch.setattr(baseline, "ROOT", baseline_repo)

    assert baseline.main(["--base-ref", "base"]) == 1


def test_adoption_uses_pinned_inventory_not_the_topic_branch_version(baseline_repo, monkeypatch):
    pinned = _git(baseline_repo, "rev-parse", f"HEAD:{baseline.BASELINE}")
    monkeypatch.setattr(baseline, "ADOPTION_BASELINE_BLOB", pinned)
    _git(baseline_repo, "rm", baseline.BASELINE)
    _commit(baseline_repo)
    _git(baseline_repo, "branch", "-f", "base", "HEAD")
    _write(baseline_repo, [FINDING])
    assert baseline.check(baseline_repo, "base") == []
    _write(baseline_repo, [FINDING, FINDING])
    _commit(baseline_repo)

    assert baseline.check(baseline_repo, "base")


def test_missing_adoption_object_fails_closed(baseline_repo, monkeypatch):
    _git(baseline_repo, "rm", baseline.BASELINE)
    _commit(baseline_repo)
    _git(baseline_repo, "branch", "-f", "base", "HEAD")
    _write(baseline_repo, [FINDING])
    monkeypatch.setattr(baseline, "ROOT", baseline_repo)
    monkeypatch.setattr(baseline, "ADOPTION_BASELINE_BLOB", "0" * 40)

    assert baseline.main(["--base-ref", "base"]) == 1


@pytest.mark.parametrize(
    "incorrect_source",
    [
        'def identity(value: int) -> int:\n    return "bad"\n',
        "def identity(value) -> int:\n    return value\n",
    ],
)
def test_regenerated_baseline_cannot_hide_a_real_new_type_error(baseline_repo, incorrect_source):
    root = baseline_repo
    (root / "pyproject.toml").write_text(
        '[tool.basedpyright]\ninclude = ["probe.py"]\npythonVersion = "3.10"\n'
        'typeCheckingMode = "standard"\nreportMissingParameterType = "error"\n',
        encoding="utf-8",
    )
    source = root / "probe.py"
    source.write_text("def identity(value: int) -> int:\n    return value\n", encoding="utf-8")
    _write(root, [])
    _commit(root)
    _git(root, "branch", "-f", "base", "HEAD")
    command = [sys.executable, "-m", "basedpyright", "--pythonpath", sys.executable]
    environment = dict(os.environ, CI="true")

    def run(*options, ci=True):
        env = (
            environment if ci else {key: value for key, value in environment.items() if key != "CI"}
        )
        return subprocess.run(
            [*command, *options],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    assert run().returncode == 0
    source.write_text(incorrect_source, encoding="utf-8")
    assert run().returncode == 1
    run("--writebaseline", ci=False)
    assert run().returncode == 0
    _commit(root)
    assert baseline.check(root, "base")
