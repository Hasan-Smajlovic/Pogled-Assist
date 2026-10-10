"""Render deterministic screenshots of the main UI surfaces without hardware."""

from __future__ import annotations

import argparse
import os
import time
from contextlib import ExitStack
from dataclasses import replace
from html import escape
from pathlib import Path
from unittest.mock import patch

if os.name == "nt":
    font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if font_directory.is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", str(font_directory))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from pogled_assist import toolbar as toolbar_module
from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.keyboard_layouts import ARABIC_MARKS, ARABIC_SCRIPT
from pogled_assist.speech.speech_library import PhraseRecord, SpeechLibrary, default_categories
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.suggestions.learning import LearningStore
from pogled_assist.suggestions.model import WordModel
from pogled_assist.suggestions.text import START
from pogled_assist.tracking.feedback import TrackingNotice
from pogled_assist.tracking.gaze_check import CheckSnapshot, FixationCheck, FixationResult
from pogled_assist.tracking.status import TrackingState, TrackingStatus
from pogled_assist.ui import settings_window as settings_module
from pogled_assist.ui import sidebar_panel as sidebar_module
from pogled_assist.ui.controller_window import ControllerWindow
from pogled_assist.ui.gaze_check_views import TARGETS
from pogled_assist.ui.gaze_check_window import GazeCheckWindow
from pogled_assist.ui.keyboard_window import KeyboardWindow
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.ui.speech_window import SpeechWindow


class PreviewAppBar:
    supported = False

    def register(self, *_args: object, **_kwargs: object) -> bool:
        return False

    def unregister(self) -> None:
        return None

    def set_position(self, *_args: object) -> None:
        return None


class PreviewInput:
    def foreground_window(self) -> None:
        return None

    def belongs_to_current_process(self, _hwnd: object) -> bool:
        return False

    def cursor_position(self) -> tuple[int, int]:
        return 640, 360


class PreviewSpeech(QObject):
    playback_changed = Signal(int, str)
    available = True

    def __init__(self) -> None:
        super().__init__()
        self.request_id = 0
        self._settings = SpeechSettings()

    @property
    def settings(self) -> SpeechSettings:
        return replace(self._settings)

    def update_settings(self, settings: SpeechSettings) -> None:
        self._settings = replace(settings)

    def speak(self, _text: str, settings: SpeechSettings | None = None) -> bool:
        if settings is not None:
            self._settings = replace(settings)
        return True

    def stop(self) -> None:
        return None


class PreviewAlarmSound(QObject):
    failed = Signal(str)

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        return None

    @property
    def last_error(self) -> str | None:
        return None


class PreviewSuggestionService(QObject):
    predictions_ready = Signal(object, int, object)
    status_changed = Signal(str)
    storage_finished = Signal(bool)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__()
        self.store = LearningStore()
        self.store.learn_text("Ćevapi džez kahva ljeto njiva šetnja")
        self._model = WordModel(
            {
                ("selam",): 100,
                ("ja",): 90,
                ("kako",): 80,
                ("može",): 70,
                ("hvala",): 60,
                ("želim",): 50,
                ("vodu",): 40,
                (START, "selam"): 1000,
                (START, "ja"): 900,
                (START, "kako"): 800,
                (START, "može"): 700,
                (START, "hvala"): 600,
                ("želim", "vodu"): 1000,
            }
        )

    @property
    def status(self) -> str:
        return self.store.error

    def request(self, owner: object, revision: int, text: str) -> None:
        self.predictions_ready.emit(
            owner, revision, self._model.predict(text, self.store.snapshot())
        )

    def persist(self) -> None:
        return None

    def forget(self, word: str) -> None:
        self.store.forget(word)
        self.storage_finished.emit(True)

    def retry(self) -> None:
        self.storage_finished.emit(True)

    def close(self) -> None:
        return None


