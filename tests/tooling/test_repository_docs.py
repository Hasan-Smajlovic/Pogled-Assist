from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT.md",
    "docs/UI_DEVELOPMENT.md",
    "docs/UI_GALLERY.md",
    "docs/DEVELOPMENT_TROUBLESHOOTING.md",
    "docs/USER_GUIDE.md",
    "docs/WINDOWS_RELEASE.md",
    "docs/features/speech-suggestions.md",
    "language/bs/README.md",
    "docs/design/speech-keyboard-reference.html",
    "docs/design/speech.html",
    "docs/design/settings.html",
    "docs/design/gaze-check.html",
    "docs/design/tracking.html",
    "docs/design/hotbar.html",
    "docs/design/keyboard.html",
    "docs/design/controller-keyboard.html",
    "docs/design/installation.html",
    "docs/design/reference-notes.html",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/maintenance_task.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".agents/skills/blast-radius/SKILL.md",
    ".agents/skills/grill-me/SKILL.md",
    ".agents/skills/interrogate/SKILL.md",
    ".agents/skills/security-review/SKILL.md",
    ".agents/skills/shipping-a-change/SKILL.md",
)

AGENT_GUIDANCE = (
    "AGENTS.md",
    "CLAUDE.md",
    ".agents/skills/*/SKILL.md",
    ".claude/skills/*/SKILL.md",
)

# Runtime folders such as data/ and logs/ exist only on an installed machine,
# so inline code under them is not checked.
PATH_ROOTS = {
    ".agents",
    ".claude",
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
        "Verification",
        "Risks and limits",
    },
    ".github/ISSUE_TEMPLATE/bug_report.md": {
        "Problem",
        "Reproduction",
        "Context",
        "Done when",
    },
    ".github/ISSUE_TEMPLATE/feature_request.md": {
        "Goal",
        "Details",
        "Done when",
    },
    ".github/ISSUE_TEMPLATE/maintenance_task.md": {
        "Goal",
        "Context",
        "Done when",
    },
}

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
LEVEL_TWO_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
INLINE_CODE = re.compile(r"`([^`\n]+)`")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HTML_ID = re.compile(r"\bid=[\"']([^\"']+)[\"']")
LEGACY_RUNTIME_PATH = re.compile(r"(?<![\w/])gaze_mouse/(?:[\w.-]+/)*[\w.-]+")
DESIGN_ROOT = REPO_ROOT / "docs" / "design"
SCRIPT_ELEMENT_ID = re.compile(r"(?:\$|checkEl)\(['\"]([^'\"]+)['\"]\)")


