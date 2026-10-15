from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/sync-hotfix.yml"
REPOSITORY = "Hasan-Smajlovic/Pogled-Assist"


def run_workflow(tmp_path, monkeypatch, *, existing=(), ahead=1, changes=None):
    pull = {
        "number": 42,
        "merged": True,
        "base": {"ref": "master"},
        "head": {"ref": "hotfix/42-speech", "repo": {"full_name": REPOSITORY}},
    }
    if changes:
        changes(pull)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": pull}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    calls = []

    def gh(command, *, input, text, capture_output, check):
        assert command[:2] == ["gh", "api"] and check and capture_output and text
        path = command[2].removeprefix(f"repos/{REPOSITORY}/")
        payload = json.loads(input) if input else None
        calls.append((path, payload))
        if path.startswith("pulls?"):
            result = list(existing)
        elif path == "compare/development...master":
            result = {"ahead_by": ahead}
        else:
            assert command[3:] == ["--method", "POST", "--input", "-"]
            result = {"html_url": "https://github.com/example/pull/43"}
        return SimpleNamespace(stdout=json.dumps(result))

    monkeypatch.setattr(subprocess, "run", gh)
    source = (
        WORKFLOW.read_text(encoding="utf-8")
        .split("python3 - <<'PY'\n", 1)[1]
        .rsplit("          PY", 1)[0]
    )
    exec(compile(textwrap.dedent(source), str(WORKFLOW), "exec"), {})
    return calls, summary.read_text(encoding="utf-8")


def test_merged_hotfix_opens_master_to_development_for_manual_merge(tmp_path, monkeypatch):
    calls, summary = run_workflow(tmp_path, monkeypatch)
    path, payload = calls[-1]
    assert path == "pulls"
    assert payload["head"] == "master" and payload["base"] == "development"
    assert "#42" in payload["body"] and "manually" in payload["body"]
    assert "pull/43" in summary
    assert all("merge" not in path for path, _ in calls)


def test_repeated_hotfix_reuses_open_sync_pr(tmp_path, monkeypatch):
    calls, summary = run_workflow(
        tmp_path, monkeypatch, existing=[{"html_url": "https://github.com/example/pull/7"}]
    )
    assert len(calls) == 1 and "pull/7" in summary


def test_already_synced_master_does_not_open_empty_pr(tmp_path, monkeypatch):
    calls, summary = run_workflow(tmp_path, monkeypatch, ahead=0)
    assert len(calls) == 2 and "No PR needed" in summary


@pytest.mark.parametrize(
    "changes",
    [
        lambda pull: pull.update(merged=False),
        lambda pull: pull["head"].update(ref="feat/42-speech"),
        lambda pull: pull["base"].update(ref="development"),
        lambda pull: pull["head"]["repo"].update(full_name="fork/repo"),
    ],
)
def test_unmerged_unrelated_and_fork_changes_cannot_open_sync_pr(tmp_path, monkeypatch, changes):
    with pytest.raises(SystemExit, match="Only a merged"):
        run_workflow(tmp_path, monkeypatch, changes=changes)


def test_hotfix_job_has_no_checkout_or_auto_merge():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in workflow and "uses:" not in workflow
    assert "contents: write" not in workflow
    assert "pull-requests: write" in workflow
    assert "gh pr merge" not in workflow
