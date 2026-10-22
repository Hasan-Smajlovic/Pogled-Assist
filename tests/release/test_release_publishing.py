from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _powershell import powershell_literal, run_powershell_cases

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Release publishing uses Windows PowerShell and command shims.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SCRIPT = REPO_ROOT / "scripts" / "release" / "publish_github_release.ps1"
VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
ARTIFACT_NAME = f"PogledAssist-v{VERSION}-windows-x64.zip"
COMMIT_SHA = "a" * 40
OTHER_COMMIT_SHA = "b" * 40

FAKE_CLI = r"""from __future__ import annotations

import json
import os
import sys
from pathlib import Path


state_path = Path(os.environ["FAKE_CLI_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
tool = sys.argv[1]
arguments = sys.argv[2:]
state.setdefault("calls", []).append([tool, *arguments])


def finish(code: int = 0, output: object | None = None) -> int:
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if output is not None:
        print(output)
    return code


def release_json() -> str:
    release = state["release"]
    payload = {
        "isDraft": release["isDraft"],
        "targetCommitish": release["targetCommitish"],
        "assets": [{"name": name} for name in release["assets"]],
    }
    return json.dumps(payload, separators=(",", ":"))


if tool == "git":
    tag_sha = state.get("tag_sha")
    if tag_sha:
        print(f"{tag_sha}\t{arguments[-2]}")
    raise SystemExit(finish())

if arguments[:2] == ["release", "view"]:
    if state.get("release") is None:
        print("release not found", file=sys.stderr)
        raise SystemExit(finish(1))
    raise SystemExit(finish(output=release_json()))

if arguments[:2] == ["release", "create"]:
    target = state.get("tag_sha")
    if "--target" in arguments:
        target = arguments[arguments.index("--target") + 1]
    state["release"] = {
        "isDraft": True,
        "targetCommitish": target,
        "assets": [Path(arguments[3]).name, Path(arguments[4]).name],
    }
    raise SystemExit(finish())

if arguments[:2] == ["release", "upload"]:
    release = state["release"]
    release["assets"] = sorted(
        set(release["assets"] + [Path(arguments[3]).name, Path(arguments[4]).name])
    )
    raise SystemExit(finish())

if arguments[:2] == ["release", "edit"]:
    release = state["release"]
    release["isDraft"] = False
    if state.get("tag_sha") is None:
        state["tag_sha"] = release["targetCommitish"]
    raise SystemExit(finish())

raise SystemExit(finish(2, f"Unsupported fake command: {tool} {' '.join(arguments)}"))
"""


def _run_publish(tmp_path: Path, initial_state: dict[str, object]):
    artifact_path = tmp_path / "release artifacts" / ARTIFACT_NAME
    artifact_path.parent.mkdir()
    artifact_path.write_bytes(b"release artifact")

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(initial_state), encoding="utf-8")
    fake_cli_path = tmp_path / "fake_cli.py"
    fake_cli_path.write_text(FAKE_CLI, encoding="utf-8")

    python_path = Path(sys.executable).resolve()
    for command in ("git", "gh"):
        command_path = tmp_path / f"{command}.cmd"
        command_path.write_text(
            f'@echo off\n"{python_path}" "%~dp0fake_cli.py" {command} %*\nexit /b %errorlevel%\n',
            encoding="utf-8",
        )

    environment = os.environ.copy()
    # Let Windows PowerShell build its module path instead of inheriting PowerShell 7 modules.
    environment.pop("PSMODULEPATH", None)
    environment["FAKE_CLI_STATE"] = str(state_path)
    environment["PATH"] = str(tmp_path) + os.pathsep + environment["PATH"]
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PUBLISH_SCRIPT),
            "-ArtifactPath",
            str(artifact_path),
            "-Repository",
            "owner/repository",
            "-CommitSha",
            COMMIT_SHA,
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return completed, state


@pytest.fixture(scope="module")
def rejected_releases(tmp_path_factory):
    root = tmp_path_factory.mktemp("release-rejections")
    states = {
        "incomplete": {
            "tag_sha": COMMIT_SHA,
            "release": _release_state(draft=False, assets=[ARTIFACT_NAME]),
            "calls": [],
        },
        "draft": {
            "tag_sha": None,
            "release": {"isDraft": True, "targetCommitish": OTHER_COMMIT_SHA, "assets": []},
            "calls": [],
        },
        "tag": {"tag_sha": OTHER_COMMIT_SHA, "release": None, "calls": []},
    }
    cases = {}
    for name, state in states.items():
        directory = root / name
        directory.mkdir()
        artifact = directory / ARTIFACT_NAME
        artifact.write_bytes(b"release artifact")
        state_path = directory / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        cases[name] = {"body": _rejection_body(state_path, artifact), "cwd": directory}
    results = run_powershell_cases(root, cases)
    return {
        name: (results[name], json.loads((root / name / "state.json").read_text("utf-8-sig")))
        for name in states
    }


