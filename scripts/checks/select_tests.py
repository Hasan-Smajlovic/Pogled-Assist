"""Conservative local test selection; full verification remains mandatory."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

DOC_TEST = "tests/tooling/test_repository_docs.py"
# Keep consumers of each boundary in the map, not just its unit tests.
RULES = (
    (
        ("pogled_assist/tracking/", "pogled_assist/interaction/"),
        (
            "tests/gaze/",
            "tests/ui/",
            "tests/app/",
            "tests/speech/test_speech.py",
            "tests/suggestions/test_suggestion_ui.py",
            "tests/release/test_installation_check.py",
            "tests/release/test_package_smoke.py",
            "tests/release/test_speech_bundle.py",
        ),
        "gaze boundary and its application/UI/speech consumers",
    ),
    (
        ("pogled_assist/suggestions/", "scripts/speech_suggestions/"),
        ("tests/suggestions/", "tests/ui/", "tests/app/", "tests/release/test_package_smoke.py"),
        "suggestions, learned settings and UI consumers",
    ),
    (
        ("pogled_assist/speech/", "pogled_assist/windows/speech_process.py"),
        (
            "tests/speech/",
            "tests/ui/",
            "tests/app/test_settings_store.py",
            "tests/app/test_application_startup.py",
            "tests/suggestions/test_suggestion_ui.py",
            "tests/release/test_speech_bundle.py",
            "tests/release/test_package_smoke.py",
        ),
        "speech boundary, bundle and UI consumers",
    ),
    (
        ("pogled_assist/ui/", "pogled_assist/toolbar.py", "pogled_assist/keyboard_layouts.py"),
        (
            "tests/ui/",
            "tests/suggestions/",
            "tests/gaze/",
            "tests/app/",
            "tests/speech/test_speech.py",
            "tests/release/test_package_smoke.py",
        ),
        "UI composition, keyboard, gaze, speech and application consumers",
    ),
    (
        ("pogled_assist/windows/",),
        (
            "tests/app/",
            "tests/gaze/",
            "tests/ui/",
            "tests/release/",
            "tests/suggestions/test_suggestion_ui.py",
        ),
        "Windows boundary and its consumers",
    ),
    (
        (
            "pogled_assist/release_update.py",
            "pogled_assist/installation_check.py",
            "scripts/release/",
            "packaging/windows/",
            "setup_windows.ps1",
            "update_windows.ps1",
        ),
        ("tests/release/", "tests/app/", "tests/ui/", "tests/suggestions/test_suggestion_ui.py"),
        "release, installation and their application/UI consumers",
    ),
    (
        ("scripts/ui/",),
        ("tests/ui/", "tests/suggestions/test_suggestion_ui.py"),
        "UI previews, gallery and suggestion rendering",
    ),
)
GLOBAL_FILES = {
    "dev.ps1",
    "pytest.ini",
    "pyproject.toml",
    "tests/conftest.py",
    "PSScriptAnalyzerSettings.psd1",
    "VERSION",
    ".gitattributes",
    ".gitignore",
}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    return result.stdout


def changed_paths(root: Path, base_ref: str) -> list[str]:
    # A missing/shallow base must never turn into an empty successful selection.
    base = _git(root, "merge-base", "--", "HEAD", base_ref).strip()
    paths: set[str] = set()
    for arguments in (
        ("diff", "--name-only", "-z", "--no-renames", base, "HEAD", "--"),
        ("diff", "--name-only", "-z", "--no-renames", "--cached", "--"),
        ("diff", "--name-only", "-z", "--no-renames", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.update(filter(None, _git(root, *arguments).split("\0")))
    return sorted(paths)


def _matches(path: str, pattern: str) -> bool:
    return path.startswith(pattern) if pattern.endswith("/") else path == pattern


def select_tests(root: Path, paths: list[str], git_error: str | None = None) -> dict:
    all_tests = sorted(
        path.relative_to(root).as_posix() for path in root.glob("tests/**/test_*.py")
    )
    selected: set[str] = set()
    reasons = []
    full_suite = git_error is not None
    for path in paths:
        patterns: tuple[str, ...] = ()
        if path in GLOBAL_FILES or path.startswith(
            (
                "requirements",
                "scripts/checks/",
                ".github/workflows/",
                "tests/fixtures/",
                "pogled_assist/assets/",
                "assets/",
                "language/",
            )
        ):
            reason = "shared configuration, dependency, check or bundled data: full suite"
            full_suite = True
        elif path.startswith("tests/"):
            if path in all_tests:
                patterns = (path,)
                reason = "changed or new test module"
            else:
                reason = "shared test helper or deleted test: full suite"
                full_suite = True
        elif path.endswith((".md", ".html")) and (
            "/" not in path or path.startswith(("docs/", ".agents/", ".github/"))
        ):
            patterns = (DOC_TEST,)
            reason = "repository documentation and link contracts"
        else:
            reason = "unmapped path: full suite"
            for prefixes, targets, description in RULES:
                if any(_matches(path, prefix) for prefix in prefixes):
                    patterns = targets
                    reason = description
                    break
            if not patterns:
                full_suite = True
        matches = [test for test in all_tests if any(_matches(test, p) for p in patterns)]
        if patterns and (not matches or any(not (root / pattern).exists() for pattern in patterns)):
            full_suite = True
            reason = "mapped test targets missing: full suite"
        selected.update(matches)
        reasons.append({"path": path, "reason": reason, "tests": matches})
    if git_error:
        reasons.append({"path": "Git", "reason": git_error + ": full suite", "tests": []})
    if full_suite:
        selected = set(all_tests)
    return {
        "changed_paths": paths,
        "test_paths": sorted(selected),
        "full_suite": full_suite,
        "reasons": reasons,
        "powershell_paths": [p for p in paths if p.endswith(".ps1") and (root / p).is_file()],
        "all_powershell": full_suite,
        "actions_check": full_suite or any(p.startswith(".github/workflows/") for p in paths),
    }


def build_plan(root: Path, base_ref: str) -> dict:
    try:
        return select_tests(root, changed_paths(root, base_ref))
    except (OSError, subprocess.CalledProcessError) as error:
        return select_tests(
            root, [], f"Cannot determine changes against {base_ref} ({type(error).__name__})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/development")
    arguments = parser.parse_args()
    print(json.dumps(build_plan(Path.cwd(), arguments.base_ref), ensure_ascii=True))


if __name__ == "__main__":
    main()
