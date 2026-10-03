from __future__ import annotations

from _ui_fakes import FakeHotbarInput
from PySide6.QtWidgets import QWidget

from pogled_assist.windows.foreground_tracker import ForegroundTracker


class FakeSurface:
    def __init__(self):
        self.over_ui = False
        self.windows = []
        self.cursors = []

    def contains_global_point(self, _point):
        return self.over_ui

    def set_external_window(self, hwnd):
        self.windows.append(hwnd)

    def set_external_cursor(self, position):
        self.cursors.append(position)


def test_foreground_tracker_keeps_external_window_and_cursor_over_application_ui(
    qtbot, monkeypatch
):
    parent = QWidget()
    qtbot.addWidget(parent)
    api = FakeHotbarInput()
    surface = FakeSurface()
    tracker = ForegroundTracker(parent, surface, lambda: api)
    tracker.prime()

    assert tracker.window == 50
    assert tracker.cursor == (600, 500)
    assert surface.windows == [50]
    assert surface.cursors == [(600, 500)]

    surface.over_ui = True
    monkeypatch.setattr(api, "foreground_window", lambda: 99)
    monkeypatch.setattr(api, "belongs_to_current_process", lambda _hwnd: True)
    monkeypatch.setattr(api, "cursor_position", lambda: (100, 100))
    tracker.update()

    assert tracker.window == 50
    assert tracker.cursor == (600, 500)
    assert surface.windows == [50]
    assert surface.cursors == [(600, 500)]


def test_foreground_tracker_stops_polling_on_input_failure(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    api = FakeHotbarInput()
    tracker = ForegroundTracker(parent, FakeSurface(), lambda: api)
    messages = []
    tracker.status_changed.connect(messages.append)
    tracker.start()
    assert tracker._timer.isActive()

    def fail():
        raise OSError("window disappeared")

    monkeypatch.setattr(api, "foreground_window", fail)
    tracker.update()

    assert not tracker._timer.isActive()
    assert tracker.window == 50
    assert tracker.cursor == (600, 500)
    assert messages == ["Praćenje aktivnog prozora je zaustavljeno zbog greške."]
