from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

from scripts.checks import static_checks

ROOT = Path(__file__).resolve().parents[2]


def _stage(name, root):
    _name, launcher, arguments = next(stage for stage in static_checks.STAGES if stage[0] == name)
    command = static_checks._command(launcher, arguments)
    assert command is not None, f"Missing installed check tool: {launcher}"
    return subprocess.run(
        command,
        cwd=root,
        env=dict(os.environ, PYTHONPATH=str(root)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def test_import_contracts_accept_runtime_and_reject_boundary_crossings(tmp_path):
    shutil.copy2(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(
        ROOT / "pogled_assist",
        tmp_path / "pogled_assist",
        ignore=shutil.ignore_patterns("__pycache__", "assets"),
    )
    valid = _stage("Import contracts", tmp_path)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    for package, statement in (
        ("windows", "import pogled_assist.ui\n"),
        ("ui", "import edge_tts\n"),
    ):
        probe = tmp_path / "pogled_assist" / package / "guard_probe.py"
        try:
            probe.write_text(statement, encoding="utf-8")
            invalid = _stage("Import contracts", tmp_path)
            assert invalid.returncode != 0
            assert "BROKEN" in invalid.stdout
            assert f"pogled_assist.{package}.guard_probe" in invalid.stdout
        finally:
            probe.unlink()


def test_workflow_security_rejects_unpinned_actions(tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "probe.yml"
    workflow.parent.mkdir(parents=True)
    shutil.copy2(ROOT / ".github" / "zizmor.yml", tmp_path / ".github" / "zizmor.yml")
    contents = """name: Probe
on: pull_request
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
        with:
          persist-credentials: false
"""
    workflow.write_text(contents, encoding="utf-8")
    valid = _stage("Workflow security", tmp_path)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    workflow.write_text(
        contents.replace("fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", "v5"), encoding="utf-8"
    )
    invalid = _stage("Workflow security", tmp_path)
    assert invalid.returncode != 0
    assert "unpinned-uses" in invalid.stdout + invalid.stderr


def test_baseline_comparison_has_history_and_a_trusted_event_base():
    for filename, job, expected in (
        (
            "ci.yml",
            "code-quality",
            "${{ github.event.pull_request.base.sha || 'origin/development' }}",
        ),
        ("release.yml", "release", "${{ github.event.before }}"),
    ):
        config = yaml.safe_load((ROOT / ".github" / "workflows" / filename).read_text())
        steps = config["jobs"][job]["steps"]
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        check = next(
            step for step in steps if step.get("run") == "python -B -m scripts.checks.static_checks"
        )
        assert checkout["with"]["fetch-depth"] == 0
        assert check["env"]["STATIC_CHECK_BASE_REF"] == expected


def test_required_job_names_stay_stable_and_workflow_job_names_are_unique():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    for required in ("code-quality", "tests", "windows-package"):
        assert ci["jobs"][required]["name"] == required
    names = [
        job.get("name", key)
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml")
        for key, job in yaml.safe_load(workflow.read_text())["jobs"].items()
    ]
    assert len(names) == len(set(names))


def test_dependabot_version_updates_cover_only_approved_python_tools():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    pip = next(update for update in config["updates"] if update["package-ecosystem"] == "pip")
    assert {item["dependency-name"] for item in pip["allow"]} == {
        "basedpyright",
        "import-linter",
        "pytest*",
        "PyYAML",
        "ruff",
        "tomli",
        "zizmor",
    }
