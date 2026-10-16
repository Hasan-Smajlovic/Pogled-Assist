from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/sync-hotfix.yml"
REPOSITORY = "Hasan-Smajlovic/Pogled-Assist"


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    return lambda **options: HotfixRun(tmp_path, monkeypatch, options).execute()


class HotfixRun:
    def __init__(self, tmp_path, monkeypatch, options):
        self.tmp_path, self.monkeypatch, self.options = tmp_path, monkeypatch, options
        self.calls = []

    def execute(self):
        pull = {"number": 42, "merged": True, "merge_commit_sha": "a" * 40,
                "base": {"ref": "master"}, "head": {"ref": "hotfix/42-speech", "repo": {"full_name": REPOSITORY}}}
        if changes := self.options.get("changes"):
            changes(pull)
        event = self.tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": pull}), encoding="utf-8")
        summary = self.tmp_path / "summary.md"
        environment = {"GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": REPOSITORY,
                       "GITHUB_STEP_SUMMARY": str(summary), "GH_TOKEN": "synthetic-token"}
        for name, value in environment.items():
            self.monkeypatch.setenv(name, value)
        self.monkeypatch.setattr(subprocess, "run", self.command)
        source = WORKFLOW.read_text(encoding="utf-8").split("python3 - <<'PY'\n", 1)[1].rsplit("          PY", 1)[0]
        exec(compile(textwrap.dedent(source), str(WORKFLOW), "exec"), {})
        return self.calls, summary.read_text(encoding="utf-8")

    def command(self, args, **kwargs):
        assert kwargs["check"] and kwargs["capture_output"] and kwargs["text"]
        self.calls.append((args, kwargs))
        if args[0] == "git":
            return git_result(args, self.options)
        return self.api_result(args)

    def api_result(self, args):
        path = args[2].removeprefix(f"repos/{REPOSITORY}/")
        if self.options.get("api_failure"):
            raise subprocess.CalledProcessError(1, args, stderr="failed synthetic-token")
        if path.startswith("pulls?"):
            result = list(self.options.get("existing", ()))
        elif path.startswith("compare/"):
            result = {"files": list(self.options.get("files", ("speech.py",))), "ahead_by": 7}
        else:
            result = {"html_url": "https://github.com/example/pull/43"}
        return SimpleNamespace(stdout=json.dumps(result))


def git_result(args, options):
    conflict = options.get("conflict", False)
    existing = branch_result(args, options)
    if existing is not None:
        return existing
    picking = "cherry-pick" in args and "--abort" not in args
    if picking and conflict:
        raise subprocess.CalledProcessError(1, args, stderr="synthetic conflict")
    if "rev-list" in args:
        return SimpleNamespace(stdout="a " + "b " * 2)
    if "diff" in args:
        return SimpleNamespace(stdout="conflicted.py" if conflict else "")
    return SimpleNamespace(stdout="")


def branch_result(args, options):
    if "ls-remote" in args and options.get("orphan_branch"):
        return SimpleNamespace(stdout="b" * 40 + " refs/heads/sync/42")
    if "FETCH_HEAD" in args and options.get("diverged_branch"):
        return SimpleNamespace(stdout="different.py")
    return None


def test_merged_hotfix_opens_isolated_draft_for_manual_merge(workflow):
    calls, summary = workflow()
    args, kwargs = calls[-1]
    assert args[2].endswith("/pulls")
    payload = json.loads(kwargs["input"])
    assert payload["head"] == "sync/42" and payload["base"] == "development"
    assert payload["draft"] is True
    assert "#42" in payload["body"] and "manually" in payload["body"]
    assert "## Review checklist" in payload["body"]
    assert "pull/43" in summary


def test_hotfix_uses_first_parent_and_pushes_only_sync_branch(workflow):
    calls, _summary = workflow()
    commands = [args for args, _ in calls if args[0] == "git"]
    assert any("cherry-pick" in args and "-m" in args for args in commands)
    pushes = [args for args in commands if "push" in args]
    assert len(pushes) == 1
    assert pushes[0][-1] == "HEAD:refs/heads/sync/42"


def test_repeated_hotfix_reuses_open_sync_pr(workflow):
    calls, summary = workflow(existing=[{"html_url": "https://github.com/example/pull/7"}])
    assert len(calls) == 1 and "pull/7" in summary


def test_identical_content_with_different_commits_does_not_open_pr(workflow):
    calls, summary = workflow(files=())
    assert len(calls) == 2 and "No PR needed" in summary


def test_conflict_never_pushes_or_opens_pr(workflow):
    calls, summary = workflow(conflict=True)
    assert not any("push" in args for args, _ in calls)
    assert not any("--method" in args for args, _ in calls)
    assert "nothing was pushed" in summary
    assert "synthetic conflict" in summary


@pytest.mark.parametrize("changes", [lambda p: p.update(merged=False), lambda p: p["head"].update(ref="feat/42-speech"), lambda p: p["base"].update(ref="development"), lambda p: p["head"]["repo"].update(full_name="fork/repo"), lambda p: p.update(merge_commit_sha="--bad")])
def test_untrusted_events_cannot_mutate_branches(workflow, changes):
    with pytest.raises(SystemExit):
        workflow(changes=changes)


def test_command_error_is_visible_but_token_is_redacted(workflow, capsys):
    with pytest.raises(SystemExit):
        workflow(api_failure=True)
    output = capsys.readouterr().out
    assert "failed <redacted>" in output and "synthetic-token" not in output


def test_hotfix_write_job_never_executes_repository_code_or_auto_merges():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in source and "uses:" not in source
    assert "contents: write" in source and "pull-requests: write" in source
    assert "gh pr merge" not in source and "core.hooksPath=/dev/null" in source
    assert "git_environment()" in source and "GIT_CONFIG_VALUE_0" in source


def test_rerun_after_pr_creation_failure_reuses_matching_branch(workflow):
    calls, summary = workflow(orphan_branch=True)
    assert not any("push" in args for args, _ in calls)
    assert calls[-1][0][2].endswith("/pulls")
    assert "pull/43" in summary


def test_existing_diverged_branch_is_never_overwritten(workflow):
    calls, summary = workflow(orphan_branch=True, diverged_branch=True)
    assert not any("push" in args for args, _ in calls)
    assert not any("--method" in args for args, _ in calls)
    assert "different content" in summary