class _DesignPage(HTMLParser):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.id_references: list[str] = []
        self.main_count = 0
        self.feed(content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if identifier := attributes.get("id"):
            self.ids.append(identifier)
        for name in ("href", "src"):
            if target := attributes.get(name):
                self.links.append(target)
        if tag == "script" and (script := attributes.get("src")):
            self.scripts.append(script)
        for name in ("for", "aria-labelledby", "aria-describedby", "aria-controls"):
            self.id_references.extend((attributes.get(name) or "").split())
        self.main_count += tag == "main"


def test_design_pages_keep_local_resources_and_accessible_references() -> None:
    errors = []
    for document in sorted(DESIGN_ROOT.glob("*.html")):
        page = _DesignPage(document.read_text(encoding="utf-8"))
        errors.extend(_design_page_errors(document, page))
    assert not errors, "Broken design pages:\n" + "\n".join(errors)


def _design_page_errors(document, page):
    errors = []
    if page.main_count != 1:
        errors.append(f"{document.name}: expected one standalone main view")
    if len(page.ids) != len(set(page.ids)):
        errors.append(f"{document.name}: duplicate element IDs")
    errors.extend(f"{document.name}: missing labelled element {identifier}" for identifier in page.id_references if identifier not in page.ids)
    for target in page.links:
        errors.extend(_design_link_errors(document, target))
    return errors


def _design_link_errors(document, target):
    parsed = urlsplit(target)
    if parsed.scheme:
        return []
    destination = document.parent / unquote(parsed.path) if parsed.path else document
    if not destination.is_file():
        return [f"{document.name}: missing resource {target}"]
    if parsed.fragment and unquote(parsed.fragment) not in _anchors(destination):
        return [f"{document.name}: missing fragment {target}"]
    return []


def test_design_scripts_only_require_elements_on_their_own_page() -> None:
    errors = []
    for document in sorted(DESIGN_ROOT.glob("*.html")):
        page = _DesignPage(document.read_text(encoding="utf-8"))
        for script in page.scripts:
            errors.extend(_script_element_errors(document, page, script))
    assert not errors, "Coupled design scripts:\n" + "\n".join(errors)


def _script_element_errors(document, page, script):
    content = (document.parent / script).read_text(encoding="utf-8")
    return [f"{document.name}: {script} requires absent #{identifier}" for identifier in SCRIPT_ELEMENT_ID.findall(content) if identifier not in page.ids]


def test_required_guides_and_templates_exist() -> None:
    missing = [path for path in REQUIRED_FILES if not (REPO_ROOT / path).is_file()]

    assert not missing, "Missing required repository files:\n" + "\n".join(missing)


def test_skills_have_valid_metadata() -> None:
    errors = [
        f"{document.relative_to(REPO_ROOT)}: {error}"
        for document in sorted(REPO_ROOT.glob(".agents/skills/*/SKILL.md"))
        for error in _skill_metadata_errors(document)
    ]

    assert not errors, "Invalid skill metadata:\n" + "\n".join(errors)


def test_claude_skill_pointers_match_agent_skills() -> None:
    errors = _claude_skill_pointer_errors(REPO_ROOT)

    assert not errors, "Claude Code skill pointers are out of sync:\n" + "\n".join(errors)


@pytest.mark.parametrize(
    ("pointer", "expected_error"),
    [
        pytest.param(None, "missing .claude/skills/example-skill/SKILL.md", id="missing"),
        pytest.param(
            "---\nname: example-skill\ndescription: Other text.\n---\n"
            "[source](../../../.agents/skills/example-skill/SKILL.md)\n",
            "metadata differs",
            id="drifted-description",
        ),
        pytest.param(
            "---\nname: example-skill\ndescription: Review changes.\n---\nCopied workflow.\n",
            "does not link to",
            id="no-source-link",
        ),
    ],
)
def test_claude_skill_pointer_check_rejects_unsynced_pointers(
    tmp_path: Path, pointer: str | None, expected_error: str
) -> None:
    source = tmp_path / ".agents" / "skills" / "example-skill" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\nname: example-skill\ndescription: Review changes.\n---\n", encoding="utf-8"
    )
    if pointer is not None:
        target = tmp_path / ".claude" / "skills" / "example-skill" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(pointer, encoding="utf-8")

    assert any(expected_error in error for error in _claude_skill_pointer_errors(tmp_path))


def test_claude_skill_pointer_check_rejects_pointer_without_source(tmp_path: Path) -> None:
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    pointer = tmp_path / ".claude" / "skills" / "orphan" / "SKILL.md"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("---\nname: orphan\ndescription: Orphan.\n---\n", encoding="utf-8")

    assert _claude_skill_pointer_errors(tmp_path) == [
        ".claude/skills/orphan/SKILL.md: no matching .agents/skills/orphan/SKILL.md"
    ]