class PreviewLibraryStore:
    read_error = False

    def __init__(self, phrases: list[PhraseRecord]) -> None:
        self._library = SpeechLibrary(
            categories=default_categories(),
            phrases=phrases,
        )

    def load(self) -> SpeechLibrary:
        return self._library

    def save(self, _library: SpeechLibrary) -> bool:
        return True


class PreviewHotbar(toolbar_module.HotbarWindow):
    def _start_services(self) -> None:
        self._tracking_status.set_tracking_status(
            TrackingStatus(TrackingState.CONNECTED, "UI preview")
        )
        self._tracking_status.set_eye_status(True, True)
        self._tracking_status.handle_gaze(0.5, 0.5, 0)
        self._set_status("UI preview: hardware and Windows input are disabled.")


def _capture_widget(
    app: QApplication,
    widget: QWidget,
    output_dir: Path,
    name: str,
    width: int,
    height: int,
) -> Path:
    # Re-show each state so reused native windows apply child visibility changes.
    widget.hide()
    widget.resize(width, height)
    widget.show()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    widget.resize(width, height)
    if widget.layout() is not None:
        # Reused native windows can retain the previous tab's cached geometry.
        widget.layout().invalidate()
        widget.layout().activate()
    widget.repaint()
    app.processEvents()

    image_path = output_dir / f"{name}.png"
    # A first native grab can finish pending child visibility/layout changes.
    widget.grab()
    app.processEvents()
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(image_path), "PNG"):
        raise RuntimeError(f"Could not render UI snapshot: {name}")
    return image_path


