from __future__ import annotations

from dataclasses import replace

from _speech_fakes import FakeLibraryStore as FakeLibraryStore
from _speech_fakes import FakeSpeech as FakeSpeech
from _speech_fakes import grouped_fake_speech as grouped_fake_speech
from PySide6.QtCore import QObject, QRect, Signal

from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


class FakeAlarmSound(QObject):
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.start_calls = 0
        self.stop_calls = 0
        self.start_result = True
        self.last_error = None

    def start(self):
        self.start_calls += 1
        return self.start_result

    def stop(self):
        self.stop_calls += 1


class FakeSelectionSound(QObject):
    def __init__(self):
        super().__init__()
        self.levels = []

    def play(self, level):
        self.levels.append(level)


def click_speech_action(qtbot, window, command):
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    qtbot.waitUntil(button.isVisible)
    button.click()


class FakeKeyboardInput:
    def __init__(self):
        self.typed = []
        self.pressed = []

    def foreground_window(self):
        return 50

    def belongs_to_current_process(self, _hwnd):
        return False

    def type_text(self, text):
        self.typed.append(text)

    def press_key(self, key):
        self.pressed.append(key)

    def is_window(self, _hwnd):
        return True

    def set_foreground_window(self, _hwnd):
        return True


class FakeControllerInput(FakeKeyboardInput):
    def __init__(self):
        super().__init__()
        self.clicks = []
        self.scrolls = []

    def click(self, x, y, **options):
        self.clicks.append((x, y, options))

    def click_current(self, **options):
        self.clicks.append((None, None, options))

    def scroll(self, units):
        self.scrolls.append(units)


class FakeAppBar:
    supported = False

    def register(self, *_args, **_kwargs):
        return False

    def unregister(self):
        return None

    def set_position(self, *_args):
        return None


class StaleWorkArea:
    """Primary screen whose work area, like Qt's cache, changes only after events run.

    Qt reads the Windows work area again only when its event loop handles
    WM_SETTINGCHANGE, so code running in the same call still sees the old value.
    """

    def __init__(self, rect: QRect):
        self._screen = QRect(rect)
        self._cached = QRect(rect)
        self.right_reservations: dict[int, int] = {}

    def primaryScreen(self):
        return self

    def geometry(self) -> QRect:
        return QRect(self._screen)

    def availableGeometry(self) -> QRect:
        return QRect(self._cached)

    def process_events(self) -> None:
        reserved = sum(self.right_reservations.values())
        self._cached = self._screen.adjusted(0, 0, -reserved, 0)

    def app_bar(self):
        return WorkAreaAppBar(self)


class WorkAreaAppBar:
    """Right-edge AppBar that reserves its width in a StaleWorkArea."""

    supported = True

    def __init__(self, area: StaleWorkArea):
        self._area = area

    def register(self, _hwnd, size, **_kwargs):
        self._area.right_reservations[id(self)] = size
        return True

    def unregister(self):
        self._area.right_reservations.pop(id(self), None)

    def set_position(self, *_args):
        return None


class FakeHotbarInput(FakeControllerInput):
    def __init__(self):
        super().__init__()
        self.moves = []

    def move_to(self, x, y):
        self.moves.append((x, y))

    def cursor_position(self):
        return 600, 500


class FakeSpeechService(FakeSpeech):
    available = True

    def update_settings(self, settings):
        self._settings = replace(settings)

    def stop(self):
        return None
