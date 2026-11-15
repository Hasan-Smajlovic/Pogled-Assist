from __future__ import annotations

import json
import os
import shutil
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


@pytest.fixture(scope="module")
def baseline_history(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline-history")
    _git(root, "init")
    _git(root, "config", "user.name", "Baseline Test")
    _git(root, "config", "user.email", "baseline@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, [FINDING])
    _commit(root)
    _git(root, "branch", "base")
    return root


@pytest.fixture
def baseline_repo(baseline_history, tmp_path):
    shutil.copytree(baseline_history, tmp_path, dirs_exist_ok=True)
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
    output = capsys.readouterr().out
    assert "Cannot verify type baseline" in output
    assert "Fetch missing-base with full history" in output


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


MOVED = dict(FINDING, range=dict(FINDING["range"], startColumn=12, endColumn=17))


def _declare(root, name):
    script = root / baseline.SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'"""Checker."""\n\nREVIEWED_INVENTORY = "{name}"\n', encoding="utf-8")


@pytest.fixture
def unadopted_repo(baseline_repo):
    _git(baseline_repo, "rm", "-q", baseline.BASELINE)
    _commit(baseline_repo)
    _git(baseline_repo, "branch", "-f", "base", "HEAD")
    return baseline_repo


def test_base_without_inventory_needs_a_declaration(unadopted_repo, monkeypatch, capsys):
    _write(unadopted_repo, [FINDING])
    _commit(unadopted_repo)
    monkeypatch.setattr(baseline, "ROOT", unadopted_repo)

    assert baseline.main(["--base-ref", "base"]) == 1
    assert "declares a reviewed inventory" in capsys.readouterr().out


def test_adoption_inventory_survives_a_squash_and_later_reductions(unadopted_repo):
    # One commit with the declaration and the baseline is what a squash merge leaves behind.
    _declare(unadopted_repo, "adoption")
    _write(unadopted_repo, [FINDING, MOVED])
    _commit(unadopted_repo)
    _write(unadopted_repo, [FINDING])
    _commit(unadopted_repo)
    assert baseline.check(unadopted_repo, "base") == []

    _write(unadopted_repo, [FINDING, FINDING])
    _commit(unadopted_repo)

    assert baseline.check(unadopted_repo, "base")


def test_tool_migration_replaces_the_inventory_only_in_its_own_commit(baseline_repo):
    _declare(baseline_repo, "migration")
    _commit(baseline_repo)
    _write(baseline_repo, [MOVED])
    _commit(baseline_repo)
    assert baseline.check(baseline_repo, "base")

    _declare(baseline_repo, "migration with the regenerated baseline")
    _commit(baseline_repo)
    assert baseline.check(baseline_repo, "base") == []

    _git(baseline_repo, "branch", "-f", "base", "HEAD")
    _write(baseline_repo, [MOVED, MOVED])
    _commit(baseline_repo)

    assert baseline.check(baseline_repo, "base")


def test_uncommitted_declaration_covers_the_working_tree(baseline_repo):
    _write(baseline_repo, [MOVED])
    assert baseline.check(baseline_repo, "base")

    _declare(baseline_repo, "migration")
    assert baseline.check(baseline_repo, "base") == []
    _commit(baseline_repo)

    assert baseline.check(baseline_repo, "base") == []


def test_repository_declares_its_reviewed_inventory_once():
    source = (baseline.ROOT / baseline.SCRIPT).read_text(encoding="utf-8")

    assert len(baseline.DECLARATION.findall(source)) == 1


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