def _write_gallery(output_dir: Path, snapshots: list[tuple[str, Path]]) -> Path:
    cards = "\n".join(
        f'<article><h2>{escape(title)}</h2><a href="{path.name}">'
        f'<img src="{path.name}" alt="{escape(title)}"></a></article>'
        for title, path in snapshots
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pogled Assist UI preview</title>
  <style>
    body {{ margin: 0; padding: 32px; background: #0c0e12; color: #f6f7fb;
      font-family: "Segoe UI", Arial, sans-serif; }}
    header {{ max-width: 900px; margin: 0 auto 32px; }}
    h1 {{ margin-bottom: 8px; }}
    p {{ color: #aeb8c8; }}
    main {{ display: grid; gap: 24px; }}
    article {{ overflow: hidden; border: 1px solid #303746; border-radius: 12px;
      background: #151923; }}
    h2 {{ margin: 0; padding: 14px 18px; font-size: 16px; }}
    a {{ display: block; overflow: auto; background: #08090c; }}
    img {{ display: block; max-width: 100%; height: auto; margin: 0 auto; }}
  </style>
</head>
<body>
  <header>
    <h1>Pogled Assist UI preview</h1>
    <p>Generated from the real Qt widgets with hardware and Windows input disabled.</p>
  </header>
  <main>{cards}</main>
</body>
</html>
"""
    gallery_path = output_dir / "index.html"
    gallery_path.write_text(document, encoding="utf-8")
    return gallery_path


def capture_ui(output_dir: Path, *, width: int = 1440, height: int = 900) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["capture-ui"])
    session = _CaptureSession(app, output_dir, (width, height))
    with ExitStack() as stack:
        for active_patch in session.patches():
            stack.enter_context(active_patch)
        try:
            session.capture_hotbar()
            session.capture_settings()
            session.capture_gaze_check()
            session.capture_speech()
            session.capture_sidebars()
            session.capture_arabic()
        finally:
            session.close()
    _write_gallery(output_dir, session.snapshots)
    return [path for _, path in session.snapshots]


class _CaptureSession:
    """Keep preview windows alive until all states have been captured."""

    def __init__(self, app: QApplication, output_dir: Path, size: tuple[int, int]) -> None:
        self.app = app
        self.output_dir = output_dir
        self.size = size
        self.gaze_settings = GazeSettings()
        self.speech_settings = SpeechSettings()
        self.widgets: list[QWidget] = []
        self.snapshots: list[tuple[str, Path]] = []

    def patches(self) -> tuple:
        return (
            patch.object(toolbar_module, "WindowsAppBar", PreviewAppBar),
            patch.object(toolbar_module, "WindowsInputController", PreviewInput),
            patch.object(toolbar_module, "SpeechService", PreviewSpeech),
            patch.object(toolbar_module, "SuggestionService", PreviewSuggestionService),
            patch.object(
                toolbar_module,
                "load_app_settings",
                return_value=(self.gaze_settings, self.speech_settings),
            ),
            patch.object(sidebar_module, "WindowsAppBar", PreviewAppBar),
            patch.object(settings_module, "is_windows_startup_enabled", return_value=False),
        )

    def capture(
        self, widget: QWidget, name: str, title: str, *, size: tuple[int, int] | None = None
    ) -> None:
        width, height = self.size if size is None else size
        path = _capture_widget(self.app, widget, self.output_dir, name, width, height)
        self.snapshots.append((title, path))

    def capture_hotbar(self) -> None:
        hotbar = PreviewHotbar()
        self.widgets.append(hotbar)
        size = min(self.size[0], 1280), hotbar.BAR_HEIGHT
        self.capture(hotbar, "hotbar", "Hotbar", size=size)
        with patch.object(toolbar_module, "save_app_settings", return_value=False):
            hotbar._save_settings()
        self.capture(hotbar, "hotbar-unsaved-settings", "Hotbar: settings not saved", size=size)
        hotbar._settings_button.setText("Postavke")
        for state, name, title in (
            (TrackingState.CONNECTED, "hotbar-paused", "Hotbar: one eye unavailable"),
            (TrackingState.WAITING, "hotbar-waiting", "Hotbar: waiting for fresh data"),
            (TrackingState.RETRYING, "hotbar-retrying", "Hotbar: device not connected"),
            (TrackingState.SIMULATING, "hotbar-simulation", "Hotbar: mouse simulation"),
        ):
            hotbar._tracking_status.set_tracking_status(TrackingStatus(state))
            hotbar._tracking_status.set_eye_status(False, True)
            self.capture(hotbar, name, title, size=size)

    def capture_settings(self) -> None:
        suggestions = PreviewSuggestionService()
        self.settings = SettingsWindow(
            self.gaze_settings, self.speech_settings, suggestions=suggestions
        )
        self.widgets.append(self.settings)
        size = min(self.size[0], 1280), min(self.size[1], 720)
        for index, name, title in (
            (0, "settings-general", "Settings: general"),
            (1, "settings-gaze", "Settings: gaze"),
            (2, "settings-speech", "Settings: speech"),
        ):
            self.settings._select_tab(index)
            self.capture(self.settings, name, title, size=size)
        self.settings._open_learning()
        self.capture(self.settings, "settings-learned-words", "Settings: learned words", size=size)
        self.settings._select_tab(1)
        self.settings.set_save_error(True)
        self.capture(self.settings, "settings-save-error", "Settings: save failed", size=size)
        self.settings.set_save_error(False)

    def capture_gaze_check(self) -> None:
        window = GazeCheckWindow(self.gaze_settings)
        self.widgets.append(window)
        size = min(self.size[0], 1280), min(self.size[1], 720)
        # Static synthetic data and frozen UI ticks keep the gallery deterministic.
        window._timer.timeout.disconnect(window._tick)
        self.capture(window, "gaze-check-unavailable", "Gaze check: data unavailable", size=size)
        window._snapshot = CheckSnapshot(position_supported=False)
        window._render_position()
        self.capture(
            window, "gaze-check-unsupported", "Gaze check: eye positions unsupported", size=size
        )
        window.handle_tracking_status(TrackingStatus(TrackingState.RETRYING))
        self.capture(window, "gaze-check-disconnected", "Gaze check: disconnected", size=size)
        window.handle_tracking_status(TrackingStatus(TrackingState.CONNECTED))
        window._snapshot = CheckSnapshot(
            True,
            True,
            (0.6, 0.5, 0.45),
            (0.4, 0.5, 0.45),
            gaze=(0.5, 0.5),
            observed_seconds=10,
            available_fraction=0.98,
            longest_loss_seconds=0.15,
        )
        window._render_position()
        self.capture(window, "gaze-check-position", "Gaze check: live position", size=size)
        window._snapshot = replace(
            window._snapshot,
            left=False,
            right=False,
            gaze=None,
            available_fraction=0.6,
            longest_loss_seconds=1.1,
        )
        window._render_position()
        self.capture(
            window,
            "gaze-check-position-without-gaze",
            "Gaze check: eye positions without valid gaze",
            size=size,
        )
        waiting_snapshot = window._snapshot
        for name, title, left, right in (
            ("too-close", "move display away", (0.6, 0.5, -0.2), (0.4, 0.5, -0.1)),
            ("too-far", "move display closer", (0.6, 0.5, 1.2), (0.4, 0.5, 1.1)),
            ("outside-frame", "align display", (1.2, -0.1, 0.5), (1.1, -0.1, 0.5)),
        ):
            window._snapshot = replace(waiting_snapshot, left_position=left, right_position=right)
            window._render_position()
            self.capture(window, f"gaze-check-{name}", f"Gaze check: {title}", size=size)
        window._snapshot = replace(
            waiting_snapshot,
            left=True,
            right_position=None,
        )
        window._render_position()
        self.capture(window, "gaze-check-interrupted", "Gaze check: eye loss", size=size)
        window._start_precision()
        self.capture(window, "gaze-check-precision", "Gaze check: fixation target", size=size)
        window._snapshot = CheckSnapshot(True, False)
        window._snapshot_at = time.monotonic()
        window._check.started_at = time.monotonic() - 1.2
        window._tick()
        self.capture(
            window, "gaze-check-precision-waiting", "Gaze check: fixation eye loss", size=size
        )
        targets = list(TARGETS)
        window._check = FixationCheck(targets, size, 36, 0)
        window._check.results = [
            FixationResult(name, 90, 0.9 if near is not None else 0.2, error, spread, near, center)
            for name, error, spread, near, center in (
                ("Sredina", 12, 8, True, (0.51, 0.5)),
                ("Gore lijevo", 14, 10, True, (0.05, 0.07)),
                ("Gore desno", 48, 12, False, (0.92, 0.09)),
                ("Dolje lijevo", 18, 9, True, (0.05, 0.93)),
                ("Dolje desno", None, None, None, None),
            )
        ]
        window._show_results()
        self.capture(window, "gaze-check-results", "Gaze check: measured results", size=size)
        window._details_button.click()
        self.capture(
            window, "gaze-check-results-details", "Gaze check: optional measurements", size=size
        )
        window._details_button.click()
        window._check.results[-1] = FixationResult(
            "Dolje desno", 90, 0.9, 48, 12, False, (0.92, 0.9)
        )
        window._show_results()
        self.capture(window, "gaze-check-results-misses", "Gaze check: measured misses", size=size)
        window._check.results = [
            FixationResult(name, 90, 0.9, 12, 8, True, (x, y)) for name, x, y in targets
        ]
        window._show_results()
        self.capture(window, "gaze-check-results-ready", "Gaze check: targets passed", size=size)
        window._start_trial()
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(window, "gaze-check-trial", "Gaze check: local dwell trial", size=size)
        window._selection.update(
            window._target.expected_button,
            time.monotonic() * 1000,
            pause_ms=500,
            dwell_ms=500,
        )
        window.handle_eye_status(True, False)
        self.capture(
            window, "gaze-check-trial-interrupted", "Gaze check: cancelled selection", size=size
        )
        wrong = window._target.mapToGlobal(window._target.button_rect(0).center())
        screen = QGuiApplication.primaryScreen().geometry()
        gaze = (
            (wrong.x() - screen.left()) / (screen.width() - 1),
            (wrong.y() - screen.top()) / (screen.height() - 1),
        )
        start = time.monotonic()
        duration = (self.gaze_settings.selection_pause_ms + self.gaze_settings.dwell_ms) / 1000
        for sample in range(round(duration / 0.02) + 3):
            at = start + sample * 0.02
            window._trial_sample(CheckSnapshot(True, True, gaze=gaze, gaze_at=at), at)
        self.capture(window, "gaze-check-trial-wrong", "Gaze check: neighbor selected", size=size)
        window._finish_trial_target(True, time.monotonic())
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(
            window, "gaze-check-trial-keyboard", "Gaze check: keyboard-sized neighbors", size=size
        )
        window._finish_trial_target(True, time.monotonic())
        window._target.progress = 0.6
        window._target.progress_target = window._target.expected_button
        self.capture(
            window, "gaze-check-trial-words", "Gaze check: suggestion-sized neighbors", size=size
        )
        window._finish_trial_target(False, time.monotonic())
        window._trial_gaze_targets = {0, 1, 2}
        window._show_results()
        self.capture(
            window, "gaze-check-trial-results", "Gaze check: trial needs adjustment", size=size
        )
        window._trial_results = [True] * 3
        window._trial_losses = window._trial_wrong_selections = 0
        window._show_results()
        self.capture(
            window, "gaze-check-results-complete", "Gaze check: targets and trial passed", size=size
        )
        window._start_trial()
        for _ in range(3):
            window._finish_trial_target(False, time.monotonic())
        self.capture(
            window, "gaze-check-trial-no-gaze", "Gaze check: trial without gaze data", size=size
        )
        window._start_free()
        screen = QGuiApplication.primaryScreen().geometry()
        point = window._target.mapToGlobal(window._target.rect().center() + QPoint(16, -10))
        window._snapshot = CheckSnapshot(
            True,
            True,
            gaze=(
                (point.x() - screen.left()) / (screen.width() - 1),
                (point.y() - screen.top()) / (screen.height() - 1),
            ),
            gaze_at=time.monotonic(),
        )
        window._render_free()
        self.capture(window, "gaze-check-free", "Gaze check: nine live targets", size=size)
        window._snapshot = CheckSnapshot()
        window._render_free()
        self.capture(
            window, "gaze-check-free-waiting", "Gaze check: free check waiting for gaze", size=size
        )

    def capture_speech(self) -> None:
        sample_phrases = [
            PhraseRecord("Trebam pomoć", 8),
            PhraseRecord("Molim vas sačekajte", 5),
            PhraseRecord("Hvala", 3),
        ]
        suggestions = PreviewSuggestionService()
        suggestions.store = LearningStore()
        self.speech = SpeechWindow(
            PreviewSpeech(),
            library_store=PreviewLibraryStore(sample_phrases),
            alarm_sound=PreviewAlarmSound(),
            suggestions=suggestions,
        )
        self.widgets.append(self.speech)
        self.capture(self.speech, "speech", "Speech keyboard")
        self.capture_tracking_feedback()
        self.speech._view_mode = "categories"
        self.speech._show_list_level()
        self.capture(self.speech, "speech-categories", "Speech categories")
        self.speech._category_index = 0
        self.speech._view_mode = "answers"
        self.speech._show_list_level()
        self.capture(self.speech, "speech-answers", "Speech category answers")
        self.speech._view_mode = "phrases"
        self.speech._category_index = None
        self.speech._show_list_level()
        self.capture(self.speech, "phrases", "Saved phrases")
        self.speech._library_store.read_error = True
        self.speech._show_list_level()
        self.capture(
            self.speech, "speech-library-read-error", "Speech: library not loaded", size=(1280, 720)
        )
        self.speech._library_store.read_error = False
        self.speech._show_list_level()
        self.speech._start_editor()
        self.capture(self.speech, "speech-editor", "Speech shared editor")
        self.capture_speech_dialogs()

    def capture_dialog(self, dialog: QWidget, name: str, title: str) -> None:
        self.capture(dialog, name, title, size=(dialog.width(), dialog.height()))

    def capture_tracking_feedback(self) -> None:
        self.speech._input.setText("TREBAM VODE")
        for name, notice in (
            (
                "warning",
                TrackingNotice(
                    "Desno oko se trenutno ne prati", "odabir je zaustavljen", eyes=(True, False)
                ),
            ),
            (
                "waiting",
                TrackingNotice(
                    "Čekam podatke o pogledu", "odabir je zaustavljen", "quiet", (True, True)
                ),
            ),
            ("disconnected", TrackingNotice("Uređaj nije povezan", "pokušavam ponovo", "error")),
            (
                "frequent",
                TrackingNotice(
                    "Praćenje često prekida", "provjerite položaj uređaja", eyes=(True, True)
                ),
            ),
            ("recovered", TrackingNotice("Možete nastaviti", tone="ready", eyes=(True, True))),
        ):
            self.speech.set_tracking_notice(notice, immediate=True)
            self.capture(self.speech, f"speech-tracking-{name}", f"Speech tracking: {name}")
        self.speech._open_letter_dialog(0)
        self.speech.set_tracking_notice(
            TrackingNotice(
                "Desno oko se trenutno ne prati", "odabir je zaustavljen", eyes=(True, False)
            ),
            immediate=True,
        )
        self.capture_dialog(
            self.speech._dialogs.letter,
            "speech-tracking-letters",
            "Speech letters: tracking interrupted",
        )
        self.speech._close_dialog()
        self.speech._open_clear_dialog()
        self.speech.set_tracking_notice(
            TrackingNotice(
                "Lijevo oko se trenutno ne prati", "odabir je zaustavljen", eyes=(False, True)
            ),
            immediate=True,
        )
        self.capture_dialog(
            self.speech._dialogs.confirm,
            "speech-tracking-confirm",
            "Clear message: tracking interrupted",
        )
        self.speech._close_dialog()
        self.speech.set_tracking_notice(None, immediate=True)
        self.speech._input.clear()

    def capture_speech_dialogs(self) -> None:
        self.speech._start_alarm()
        self.capture_dialog(self.speech._dialogs.alarm, "speech-alarm", "Speech alarm")
        self.speech._stop_alarm()
        self.speech._start_sleep()
        self.capture(self.speech._dialogs.sleep, "speech-sleep", "Speech sleep")
        self.speech._wake_from_sleep()
        self.speech._open_exit_dialog()
        self.capture_dialog(self.speech._dialogs.exit, "speech-exit", "Speech exit confirmation")
        self.speech._close_dialog()

    def capture_sidebars(self) -> None:
        size = 380, self.size[1]
        self.keyboard = KeyboardWindow(self.speech_settings)
        self.widgets.append(self.keyboard)
        for show, name, title in (
            (None, "keyboard-letters", "Keyboard: letters"),
            (self.keyboard._show_numpad, "keyboard-numpad", "Keyboard: numpad"),
            (self.keyboard._show_symbols, "keyboard-symbols", "Keyboard: symbols"),
        ):
            if show is not None:
                show()
            self.capture(self.keyboard, name, title, size=size)
        self.controller = ControllerWindow(self.gaze_settings, self.speech_settings)
        self.widgets.append(self.controller)
        for show, name, title in (
            (None, "controller-general", "Controller: general"),
            (self.controller._show_keyboard_tab, "controller-keyboard", "Controller: keyboard"),
            (self.controller._show_settings_tab, "controller-settings", "Controller: settings"),
        ):
            if show is not None:
                show()
            self.capture(self.controller, name, title, size=size)
        small_groups = replace(self.speech_settings, letters_per_group=2)
        self.keyboard.update_settings(small_groups)
        self.controller.update_speech_settings(small_groups)
        self.controller._show_keyboard_tab()
        for widget, name, title in (
            (self.keyboard, "keyboard-latin-paged", "Keyboard: Latin, two letters per group"),
            (
                self.controller,
                "controller-latin-paged",
                "Controller: Latin, two letters per group",
            ),
        ):
            self.capture(widget, name, title, size=(380, 640))

    def capture_arabic(self) -> None:
        # Arabic uses the same services and storage fakes, with original Unicode.
        arabic_settings = replace(self.speech_settings, keyboard_script=ARABIC_SCRIPT)
        self.settings.update_speech_settings(arabic_settings)
        self.settings._select_tab(2)
        size = min(self.size[0], 1280), min(self.size[1], 720)
        self.capture(self.settings, "settings-arabic", "Settings: Arabic", size=size)
        self.capture_arabic_speech(arabic_settings)
        self.capture_arabic_sidebars(arabic_settings)

    def capture_arabic_speech(self, settings: SpeechSettings) -> None:
        self.speech._cancel_editor()
        self.speech.update_settings(settings)
        self.speech._view_mode = "keyboard"
        self.speech._show_group_level()
        self.speech._input.setText("سَلَامٌ · SELAM · ١٢٣")
        self.capture(self.speech, "speech-arabic", "Speech: Arabic")
        self.speech._open_letter_dialog(0)
        self.capture_dialog(
            self.speech._dialogs.letter, "speech-arabic-letters", "Speech: Arabic letters"
        )
        self.speech._close_dialog()
        self.speech._show_symbols_level()
        self.capture(self.speech, "speech-arabic-symbols", "Speech: Arabic symbols")
        mark_group = next(
            index
            for index, keys in enumerate(self.speech._symbol_groups)
            if all(key in ARABIC_MARKS for key in keys)
        )
        self.speech._open_letter_dialog(mark_group, symbols=True)
        self.capture_dialog(
            self.speech._dialogs.letter, "speech-arabic-marks", "Speech: Arabic vowel marks"
        )
        self.speech._close_dialog()
        self.speech._view_mode = "phrases"
        self.speech._show_list_level()
        self.speech._start_editor()
        self.speech._input.setText("سَلَامٌ")
        self.capture(self.speech, "speech-arabic-editor", "Speech: Arabic editor")

    def capture_arabic_sidebars(self, settings: SpeechSettings) -> None:
        size = 380, self.size[1]
        self.keyboard.update_settings(settings)
        self.keyboard._show_letter_groups()
        self.capture(self.keyboard, "keyboard-arabic", "Keyboard: Arabic", size=size)
        self.keyboard._show_symbols()
        self.keyboard._group_page = 1
        self.keyboard._show_symbols()
        self.capture(
            self.keyboard, "keyboard-arabic-symbols", "Keyboard: Arabic symbols, page 2", size=size
        )
        self.controller.update_speech_settings(settings)
        self.controller._show_keyboard_tab()
        self.capture(self.controller, "controller-arabic", "Controller: Arabic keyboard", size=size)
        self.controller._show_keyboard_symbols()
        self.controller._keyboard_group_page = 1
        self.controller._show_keyboard_symbols()
        self.capture(
            self.controller,
            "controller-arabic-symbols",
            "Controller: Arabic symbols, page 2",
            size=size,
        )

    def close(self) -> None:
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        self.app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/ui-preview"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    arguments = parser.parse_args()

    snapshots = capture_ui(
        arguments.output.resolve(), width=arguments.width, height=arguments.height
    )
    print(f"Rendered {len(snapshots)} UI snapshots: {arguments.output.resolve() / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
