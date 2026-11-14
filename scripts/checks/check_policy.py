"""Enforce the reviewed Ruff exceptions before running the static tools."""

from __future__ import annotations

import re
import tokenize
from pathlib import Path

import tomli

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("pogled_assist", "scripts", "tests")
# These are permissions, not a snapshot of every setting. Changes need human review.
PATH_EXCEPTIONS = {
    "tests/**": {"ARG", "C901", "PLR0911", "PLR0912", "PLR0915", "S"},
    "scripts/**": {"T20"},
    # The model records this generator's hash; remove at the next model rebuild.
    "scripts/speech_suggestions/prepare_speech_model.py": {"S324"},
}
GLOBAL_EXCEPTIONS = {"PLW0603", "S101", "S603", "S607"}
NOQA = re.compile(r"#\s*noqa\b", re.IGNORECASE)
EXPLAINED_NOQA = re.compile(r"# noqa: [A-Z]+[0-9]+(?:, [A-Z]+[0-9]+)* - \S.*")
OTHER_SUPPRESSION = re.compile(
    r"#\s*(?:ruff\s*:\s*(?:noqa|ignore|file-ignore|disable|enable)\b|"
    r"flake8\s*:\s*noqa\b|isort\s*:\s*(?:skip_file|off|on)\b)",
    re.IGNORECASE,
)


def configuration_errors(root: Path) -> list[str]:
    with (root / "pyproject.toml").open("rb") as stream:
        ruff = tomli.load(stream)["tool"]["ruff"]
    lint = ruff.get("lint", {})
    errors = []
    for path, rules in lint.get("per-file-ignores", {}).items():
        if not set(rules) <= PATH_EXCEPTIONS.get(path, set()):
            errors.append(f"pyproject.toml: unapproved Ruff exceptions for {path}")
    if not set(lint.get("ignore", [])) <= GLOBAL_EXCEPTIONS:
        errors.append("pyproject.toml: unapproved global Ruff exceptions")
    # Alternative spellings must not silently enlarge the reviewed permissions.
    for table, keys in (
        (
            ruff,
            ("extend", "ignore", "per-file-ignores", "extend-ignore", "extend-per-file-ignores"),
        ),
        (lint, ("extend-ignore", "extend-per-file-ignores")),
    ):
        for key in keys:
            if table.get(key):
                errors.append(f"pyproject.toml: use the reviewed lint tables instead of {key}")
    errors.extend(
        f"{path.relative_to(root).as_posix()}: nested/alternate Ruff config"
        for path in alternate_configs(root)
    )
    return errors


def alternate_configs(root: Path) -> list[Path]:
    result = []
    for directory in (root, *(root / name for name in SOURCE_DIRS)):
        for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
            paths = directory.glob(name) if directory == root else directory.rglob(name)
            for path in paths:
                if path != root / "pyproject.toml":
                    result.append(path)
    return result


def suppression_errors(source: Path, root: Path) -> list[str]:
    errors = []
    with tokenize.open(source) as stream:
        for token in tokenize.generate_tokens(stream.readline):
            if token.type != tokenize.COMMENT:
                continue
            matches = list(NOQA.finditer(token.string))
            if OTHER_SUPPRESSION.search(token.string) or any(
                not EXPLAINED_NOQA.fullmatch(token.string[match.start() :]) for match in matches
            ):
                errors.append(
                    f"{source.relative_to(root).as_posix()}:{token.start[0]}: "
                    "use a line-level '# noqa: <code> - <reason>' only"
                )
    return errors


def check(root: Path) -> list[str]:
    errors = configuration_errors(root)
    sources = set(root.glob("*.py")) | set(root.glob("*.pyi"))
    for name in SOURCE_DIRS:
        for pattern in ("*.py", "*.pyi"):
            sources.update((root / name).rglob(pattern))
    for source in sorted(sources):
        errors.extend(suppression_errors(source, root))
    return errors


def main() -> int:
    errors = check(ROOT)
    for error in errors:
        print(error)
    if not errors:
        print("Ruff exception policy passed.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
