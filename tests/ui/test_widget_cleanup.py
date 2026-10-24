from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget


@pytest.fixture
def closed_window(qapp):
    window = QWidget()
    destroyed = []
    window.destroyed.connect(lambda: destroyed.append(True))
    yield window
    assert destroyed == [True]


@pytest.fixture(autouse=True)
def close_top_level_widgets(closed_window, close_top_level_widgets):
    # Resolve the parent fixture after the observer so its teardown runs first.
    return None


def test_cleanup_deletes_closed_windows_before_the_next_test(closed_window):
    closed_window.show()
    closed_window.close()
