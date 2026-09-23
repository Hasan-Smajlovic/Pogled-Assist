from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/DEVELOPMENT_TROUBLESHOOTING.md",
    "docs/USER_GUIDE.md",
    "docs/WINDOWS_RELEASE.md",
    "docs/features/speech-suggestions.md",
    "docs/design/speech-keyboard-reference.html",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/maintenance_task.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".agents/skills/security-review/SKILL.md",
    ".agents/skills/shipping-a-change/SKILL.md",
)

AGENT_GUIDANCE = (
    "AGENTS.md",
    ".agents/skills/*/SKILL.md",
)

# Runtime folders such as data/ and logs/ exist only on an installed machine,
# so inline code under them is not checked.
PATH_ROOTS = {
    ".agents",
    ".github",
    "assets",
    "docs",
    "pogled_assist",
    "language",
    "packaging",
    "scripts",
    "tests",
}
ROOT_FILE_SUFFIXES = {".ini", ".md", ".psd1", ".ps1", ".py", ".toml", ".txt"}
ROOT_FILE_NAMES = {".gitattributes", ".gitignore", "VERSION"}

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
INLINE_CODE = re.compile(r"`([^`\n]+)`")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HTML_ID = re.compile(r"\bid=[\"']([^\"']+)[\"']")
LEGACY_RUNTIME_PATH = re.compile(r"(?<![\w/])gaze_mouse/(?:[\w.-]+/)*[\w.-]+")


def test_required_guides_and_templates_exist() -> None:
    missing = [path for path in REQUIRED_FILES if not (REPO_ROOT / path).is_file()]

    assert not missing, "Missing required repository files:\n" + "\n".join(missing)


def test_agent_guidance_names_existing_paths() -> None:
    missing: list[str] = []

    for document in _agent_guidance():
        for token in INLINE_CODE.findall(document.read_text(encoding="utf-8")):
            if _is_repo_path(token) and not _path_exists(token):
                missing.append(f"{document.relative_to(REPO_ROOT)}: {token}")

    assert not missing, "Agent guidance names missing paths:\n" + "\n".join(missing)


def test_local_markdown_links_resolve() -> None:
    broken_links: list[str] = []

    for document in _maintained_markdown():
        broken_links.extend(
            f"{document.relative_to(REPO_ROOT)}: {target}"
            for target in _broken_local_links(document)
        )

    assert not broken_links, "Broken local documentation links:\n" + "\n".join(broken_links)


def test_maintained_docs_do_not_use_removed_runtime_paths() -> None:
    stale = [
        f"{document.relative_to(REPO_ROOT)}: {match.group()}"
        for document in _maintained_markdown()
        for match in LEGACY_RUNTIME_PATH.finditer(document.read_text(encoding="utf-8"))
    ]
    assert not stale, "Removed runtime paths in documentation:\n" + "\n".join(stale)


def test_documentation_checks_reject_wrong_fragments_and_old_runtime_paths(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("## Valid heading\n[bad](#missing-heading)\n", encoding="utf-8")

    assert _broken_local_links(document) == ["#missing-heading"]
    assert LEGACY_RUNTIME_PATH.search("gaze_mouse/suggestion_model.py")


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


def _agent_guidance() -> list[Path]:
    return sorted(path for pattern in AGENT_GUIDANCE for path in REPO_ROOT.glob(pattern))


def _maintained_markdown() -> list[Path]:
    return sorted(
        {
            REPO_ROOT / "README.md",
            REPO_ROOT / "CONTRIBUTING.md",
            *_agent_guidance(),
            *(REPO_ROOT / "docs").rglob("*.md"),
            *(REPO_ROOT / "language").rglob("*.md"),
            *(REPO_ROOT / "tests" / "fixtures").rglob("*.md"),
        }
    )


def _broken_local_links(document: Path) -> list[str]:
    broken: list[str] = []
    for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
        target = raw_target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        elif " " in target:
            target = target.split(maxsplit=1)[0]

        parsed = urlsplit(target)
        if parsed.scheme:
            continue

        local_path = unquote(parsed.path)
        destination = document.parent / local_path if local_path else document
        fragment = unquote(parsed.fragment)
        if not destination.exists() or (fragment and fragment not in _anchors(destination)):
            broken.append(raw_target)
    return broken


def _anchors(document: Path) -> set[str]:
    content = document.read_text(encoding="utf-8")
    if document.suffix.lower() == ".html":
        return set(HTML_ID.findall(content))
    anchors = set(HTML_ID.findall(content))
    counts: dict[str, int] = {}
    for heading in MARKDOWN_HEADING.findall(content):
        heading = re.sub(r"<[^>]+>", "", heading)
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\s-]", "", heading.lower()).replace("_", "")
        slug = re.sub(r"\s+", "-", slug.strip())
        count = counts.get(slug, 0)
        anchors.add(f"{slug}-{count}" if count else slug)
        counts[slug] = count + 1
    return anchors


def _is_repo_path(token: str) -> bool:
    if any(character.isspace() for character in token) or "\\" in token:
        return False
    if "/" in token:
        return token.split("/", 1)[0] in PATH_ROOTS
    return token in ROOT_FILE_NAMES or Path(token).suffix in ROOT_FILE_SUFFIXES


def _path_exists(token: str) -> bool:
    if any(character in token for character in "*?["):
        return any(REPO_ROOT.glob(token))
    return (REPO_ROOT / token).exists()
