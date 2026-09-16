from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/USER_GUIDE.md",
    "docs/WINDOWS_RELEASE.md",
    "docs/design/speech-keyboard-reference.html",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/maintenance_task.md",
    ".github/ISSUE_TEMPLATE/config.yml",
)

REQUIRED_TEMPLATE_SECTIONS = {
    ".github/pull_request_template.md": {
        "Outcome",
        "Linked issue",
        "Changes",
        "Compatibility and risk",
        "Verification",
        "Evidence and limits",
        "Review checklist",
    },
    ".github/ISSUE_TEMPLATE/bug_report.md": {
        "Problem",
        "Reproduction",
        "Context and evidence",
        "Scope",
        "Compatibility constraints",
        "Acceptance criteria",
        "Verification",
    },
    ".github/ISSUE_TEMPLATE/feature_request.md": {
        "Goal",
        "User flow",
        "Scope",
        "Compatibility constraints",
        "Acceptance criteria",
        "Verification",
    },
    ".github/ISSUE_TEMPLATE/maintenance_task.md": {
        "Goal",
        "Context",
        "Scope",
        "Compatibility constraints",
        "Acceptance criteria",
        "Verification",
    },
}

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
LEVEL_TWO_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def test_required_guides_and_templates_exist() -> None:
    missing = [path for path in REQUIRED_FILES if not (REPO_ROOT / path).is_file()]

    assert not missing, "Missing required repository files:\n" + "\n".join(missing)


def test_local_markdown_links_resolve() -> None:
    documents = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        *sorted((REPO_ROOT / "docs").rglob("*.md")),
    ]
    broken_links: list[str] = []

    for document in documents:
        for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            elif " " in target:
                target = target.split(maxsplit=1)[0]

            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue

            local_path = unquote(parsed.path)
            if local_path and not (document.parent / local_path).exists():
                relative_document = document.relative_to(REPO_ROOT)
                broken_links.append(f"{relative_document}: {raw_target}")

    assert not broken_links, "Broken local documentation links:\n" + "\n".join(broken_links)


def test_templates_keep_required_sections() -> None:
    errors: list[str] = []

    for relative_path, required_sections in REQUIRED_TEMPLATE_SECTIONS.items():
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        headings = set(LEVEL_TWO_HEADING.findall(content))
        missing_sections = sorted(required_sections - headings)
        if missing_sections:
            errors.append(f"{relative_path}: {', '.join(missing_sections)}")

    assert not errors, "Missing required template sections:\n" + "\n".join(errors)


def test_blank_issues_are_disabled() -> None:
    config = (REPO_ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")

    assert re.search(r"^blank_issues_enabled:\s*false\s*$", config, re.MULTILINE)
