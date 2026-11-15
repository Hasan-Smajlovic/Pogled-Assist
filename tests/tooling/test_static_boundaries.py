from __future__ import annotations

import os
import shutil
import subprocess
from fnmatch import fnmatch
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


def _workflow(filename):
    return yaml.safe_load((ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8"))


def _uses(step, action):
    return step.get("uses", "").startswith(f"{action}@")


def test_baseline_comparison_has_history_and_a_trusted_event_base():
    # Pull requests compare with their base. Development pushes and the release verification,
    # which reuses these jobs for a master push, compare with the commit before the push.
    steps = _workflow("ci.yml")["jobs"]["code-quality"]["steps"]
    checkout = next(step for step in steps if _uses(step, "actions/checkout"))
    check = next(
        step for step in steps if step.get("run") == "python -B -m scripts.checks.static_checks"
    )
    assert checkout["with"]["fetch-depth"] == 0
    assert check["env"]["STATIC_CHECK_BASE_REF"] == (
        "${{ github.event.pull_request.base.sha || github.event.before || 'origin/development' }}"
    )


def test_release_publishes_only_the_package_verified_by_the_ci_jobs():
    ci = _workflow("ci.yml")
    release = _workflow("release.yml")
    verify = release["jobs"]["verify"]
    publish = release["jobs"]["release"]

    # The merged master commit passes the same read-only jobs as a pull request.
    assert verify["uses"] == "./.github/workflows/ci.yml"
    assert verify["permissions"] == {"contents": "read"}
    assert ci["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in ci["jobs"].values())
    assert ci[True]["workflow_call"]["outputs"]["artifact_name"]["value"] == (
        "${{ jobs.windows-package.outputs.artifact_name }}"
    )
    assert ci["jobs"]["windows-package"]["outputs"]["artifact_name"] == (
        "${{ steps.build.outputs.artifact_name }}"
    )

    # Only the publishing job holds a write token. It starts after verification and
    # publishes the package built and smoke-tested there, without building or testing.
    writers = [
        name
        for name, job in release["jobs"].items()
        if "write" in (job.get("permissions") or {}).values()
    ]
    assert writers == ["release"]
    assert publish["needs"] == "verify"
    download = next(step for step in publish["steps"] if _uses(step, "actions/download-artifact"))
    assert download["with"]["name"] == "${{ needs.verify.outputs.artifact_name }}"
    commands = "\n".join(step.get("run", "") for step in publish["steps"])
    assert "publish_github_release.ps1" in commands
    for verification in ("pip", "pytest", "static_checks", "build_windows_package"):
        assert verification not in commands


def test_ci_isolates_serial_ui_tests_and_enforces_combined_coverage():
    steps = _workflow("ci.yml")["jobs"]["tests"]["steps"]
    runs = [step for step in steps if "pytest" in step.get("run", "")]
    assert len(runs) == 2
    parallel, ui = runs
    # Excluding one directory from discovery and then running exactly that directory
    # keeps every test, including future directories, without executing any twice.
    assert "-n 4 --dist=loadfile --ignore=tests/ui" in parallel["run"]
    assert "--cov-fail-under=0" in parallel["run"]
    assert "--cov-report=" in parallel["run"]
    assert "--cov-append" not in parallel["run"]
    assert "-n 0 tests/ui" in ui["run"]
    assert "--cov-append" in ui["run"]
    assert "--cov-fail-under" not in ui["run"]  # Use the configured 60 percent floor.
    assert "--cov-report=xml:coverage.xml" in ui["run"]
    assert "POGLED_ASSIST_UI_GALLERY" in ui["env"]
    for step in runs:
        assert "--cov=pogled_assist" in step["run"]
        assert not step.get("continue-on-error", False)


def test_python_environment_is_restored_in_every_job_and_saved_only_from_development():
    ci = _workflow("ci.yml")
    assert ci[True]["push"]["branches"] == ["development"]
    restores = []
    saves = []
    for name, job in ci["jobs"].items():
        steps = job.get("steps", [])
        setup = next(
            (i for i, step in enumerate(steps) if _uses(step, "actions/setup-python")), None
        )
        if setup is None:
            continue
        # A setup-python pip cache would be saved separately for every pull request.
        assert "cache" not in steps[setup]["with"], name
        restore = next(i for i, step in enumerate(steps) if _uses(step, "actions/cache/restore"))
        assert restore < setup, name
        restores.append(steps[restore]["with"])
        saves += [
            (name, i, step) for i, step in enumerate(steps) if _uses(step, "actions/cache/save")
        ]

    assert len(restores) == 3
    assert all(item == restores[0] for item in restores)
    assert restores[0]["path"] == "${{ runner.tool_cache }}/Python/3.10.*"
    for requirements in ("requirements.txt", "requirements-dev.txt", "requirements-build.txt"):
        assert f"'{requirements}'" in restores[0]["key"]

    # Pull requests and the release only restore. One development job saves the pinned
    # installation before any repository code runs in that job.
    assert len(saves) == 1
    name, index, save = saves[0]
    steps = ci["jobs"][name]["steps"]
    assert "pip install" in steps[index - 1]["run"]
    assert all("run" not in step for step in steps[: index - 1])
    assert save["with"]["path"] == restores[0]["path"]
    assert "github.event_name == 'push'" in save["if"]
    assert "github.ref == 'refs/heads/development'" in save["if"]


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


def _pinned(requirements):
    return {
        line.split("==")[0].strip().lower().replace("_", "-")
        for line in (ROOT / requirements).read_text().splitlines()
        if "==" in line
    }


def test_dependabot_version_updates_cover_exactly_the_pinned_check_tools():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    pip = next(update for update in config["updates"] if update["package-ecosystem"] == "pip")
    patterns = [item["dependency-name"].lower() for item in pip["allow"]]
    tools = _pinned("requirements-dev.txt")
    runtime = _pinned("requirements.txt") | _pinned("requirements-build.txt")

    assert {name for name in tools if not any(fnmatch(name, p) for p in patterns)} == set()
    assert [p for p in patterns if not any(fnmatch(name, p) for name in tools)] == []
    # Runtime and packaging updates need a separate compatibility decision.
    assert {name for name in runtime if any(fnmatch(name, p) for p in patterns)} == set()