def _rejection_body(state_path, artifact):
    return (
        r"""
$statePath = STATE_PATH
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
function git {
    $state.calls += ,(@("git") + @($args))
    $global:LASTEXITCODE = 0
    if ($state.tag_sha) { "$($state.tag_sha)`t$($args[-2])" }
}
function gh {
    $state.calls += ,(@("gh") + @($args))
    if ($args[0] -ne "release" -or $args[1] -ne "view") {
        throw "A rejected release attempted a mutation"
    }
    $global:LASTEXITCODE = 0
    @{
        isDraft = $state.release.isDraft
        targetCommitish = $state.release.targetCommitish
        assets = @($state.release.assets | ForEach-Object { @{ name = $_ } })
    } | ConvertTo-Json -Depth 5 -Compress
}
try {
    & PUBLISH_SCRIPT -ArtifactPath ARTIFACT_PATH -Repository "owner/repository" -CommitSha COMMIT_SHA
} finally {
    $state | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath $statePath -Encoding UTF8
}
""".replace("STATE_PATH", powershell_literal(state_path))
        .replace("PUBLISH_SCRIPT", powershell_literal(PUBLISH_SCRIPT))
        .replace("ARTIFACT_PATH", powershell_literal(artifact))
        .replace("COMMIT_SHA", powershell_literal(COMMIT_SHA))
    )


def _release_state(*, draft: bool, assets: list[str]) -> dict[str, object]:
    return {
        "isDraft": draft,
        "targetCommitish": COMMIT_SHA,
        "assets": assets,
    }


def _gh_mutations(state: dict[str, object]) -> list[list[str]]:
    return [
        call
        for call in state["calls"]
        if call[0] == "gh" and call[2] in {"create", "upload", "edit"}
    ]


def test_publish_creates_draft_with_assets_then_publishes_it(tmp_path):
    completed, state = _run_publish(
        tmp_path,
        {"tag_sha": None, "release": None, "calls": []},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert state["tag_sha"] == COMMIT_SHA
    assert state["release"] == _release_state(
        draft=False,
        assets=[ARTIFACT_NAME, f"{ARTIFACT_NAME}.sha256"],
    )
    mutations = _gh_mutations(state)
    assert [call[2] for call in mutations] == ["create", "edit"]
    create, edit = mutations
    assert create[create.index("--target") + 1] == COMMIT_SHA
    assert "--draft" in create and "--draft=false" in edit
    assert create[4:6] == [
        str(tmp_path / "release artifacts" / ARTIFACT_NAME),
        str(tmp_path / "release artifacts" / f"{ARTIFACT_NAME}.sha256"),
    ]


def test_publish_leaves_complete_public_release_unchanged(tmp_path):
    completed, state = _run_publish(
        tmp_path,
        {
            "tag_sha": COMMIT_SHA,
            "release": _release_state(
                draft=False,
                assets=[ARTIFACT_NAME, f"{ARTIFACT_NAME}.sha256"],
            ),
            "calls": [],
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _gh_mutations(state) == []


def test_publish_does_not_modify_incomplete_public_release(rejected_releases):
    completed, state = rejected_releases["incomplete"]

    assert completed.returncode != 0
    assert "missing required asset" in completed.stdout + completed.stderr
    assert _gh_mutations(state) == []


def test_publish_repairs_matching_draft_before_publication(tmp_path):
    completed, state = _run_publish(
        tmp_path,
        {
            "tag_sha": None,
            "release": _release_state(draft=True, assets=[]),
            "calls": [],
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert state["tag_sha"] == COMMIT_SHA
    assert state["release"] == _release_state(
        draft=False,
        assets=[ARTIFACT_NAME, f"{ARTIFACT_NAME}.sha256"],
    )
    mutations = _gh_mutations(state)
    assert [call[2] for call in mutations] == ["upload", "edit"]
    assert "--clobber" in mutations[0]


def test_publish_rejects_draft_for_another_commit(rejected_releases):
    completed, state = rejected_releases["draft"]

    assert completed.returncode != 0
    assert "Draft release" in completed.stdout + completed.stderr
    assert _gh_mutations(state) == []


def test_publish_rejects_version_tag_from_another_commit(rejected_releases):
    completed, state = rejected_releases["tag"]

    assert completed.returncode != 0
    assert "Immutable tag" in completed.stdout + completed.stderr
    assert not any(call[0] == "gh" for call in state["calls"])
