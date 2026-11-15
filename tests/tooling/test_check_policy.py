from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.checks import check_policy

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


@pytest.fixture
def policy_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    (tmp_path / "pyproject.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "pogled_assist").mkdir()
    return tmp_path


def _add_to_table(table, setting):
    return lambda config: config.replace(f"[{table}]\n", f"[{table}]\n{setting}\n")


@pytest.mark.parametrize(
    "change",
    [
        lambda config: config.replace(
            "[tool.ruff.lint.per-file-ignores]\n",
            "[tool.ruff.lint.per-file-ignores]\n'pogled_assist/probe.py' = [\"ALL\"]\n",
        ),
        lambda config: (
            config
            + '\n[tool.ruff.lint.extend-per-file-ignores]\n"pogled_assist/probe.py" = ["ALL"]\n'
        ),
        lambda config: config.replace(
            '"scripts/speech_suggestions/prepare_speech_model.py" = ["S324"]',
            '"scripts/speech_suggestions/prepare_speech_model.py" = ["ALL"]',
        ),
        lambda config: config.replace('"scripts/**" = ["T20"]', '"scripts/**" = ["T20", "S"]'),
        lambda config: config.replace('    "S101",', '    "ALL",'),
        _add_to_table("tool.ruff", 'extend = "other.toml"'),
        _add_to_table("tool.ruff.lint", 'extend-ignore = ["S"]'),
        # Rules and files can also leave the check without any exception entry.
        lambda config: config.replace('    "S",\n', "").replace('    "BLE",\n', ""),
        _add_to_table("tool.ruff", 'exclude = ["pogled_assist"]'),
        _add_to_table("tool.ruff", 'extend-exclude = ["pogled_assist/probe.py"]'),
        _add_to_table("tool.ruff", 'include = ["scripts/**/*.py"]'),
        _add_to_table("tool.ruff.lint", 'exclude = ["pogled_assist/probe.py"]'),
        _add_to_table("tool.ruff.lint", 'dummy-variable-rgx = ".*"'),
        lambda config: config + "\n[tool.ruff.lint.mccabe]\nmax-complexity = 99\n",
        lambda config: config + "\n[tool.ruff.lint.pylint]\nmax-statements = 999\n",
        lambda config: config + '\n[tool.ruff.format]\nexclude = ["pogled_assist"]\n',
        lambda config: config.replace('typeCheckingMode = "standard"', 'typeCheckingMode = "off"'),
        lambda config: config.replace('reportMissingParameterType = "error"', ""),
        _add_to_table("tool.basedpyright", 'ignore = ["pogled_assist/probe.py"]'),
        _add_to_table("tool.basedpyright", 'reportReturnType = "none"'),
        _add_to_table("tool.basedpyright", 'baselineFile = ".basedpyright/other.json"'),
    ],
)
def test_configuration_rejects_unapproved_exceptions(policy_repo, change):
    (policy_repo / "pyproject.toml").write_text(change(CONFIG), encoding="utf-8")

    assert check_policy.check(policy_repo)


@pytest.mark.parametrize(
    "change",
    [
        lambda config: (
            config.replace('"scripts/**" = ["T20"]', "'scripts/**'=['T20']")
            .replace('"S324"', "")
            .replace('"S101",', "")
        ),
        _add_to_table("tool.ruff.lint", 'extend-select = ["N"]'),
        lambda config: config.replace('    "PLR0911",\n    "PLR0912",\n', '    "PLR",\n'),
    ],
)
def test_formatting_removed_exceptions_and_added_rules_are_allowed(policy_repo, change):
    (policy_repo / "pyproject.toml").write_text(change(CONFIG), encoding="utf-8")

    assert check_policy.check(policy_repo) == []


@pytest.mark.parametrize(
    "path",
    [
        "ruff.toml",
        ".ruff.toml",
        "pogled_assist/ruff.toml",
        "pogled_assist/pyproject.toml",
        "packaging/windows/ruff.toml",
        "pyrightconfig.json",
        ".importlinter",
        "setup.cfg",
        "RUFF.TOML",
        ".RuFf.ToMl",
        "pogled_assist/PYPROJECT.TOML",
        "PYRIGHTCONFIG.JSON",
        ".IMPORTLINTER",
        "Setup.Cfg",
    ],
)
def test_alternate_configuration_is_rejected(policy_repo, path):
    (policy_repo / path).parent.mkdir(parents=True, exist_ok=True)
    (policy_repo / path).write_text('[lint]\nignore = ["ALL"]\n', encoding="utf-8")

    assert any(path in error for error in check_policy.check(policy_repo))


def test_configuration_in_ignored_directories_is_not_read(policy_repo):
    (policy_repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    package = policy_repo / ".venv" / "lib" / "package"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (package / "module.py").write_text("import os  # noqa\n", encoding="utf-8")

    assert check_policy.check(policy_repo) == []


@pytest.mark.parametrize("filename", ["RUFF.TOML", "PYRIGHTCONFIG.JSON"])
def test_policy_rejects_uppercase_configuration_that_the_tool_loads(policy_repo, filename):
    source = policy_repo / "pogled_assist" / "probe.py"
    if filename == "RUFF.TOML":
        source.write_text("import math\n", encoding="utf-8")
        contents = '[lint]\nignore = ["ALL"]\n'
        command = [sys.executable, "-m", "ruff", "check", str(source)]
    else:
        source.write_text(
            "def identity(value: int) -> int:\n    return str(value)\n", encoding="utf-8"
        )
        (policy_repo / "scripts").mkdir()
        (policy_repo / "run_gaze_mouse.py").write_text("", encoding="utf-8")
        (policy_repo / ".basedpyright").mkdir()
        (policy_repo / ".basedpyright" / "baseline.json").write_text(
            '{"files": {}}', encoding="utf-8"
        )
        contents = json.dumps({"include": ["pogled_assist"], "typeCheckingMode": "off"})
        command = [sys.executable, "-m", "basedpyright", "--pythonpath", sys.executable]

    def run():
        return subprocess.run(
            command,
            cwd=policy_repo,
            env=dict(os.environ, CI="true"),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    invalid = run()
    assert invalid.returncode == 1, invalid.stdout + invalid.stderr
    (policy_repo / filename).write_text(contents, encoding="utf-8")
    overridden = run()
    expected = 0 if (policy_repo / filename.lower()).exists() else 1
    assert overridden.returncode == expected, overridden.stdout + overridden.stderr
    assert f"{filename}: alternate or nested check configuration" in check_policy.check(policy_repo)


@pytest.mark.parametrize("ignore_file", [".ignore", ".gitignore", "pogled_assist/.ignore"])
@pytest.mark.parametrize("suffix", [".py", ".pyi"])
def test_policy_rejects_ignored_sources_that_ruff_would_skip(policy_repo, ignore_file, suffix):
    source = policy_repo / "pogled_assist" / f"probe{suffix}"
    source.write_text("import math\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=policy_repo, check=True, timeout=30)
    assert check_policy.check(policy_repo) == []
    command = [sys.executable, "-m", "ruff", "check", "."]
    invalid = subprocess.run(
        command, cwd=policy_repo, capture_output=True, text=True, check=False, timeout=30
    )
    assert invalid.returncode == 1, invalid.stdout + invalid.stderr
    assert "F401" in invalid.stdout
    (policy_repo / ignore_file).write_text("probe*\n", encoding="utf-8")
    ignored = subprocess.run(
        command, cwd=policy_repo, capture_output=True, text=True, check=False, timeout=30
    )
    assert ignored.returncode == 0, ignored.stdout + ignored.stderr
    assert (
        f"pogled_assist/probe{suffix}: Python source omitted by Ruff file discovery"
        in check_policy.check(policy_repo)
    )


def test_policy_checks_untracked_sources_ignored_only_by_ruff(policy_repo):
    (policy_repo / "pogled_assist" / "probe.py").write_text("import math\n", encoding="utf-8")
    (policy_repo / ".ignore").write_text("pogled_assist/\n", encoding="utf-8")

    assert (
        "pogled_assist/probe.py: Python source omitted by Ruff file discovery"
        in check_policy.check(policy_repo)
    )


@pytest.mark.parametrize(
    ("comment", "allowed"),
    [
        ("# noqa", False),
        ("# noqa: F401", False),
        ("# noqa: F401 - ", False),
        ("# noqa: F401, S101 - documented boundary", True),
        ("# ruff: noqa: F401", False),
        ("#ruff:noqa: F401 - a reason still cannot exempt a whole file", False),
        ("# flake8: noqa", False),
        ("# ruff: ignore[F401]", False),
        ("# ruff: file-ignore[F401]", False),
        ("# ruff: disable[F401]", False),
        ("# ruff: enable[F401]", False),
        ("# ruff: isort: skip_file", False),
        ("# isort: skip_file", False),
        ("# isort: skip", False),
        ("# isort: split", False),
        ("# isort: off", False),
        ("# fmt: off", False),
        ("# fmt: on", False),
        ("# fmt: skip", False),
        ("# yapf: disable", False),
        ("# pyright: basic", False),
        ("# pyright: reportReturnType=false", False),
        ("# basedpyright: ignore[reportReturnType] - reason", False),
        ("# pyright: ignore[reportReturnType]", False),
        ("# pyright: ignore[reportReturnType] - Qt returns a wider type here", True),
        ("# normal comment", True),
    ],
)
def test_suppression_policy_checks_actual_comment_tokens(policy_repo, comment, allowed):
    source = policy_repo / "pogled_assist" / "probe.py"
    source.write_text(f"import math  {comment}\n", encoding="utf-8")

    assert (check_policy.check(policy_repo) == []) is allowed


@pytest.mark.parametrize(
    "path", ["packaging/windows/probe.py", "tools/probe.py", "probe.py", "pogled_assist/a.pyi"]
)
def test_every_python_file_ruff_reads_is_checked(policy_repo, path):
    (policy_repo / path).parent.mkdir(parents=True, exist_ok=True)
    (policy_repo / path).write_text("# ruff: noqa: F401\nimport math\n", encoding="utf-8")

    assert any(path in error for error in check_policy.check(policy_repo))


def test_suppression_examples_in_strings_are_not_directives(policy_repo):
    (policy_repo / "pogled_assist" / "probe.py").write_text(
        'EXAMPLE = "# ruff: noqa: F401"\n', encoding="utf-8"
    )

    assert check_policy.check(policy_repo) == []


def test_unreadable_source_is_reported_instead_of_skipped(policy_repo):
    (policy_repo / "pogled_assist" / "probe.py").write_text('TEXT = """open\n', encoding="utf-8")

    assert any("probe.py" in error for error in check_policy.check(policy_repo))


@pytest.mark.parametrize(
    ("line", "allowed"),
    [
        ("      - uses: actions/checkout@v5 # zizmor: ignore[unpinned-uses]", False),
        ("      # zizmor: ignore[artipacked]", False),
        ("      - run: echo zizmor", True),
    ],
)
def test_workflow_findings_are_accepted_only_in_the_zizmor_configuration(
    policy_repo, line, allowed
):
    workflow = policy_repo / ".github" / "workflows" / "probe.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(f"jobs:\n  probe:\n    steps:\n{line}\n", encoding="utf-8")

    assert (check_policy.check(policy_repo) == []) is allowed


def test_outside_a_git_checkout_the_policy_fails_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_policy, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert check_policy.main() == 1
    assert "Cannot check the exception policy" in capsys.readouterr().out


def test_cli_rejects_a_file_suppression_that_ruff_accepts(policy_repo):
    source = policy_repo / "pogled_assist" / "probe.py"
    source.write_text("# ruff: noqa: F401\nimport math\n", encoding="utf-8")
    script = policy_repo / "scripts" / "checks" / "check_policy.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "checks" / "check_policy.py", script)
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(source)],
        cwd=policy_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    policy = subprocess.run(
        [sys.executable, "-B", "-m", "scripts.checks.check_policy"],
        cwd=policy_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    assert policy.returncode == 1, policy.stdout + policy.stderr
    assert "pogled_assist/probe.py:1" in policy.stdout


def test_policy_rejects_a_file_level_type_relaxation_that_basedpyright_accepts(policy_repo):
    source = policy_repo / "pogled_assist" / "probe.py"
    source.write_text(
        '# pyright: reportReturnType=false\ndef identity(value: int) -> int:\n    return "bad"\n',
        encoding="utf-8",
    )
    (policy_repo / "scripts").mkdir()
    (policy_repo / "run_gaze_mouse.py").write_text("", encoding="utf-8")
    (policy_repo / ".basedpyright").mkdir()
    (policy_repo / ".basedpyright" / "baseline.json").write_text('{"files": {}}', encoding="utf-8")
    types = subprocess.run(
        [sys.executable, "-m", "basedpyright", "--pythonpath", sys.executable],
        cwd=policy_repo,
        env=dict(os.environ, CI="true"),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert types.returncode == 0, types.stdout + types.stderr
    assert any("pogled_assist/probe.py:1" in error for error in check_policy.check(policy_repo))
