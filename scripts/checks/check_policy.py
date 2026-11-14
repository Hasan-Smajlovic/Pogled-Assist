"""Enforce the reviewed check exceptions before running the static tools."""

from __future__ import annotations

import re
import subprocess
import tokenize
from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parents[2]
# These are permissions, not a snapshot of every setting. Changes need human review.
PATH_EXCEPTIONS = {
    "tests/**": {"ARG", "C901", "PLR0911", "PLR0912", "PLR0915", "S"},
    "scripts/**": {"T20"},
    # The model records this generator's hash; remove at the next model rebuild.
    "scripts/speech_suggestions/prepare_speech_model.py": {"S324"},
}
GLOBAL_EXCEPTIONS = {"PLW0603", "S101", "S603", "S607"}
# Every lint run selects at least these rules; selecting more is allowed.
REQUIRED_RULES = {
    *("A", "ARG", "ASYNC", "B", "BLE", "C90", "DTZ", "E4", "E7", "E9", "ERA", "F", "FURB"),
    *("G", "I", "LOG", "PGH", "PLE", "PLR0911", "PLR0912", "PLR0915", "PLW", "RUF", "S"),
    *("SIM", "T20", "UP"),
}
# Other Ruff settings can skip files or relax rules (exclude, include, complexity limits,
# plugin options), so each new key needs a policy change.
RUFF_SETTINGS = {"target-version", "line-length", "lint"}
LINT_SETTINGS = {"select", "extend-select", "ignore", "per-file-ignores"}
# The reviewed type-check settings. Any change, a stricter one included, updates this table.
TYPE_SETTINGS = {
    "include": ["pogled_assist", "scripts", "run_gaze_mouse.py"],
    "pythonVersion": "3.10",
    "pythonPlatform": "Windows",
    "typeCheckingMode": "standard",
    "reportMissingParameterType": "error",
    "reportUnnecessaryTypeIgnoreComment": "error",
    "enableTypeIgnoreComments": False,
    "reportIgnoreCommentWithoutRule": "error",
}
# Files that Ruff, basedpyright or import-linter read instead of the root pyproject.toml.
CONFIG_NAMES = {
    *("ruff.toml", ".ruff.toml", "pyproject.toml"),
    *("pyrightconfig.json", ".importlinter", "setup.cfg"),
}
PYTHON_SUFFIXES = {".py", ".pyi", ".pyw"}
NOQA = re.compile(r"#\s*noqa\b", re.IGNORECASE)
EXPLAINED_NOQA = re.compile(r"# noqa: [A-Z]+[0-9]+(?:, [A-Z]+[0-9]+)* - \S.*")
PYRIGHT = re.compile(r"#\s*(?:based)?pyright\s*:", re.IGNORECASE)
EXPLAINED_PYRIGHT = re.compile(r"# pyright: ignore\[[A-Za-z]+(?:, [A-Za-z]+)*\] - \S.*")
OTHER_SUPPRESSION = re.compile(
    r"#\s*(?:ruff\s*:\s*(?:noqa|ignore|file-ignore|disable|enable|isort)\b|"
    r"flake8\s*:\s*noqa\b|isort\s*:|fmt\s*:\s*(?:off|on|skip)\b|"
    r"yapf\s*:\s*(?:disable|enable)\b)",
    re.IGNORECASE,
)
WORKFLOW_SUPPRESSION = re.compile(r"#.*\bzizmor\s*:\s*ignore", re.IGNORECASE)


def repository_files(root: Path) -> list[Path]:
    """List the files Git does not ignore, untracked ones included, as Ruff finds them."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout.decode("utf-8")
    return sorted({root / name for name in listing.split("\0") if name and (root / name).is_file()})


def _selected(lint: dict, rule: str) -> bool:
    choices = [*lint.get("select", []), *lint.get("extend-select", [])]
    return any(choice == "ALL" or rule.startswith(choice) for choice in choices)


def configuration_errors(root: Path, files: list[Path]) -> list[str]:
    with (root / "pyproject.toml").open("rb") as stream:
        tool = tomli.load(stream).get("tool", {})
    ruff = tool.get("ruff", {})
    lint = ruff.get("lint", {})
    errors = [
        f"pyproject.toml: unreviewed Ruff setting {key}"
        for key in sorted(ruff.keys() - RUFF_SETTINGS)
    ]
    errors.extend(
        f"pyproject.toml: unreviewed Ruff setting lint.{key}"
        for key in sorted(lint.keys() - LINT_SETTINGS)
    )
    missing = sorted(rule for rule in REQUIRED_RULES if not _selected(lint, rule))
    if missing:
        errors.append(f"pyproject.toml: Ruff must select {', '.join(missing)}")
    for path, rules in lint.get("per-file-ignores", {}).items():
        if not set(rules) <= PATH_EXCEPTIONS.get(path, set()):
            errors.append(f"pyproject.toml: unapproved Ruff exceptions for {path}")
    if not set(lint.get("ignore", [])) <= GLOBAL_EXCEPTIONS:
        errors.append("pyproject.toml: unapproved global Ruff exceptions")
    if tool.get("basedpyright") != TYPE_SETTINGS:
        errors.append("pyproject.toml: [tool.basedpyright] differs from the reviewed settings")
    errors.extend(
        f"{path.relative_to(root).as_posix()}: alternate or nested check configuration"
        for path in files
        if path.name in CONFIG_NAMES and path != root / "pyproject.toml"
    )
    return errors


def _unexplained(comment: str, directive: re.Pattern[str], explained: re.Pattern[str]) -> bool:
    return any(
        not explained.fullmatch(comment[match.start() :]) for match in directive.finditer(comment)
    )


def suppression_errors(source: Path, root: Path) -> list[str]:
    name = source.relative_to(root).as_posix()
    errors = []
    try:
        with tokenize.open(source) as stream:
            comments = [
                token
                for token in tokenize.generate_tokens(stream.readline)
                if token.type == tokenize.COMMENT
            ]
    except (SyntaxError, tokenize.TokenError, UnicodeDecodeError) as error:
        return [f"{name}: cannot read comments: {error}"]
    for token in comments:
        if (
            OTHER_SUPPRESSION.search(token.string)
            or _unexplained(token.string, NOQA, EXPLAINED_NOQA)
            or _unexplained(token.string, PYRIGHT, EXPLAINED_PYRIGHT)
        ):
            errors.append(
                f"{name}:{token.start[0]}: use a line-level '# noqa: <code> - <reason>' or "
                "'# pyright: ignore[<rule>] - <reason>' only"
            )
    return errors


def workflow_errors(source: Path, root: Path) -> list[str]:
    name = source.relative_to(root).as_posix()
    return [
        f"{name}:{number}: record accepted findings in .github/zizmor.yml instead"
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1)
        if WORKFLOW_SUPPRESSION.search(line)
    ]


def check(root: Path) -> list[str]:
    files = repository_files(root)
    errors = configuration_errors(root, files)
    for path in files:
        if path.suffix in PYTHON_SUFFIXES:
            errors.extend(suppression_errors(path, root))
        elif path.suffix in {".yml", ".yaml"} and path.relative_to(root).parts[0] == ".github":
            errors.extend(workflow_errors(path, root))
    return errors


def main() -> int:
    try:
        errors = check(ROOT)
    except (OSError, subprocess.SubprocessError, tomli.TOMLDecodeError) as error:
        print(f"Cannot check the exception policy: {error}")
        return 1
    for error in errors:
        print(error)
    if not errors:
        print("Exception policy passed.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