@pytest.mark.parametrize(
    "metadata",
    [
        "name: example-skill\ndescription: Review project changes.\n",
        'name: "example-skill"\ndescription: "Review changes: code and docs."\n',
        "name: 'example-skill'\ndescription: >\n  Review project changes\n  and their consequences.\n",
        "name: example-skill\ndescription: |\n  Review project changes.\n  Check their consequences.\n",
        "name: example-skill\ndescription: Review changes.\n"
        "metadata:\n  owner: contributors\n  areas: [code, docs]\n",
    ],
    ids=["plain", "quoted", "folded", "literal", "additional-metadata"],
)
def test_skill_metadata_accepts_valid_documents(tmp_path: Path, metadata: str) -> None:
    document = tmp_path / "example-skill" / "SKILL.md"
    document.parent.mkdir()
    document.write_text(
        f"---\n{metadata}---\n\n# Example skill\n\nBody: [this is Markdown, not YAML.\n",
        encoding="utf-8",
    )

    assert _skill_metadata_errors(document) == []


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        pytest.param("", "must start with ---", id="empty-file"),
        pytest.param("# Example skill\n", "must start with ---", id="missing-frontmatter"),
        pytest.param(
            "# Heading\n---\nname: example-skill\ndescription: Review changes.\n---\n",
            "must start with ---",
            id="frontmatter-after-body",
        ),
        pytest.param(
            "---\nname: example-skill\ndescription: Review changes.\n",
            "missing closing ---",
            id="unclosed-frontmatter",
        ),
        pytest.param("---\n---\n", "must be a YAML mapping", id="empty-frontmatter"),
        pytest.param("---\n- example-skill\n---\n", "must be a YAML mapping", id="sequence"),
        pytest.param("---\nexample-skill\n---\n", "must be a YAML mapping", id="scalar"),
        pytest.param(
            "---\nname: example-skill\ndescription: [unfinished\n---\n",
            "invalid YAML",
            id="invalid-yaml",
        ),
        pytest.param(
            "---\nname: other-skill\ndescription: Review changes.\n---\n",
            "name must match directory 'example-skill'",
            id="wrong-name",
        ),
        pytest.param(
            "---\ndescription: Review changes.\n---\n",
            "name must be a non-empty string",
            id="missing-name",
        ),
        pytest.param(
            "---\nname: example-skill\n---\n",
            "description must be a non-empty string",
            id="missing-description",
        ),
        pytest.param(
            "---\nname: wrong-name\nname: example-skill\ndescription: Review changes.\n---\n",
            "duplicate mapping keys",
            id="duplicate-name",
        ),
        pytest.param(
            "---\nname: example-skill\ndescription: First.\ndescription: Second.\n---\n",
            "duplicate mapping keys",
            id="duplicate-description",
        ),
        pytest.param(
            "---\nname: example-skill\ndescription: Review changes.\n"
            "metadata:\n  owner: first\n  owner: second\n---\n",
            "duplicate mapping keys",
            id="duplicate-nested-key",
        ),
    ],
)
def test_skill_metadata_rejects_invalid_documents(
    tmp_path: Path, content: str, expected_error: str
) -> None:
    document = tmp_path / "example-skill" / "SKILL.md"
    document.parent.mkdir()
    document.write_text(content, encoding="utf-8")

    assert any(expected_error in error for error in _skill_metadata_errors(document))


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize(
    "value",
    ["null", "''", "'   '", "true", "42", "[text]", "{text: value}"],
    ids=["null", "empty", "whitespace", "boolean", "number", "sequence", "mapping"],
)
def test_skill_metadata_rejects_empty_or_non_text_fields(
    tmp_path: Path, field: str, value: str
) -> None:
    document = tmp_path / "example-skill" / "SKILL.md"
    document.parent.mkdir()
    metadata = {"name": "example-skill", "description": "Review changes."}
    metadata[field] = value
    content = "\n".join(f"{key}: {item}" for key, item in metadata.items())
    document.write_text(f"---\n{content}\n---\n", encoding="utf-8")

    assert f"{field} must be a non-empty string" in _skill_metadata_errors(document)


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


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "duplicate mapping keys",
                node.start_mark,
            )
        return mapping


def _skill_metadata_errors(document: Path) -> list[str]:
    lines = document.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return ["metadata must start with --- on the first line"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return ["metadata is missing closing ---"]
    try:
        metadata = yaml.load("\n".join(lines[1:end]), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        return [f"invalid YAML metadata: {error}"]
    if not isinstance(metadata, dict):
        return ["metadata must be a YAML mapping"]

    return [error for field in ("name", "description") if (error := _metadata_field_error(document, metadata, field))]


def _metadata_field_error(document, metadata, field):
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip():
        return f"{field} must be a non-empty string"
    if field == "name" and value != document.parent.name:
        return f"name must match directory '{document.parent.name}', got {value!r}"
    return ""


def _skill_metadata(document: Path) -> object:
    lines = document.read_text(encoding="utf-8").splitlines()
    end = lines.index("---", 1)
    return yaml.load("\n".join(lines[1:end]), Loader=_UniqueKeyLoader)


def _claude_skill_pointer_errors(root: Path) -> list[str]:
    sources = {path.parent.name: path for path in (root / ".agents" / "skills").glob("*/SKILL.md")}
    pointers = {path.parent.name: path for path in (root / ".claude" / "skills").glob("*/SKILL.md")}
    errors = [
        f".claude/skills/{name}/SKILL.md: no matching .agents/skills/{name}/SKILL.md"
        for name in sorted(pointers.keys() - sources.keys())
    ]
    for name in sorted(sources):
        if name not in pointers:
            errors.append(f"missing .claude/skills/{name}/SKILL.md")
            continue
        pointer = pointers[name]
        if _skill_metadata(pointer) != _skill_metadata(sources[name]):
            errors.append(f".claude/skills/{name}/SKILL.md: metadata differs from its source")
        source_link = f"../../../.agents/skills/{name}/SKILL.md"
        if f"]({source_link})" not in pointer.read_text(encoding="utf-8"):
            errors.append(f".claude/skills/{name}/SKILL.md: does not link to {source_link}")
    return errors


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
    return [target for target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")) if _local_link_broken(document, target)]


def _local_link_broken(document, raw_target):
    parsed = urlsplit(_link_target(raw_target))
    if parsed.scheme:
        return False
    local_path = unquote(parsed.path)
    destination = document.parent / local_path if local_path else document
    if not destination.exists():
        return True
    return bool(parsed.fragment) and unquote(parsed.fragment) not in _anchors(destination)


def _link_target(raw_target):
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        return target[1:-1]
    return target.split(maxsplit=1)[0] if " " in target else target


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
