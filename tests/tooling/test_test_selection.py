from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.checks.select_tests import RULES, build_plan, changed_paths, select_tests

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("path", "required"),
    [
        (
            "pogled_assist/interaction/gaze_selection.py",
            [
                "tests/gaze/test_gaze_selection.py",
                "tests/ui/test_hotbar_e2e.py",
                "tests/app/test_application_startup.py",
            ],
        ),
        (
            "pogled_assist/tracking/tobii_stream_engine.py",
            ["tests/speech/test_speech.py", "tests/release/test_speech_bundle.py"],
        ),
        (
            "pogled_assist/suggestions/service.py",
            [
                "tests/suggestions/test_suggestion_profiles.py",
                "tests/ui/test_speech_predictions.py",
                "tests/app/test_settings_store.py",
            ],
        ),
        (
            "pogled_assist/speech/speech_service.py",
            [
                "tests/speech/test_speech.py",
                "tests/ui/test_speech_focus_e2e.py",
                "tests/release/test_speech_bundle.py",
            ],
        ),
        (
            "pogled_assist/windows/speech_process.py",
            ["tests/speech/test_speech_process.py", "tests/ui/test_speech_dialogs_e2e.py"],
        ),
        (
            "pogled_assist/ui/settings_window.py",
            [
                "tests/ui/test_settings_e2e.py",
                "tests/app/test_settings_store.py",
                "tests/gaze/test_mouse_controller.py",
                "tests/suggestions/test_suggestion_ui.py",
            ],
        ),
        (
            "pogled_assist/ui/speech_window.py",
            ["tests/speech/test_speech.py"],
        ),
        (
            "pogled_assist/keyboard_layouts.py",
            ["tests/speech/test_speech.py"],
        ),
        (
            "pogled_assist/windows/appbar.py",
            [
                "tests/app/test_windows_native.py",
                "tests/ui/test_hotbar_e2e.py",
                "tests/suggestions/test_suggestion_ui.py",
            ],
        ),
        (
            "packaging/windows/install_windows.ps1",
            ["tests/release/test_windows_installer.py", "tests/ui/test_installation_e2e.py"],
        ),
        (
            "scripts/ui/capture_ui.py",
            ["tests/ui/test_ui_rendering.py", "tests/suggestions/test_suggestion_ui.py"],
        ),
    ],
)
def test_selection_includes_consumers_of_changed_boundaries(path, required):
    plan = select_tests(ROOT, [path])

    assert not plan["full_suite"]
    assert set(required) <= set(plan["test_paths"])


@pytest.mark.parametrize(
    "path",
    [
        "dev.ps1",
        "requirements-dev.txt",
        "pyproject.toml",
        "pytest.ini",
        "tests/conftest.py",
        "tests/ui/_ui_fakes.py",
        "tests/ui/deleted_test.py",
        "tests/fixtures/new.json",
        ".github/workflows/ci.yml",
        "scripts/checks/select_tests.py",
        "pogled_assist/settings_store.py",
        "pogled_assist/main.py",
        "new-unknown.txt",
        "pogled_assist/assets/bosnian-model.json.gz",
        "language/bs/model/new.tsv",
    ],
)
def test_uncertain_or_shared_changes_fall_back_to_every_test(path):
    plan = select_tests(ROOT, [path])

    assert plan["full_suite"]
    assert set(plan["test_paths"]) == {
        p.relative_to(ROOT).as_posix() for p in ROOT.glob("tests/**/test_*.py")
    }
    assert plan["all_powershell"]
    assert plan["actions_check"]


def test_documentation_change_selects_only_repository_contracts():
    plan = select_tests(ROOT, ["docs/USER_GUIDE.md"])

    assert plan["test_paths"] == ["tests/tooling/test_repository_docs.py"]
    assert not plan["all_powershell"]
    assert not plan["actions_check"]


def test_new_test_is_selected_and_missing_mapped_targets_force_full_suite(tmp_path):
    tests = tmp_path / "tests" / "gaze"
    tests.mkdir(parents=True)
    (tests / "test_new.py").touch()

    assert select_tests(tmp_path, ["tests/gaze/test_new.py"])["test_paths"] == [
        "tests/gaze/test_new.py"
    ]
    assert select_tests(tmp_path, ["docs/new.md"])["full_suite"]


def test_no_changes_do_not_select_a_suite_accidentally():
    plan = select_tests(ROOT, [])

    assert plan["test_paths"] == []
    assert not plan["full_suite"]


def test_rule_targets_exist_so_a_stale_map_cannot_silently_drop_consumers():
    for _, targets, _ in RULES:
        for target in targets:
            assert (ROOT / target).exists(), target


@pytest.mark.parametrize(
    "path",
    [
        "pogled_assist/interaction/mouse_controller.py",
        "pogled_assist/speech/speech_library.py",
    ],
)
def test_cross_boundary_suggestion_ui_consumer_is_always_selected(path):
    assert "tests/suggestions/test_suggestion_ui.py" in select_tests(ROOT, [path])["test_paths"]


def test_missing_one_target_in_a_mapping_falls_back_even_when_other_targets_exist(tmp_path):
    (tmp_path / "tests" / "ui").mkdir(parents=True)
    (tmp_path / "tests" / "ui" / "test_existing.py").touch()

    plan = select_tests(tmp_path, ["scripts/ui/capture_ui.py"])

    assert plan["full_suite"]
    assert "mapped test targets missing" in plan["reasons"][0]["reason"]


def _git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def test_git_selection_unions_commits_index_worktree_new_files_and_both_rename_paths(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Selection Test")
    _git(tmp_path, "config", "user.email", "selection@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for name in ("committed.py", "staged.py", "dirty.py", "deleted.py", "old name.py"):
        (tmp_path / name).write_text("baseline\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    _git(tmp_path, "branch", "base")
    (tmp_path / "committed.py").write_text("committed change\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "topic change")
    (tmp_path / "staged.py").write_text("index change\n", encoding="utf-8")
    _git(tmp_path, "add", "staged.py")
    _git(tmp_path, "mv", "old name.py", "novo ime ž.py")
    (tmp_path / "dirty.py").write_text("working change\n", encoding="utf-8")
    (tmp_path / "deleted.py").unlink()
    (tmp_path / "untracked.py").touch()
    (tmp_path / "ignored.py").touch()

    assert set(changed_paths(tmp_path, "base")) == {
        "committed.py",
        "staged.py",
        "dirty.py",
        "deleted.py",
        "old name.py",
        "novo ime ž.py",
        "untracked.py",
    }


def test_missing_base_or_git_repository_falls_back_instead_of_skipping_tests(tmp_path):
    for root in (tmp_path, ROOT):
        plan = build_plan(root, "missing-base-for-selection-test")
        assert plan["full_suite"]
        assert "Cannot determine changes" in plan["reasons"][0]["reason"]


def test_selected_powershell_paths_exclude_deleted_scripts(tmp_path):
    (tmp_path / "update_windows.ps1").touch()
    plan = select_tests(tmp_path, ["update_windows.ps1", "setup_windows.ps1"])

    assert plan["powershell_paths"] == ["update_windows.ps1"]
