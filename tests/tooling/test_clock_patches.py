from __future__ import annotations

import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
HELPER = TESTS / "_clock.py"
PROCESS_WIDE_CLOCK_PATCH = re.compile(
    r"setattr\(\s*(?:"
    r'"(?:[\w.]+\.)?time\.monotonic"'
    r"|(?:[\w.]+\.)?time\s*,\s*[\"']monotonic[\"']"
    r")"
)


def process_wide_clock_patches(source: str) -> list[int]:
    return [
        source.count("\n", 0, match.start()) + 1
        for match in PROCESS_WIDE_CLOCK_PATCH.finditer(source)
    ]


def test_tests_replace_the_process_clock_only_through_the_shared_helper() -> None:
    offenders = [
        f"{path.relative_to(TESTS).as_posix()}:{line}"
        for path in sorted(TESTS.rglob("*.py"))
        if path not in (HELPER, Path(__file__).resolve())
        for line in process_wide_clock_patches(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "Use freeze_monotonic from tests/_clock.py, or replace only one module's "
        "time attribute with SimpleNamespace(monotonic=...)."
    )


@pytest.mark.parametrize(
    "source",
    [
        'monkeypatch.setattr("pogled_assist.ui.quick_action_zoom.time.monotonic", '
        "lambda: next(times))",
        'monkeypatch.setattr(\n    "pogled_assist.tracking.gaze_provider.time.monotonic", clock\n)',
        'monkeypatch.setattr(diagnostics.time, "monotonic", lambda: now[0])',
        "monkeypatch.setattr(time, 'monotonic', clock)",
        'monkeypatch.setattr("time.monotonic", clock)',
    ],
)
def test_clock_check_rejects_process_wide_replacements(source: str) -> None:
    assert process_wide_clock_patches(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "now = freeze_monotonic(monkeypatch, 10.0)",
        'monkeypatch.setattr(diagnostics, "time", SimpleNamespace(monotonic=lambda: now[0]))',
        "audio = client.synthesize(config, text, threading.Event(), time.monotonic() + 5)",
    ],
)
def test_clock_check_accepts_helper_and_single_module_replacements(source: str) -> None:
    assert process_wide_clock_patches(source) == []
