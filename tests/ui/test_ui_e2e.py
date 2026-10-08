from __future__ import annotations

import pytest
from _speech_fixtures import make_speech_window as make_speech_window
from _ui_fakes import FakeAppBar, FakeControllerInput, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.controller_window import CONTROLLER_WINDOW_ACTION_PREFIX, ControllerWindow
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.fixture
def gaze_check(qtbot, monkeypatch):
    from types import SimpleNamespace

    from pogled_assist.ui import gaze_check_window as module

    screen = QRect(-100, 20, 1280, 720)
    monkeypatch.setattr(
        module.QGuiApplication, "primaryScreen", lambda: SimpleNamespace(geometry=lambda: screen)
    )
    window = module.GazeCheckWindow(GazeSettings())
    qtbot.addWidget(window)
    window.setGeometry(screen)
    window.show()
    qtbot.wait(1)
    window._timer.stop()
    now = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    return window, now, screen


@pytest.mark.e2e
def test_gaze_check_live_states_and_timeout_are_not_false_successes(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window.handle_snapshot(
        CheckSnapshot(
            True,
            True,
            (0.6, 0.5, 0.5),
            (0.4, 0.5, 0.5),
            gaze=(0.5, 0.5),
            gaze_at=now[0],
            observed_seconds=5,
            available_fraction=0.98,
            longest_loss_seconds=0.1,
        )
    )
    window._tick()
    assert window._distance_label.text().startswith("✓")
    assert window._left_label.text().startswith("✓")
    now[0] += 0.6
    window._tick()
    assert window._distance_label.text().startswith("—")
    assert window._left_label.text().startswith("—")
    window.handle_snapshot(CheckSnapshot(True, False))
    window._tick()
    assert window._right_label.text().startswith("!")
    assert window._distance_label.text().startswith("—")


@pytest.mark.e2e
def test_gaze_check_runs_five_targets_without_any_gaze_click(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._primary_button.click()
    qtbot.wait(1)
    assert window._phase == "precision"
    assert window._check is not None
    for index in range(5):
        name, x, y = window._check.targets[index]
        start = window._check.started_at
        for sample in range(100):
            now[0] = start + 1 + sample * 0.02
            window.handle_snapshot(CheckSnapshot(True, True, gaze=(x, y), gaze_at=now[0]))
        now[0] = start + 3.01
        window._tick()
        assert window._check.results[index].name == name
        assert window._check.results[index].near is True
    assert window._phase == "results"
    assert "5 od 5" in window._result_summary.text()
    window._repeat_button.click()
    assert window._check is None
    assert window._phase == "position"


@pytest.mark.e2e
def test_precision_does_not_bridge_coalesced_eye_losses(gaze_check, qtbot):
    import threading

    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider

    window, now, _screen = gaze_check
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    gaze, eyes = provider._new_stream_callbacks()
    provider.eye_status_changed.connect(window.handle_eye_status)
    provider.diagnostics_updated.connect(window.handle_snapshot)
    window._primary_button.click()
    qtbot.wait(1)
    start = window._check.started_at
    _name, x, y = window._check.targets[0]

    def feed(at):
        now[0] = at - 0.09
        eyes(False, True, 0)
        now[0] = at
        eyes(True, True, 0)
        gaze(x, y, 0)

    for sample in range(20):
        # Both eye events arrive before Qt delivers the next valid snapshot.
        thread = threading.Thread(target=feed, args=(start + 1 + sample * 0.1,))
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        provider._emit_latest_gaze_sample()
    now[0] = start + 3.01
    window._tick()
    result = window._check.results[0]
    assert result.samples == 20
    assert result.coverage == 0
    assert result.near is None
    window._show_results()
    assert "nedovoljno podataka" in window._result_detail.text()


@pytest.mark.e2e
def test_research_eye_positions_remain_visible_without_enabling_gaze(gaze_check):
    from pogled_assist.tracking.gaze_provider import TobiiGazeProvider

    window, now, _screen = gaze_check
    provider = TobiiGazeProvider()
    provider.set_check_active(True)
    provider.eye_status_changed.connect(window.handle_eye_status)
    provider.diagnostics_updated.connect(window.handle_snapshot)
    delivered = []
    provider.gaze_updated.connect(lambda *sample: delivered.append(sample))
    data = {
        "left_gaze_point_validity": 0,
        "right_gaze_point_validity": 0,
        "left_gaze_point_on_display_area": (0.5, 0.5),
        "right_gaze_point_on_display_area": (0.5, 0.5),
        "left_gaze_origin_validity": 1,
        "right_gaze_origin_validity": 1,
        "left_gaze_origin_in_trackbox_coordinate_system": (0.4, 0.5, 0.6),
        "right_gaze_origin_in_trackbox_coordinate_system": (0.6, 0.5, 0.6),
    }
    provider._on_gaze_data(data)
    provider._emit_latest_gaze_sample()
    window._tick()
    assert window._left_label.text().startswith("✓")
    assert window._right_label.text().startswith("✓")
    assert window._distance_label.text().startswith("✓")
    assert window._eyes_view.snapshot.left_position == (0.4, 0.5, 0.6)
    assert window._gaze_label.text().endswith("Čekam položaj pogleda")
    assert "Oči su prepoznate" in window._guidance.text()
    assert window._snapshot.left is window._snapshot.right is False
    assert window._snapshot.gaze is None
    assert delivered == []
    window._start_trial()
    for _ in range(100):
        now[0] += 0.02
        provider._on_gaze_data(data)
        provider._emit_latest_gaze_sample()
    assert window._trial_results == []
    assert window._target.progress == 0
    assert delivered == []


@pytest.mark.e2e
def test_precision_targets_use_final_geometry_and_unclamped_logical_screen(gaze_check, qtbot):
    window, _now, screen = gaze_check
    window._primary_button.click()
    qtbot.wait(1)
    for index, (_name, x, y) in enumerate(window._check.targets):
        window._target.target_index = index
        painted = window._target.mapToGlobal(window._target.center())
        assert abs(painted.x() - (screen.left() + x * (screen.width() - 1))) <= 1
        assert abs(painted.y() - (screen.top() + y * (screen.height() - 1))) <= 1
        if index:
            assert x < 0.06 or x > 0.94
            assert y < 0.08 or y > 0.92
    window.resize(1200, 680)
    qtbot.wait(1)
    assert window._phase == "position"
    assert window._check is None


@pytest.mark.e2e
def test_free_check_shows_nine_targets_and_only_fresh_both_eye_gaze(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._free_button.click()
    qtbot.wait(1)
    assert window._phase == "free"
    assert window._check is None
    assert len(window._target.free_centers()) == 9
    controls = window._test_controls.geometry()
    for point in window._target.free_centers():
        assert not controls.adjusted(-36, -36, 36, 36).contains(point)
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.25, 0.75), gaze_at=now[0]))
    expected = window._target.mapFromGlobal(QPoint(
        round(screen.left() + 0.25 * (screen.width() - 1)),
        round(screen.top() + 0.75 * (screen.height() - 1)),
    ))
    assert window._target.gaze_point == expected
    window.handle_eye_status(True, False)
    assert window._target.gaze_point is None
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.25, 0.75), gaze_at=now[0]))
    now[0] += 0.6
    window._tick()
    assert window._target.gaze_point is None
    assert window._phase == "free"
    assert window._check is None
    window._test_back_button.click()
    assert window._phase == "position"
    assert not window._target.isVisible()


@pytest.mark.e2e
def test_trial_counts_wrong_neighbor_once_and_requires_correct_button(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    qtbot.wait(1)
    wrong = window._target.mapToGlobal(window._target.button_rect(0).center())
    gaze = ((wrong.x() - screen.left()) / (screen.width() - 1),
            (wrong.y() - screen.top()) / (screen.height() - 1))
    for sample in range(100):
        now[0] = 10 + sample * 0.02
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))
    assert window._trial_wrong_selections == 1
    assert window._trial_results == []
    assert window._selection.is_blocked
    correct = window._target.mapToGlobal(window._target.center())
    gaze = ((correct.x() - screen.left()) / (screen.width() - 1),
            (correct.y() - screen.top()) / (screen.height() - 1))
    for sample in range(60):
        now[0] = 12 + sample * 0.02
        window.handle_snapshot(CheckSnapshot(True, True, gaze=gaze, gaze_at=now[0]))
    assert window._trial_results == [True]
    assert window._trial_wrong_selections == 1
    assert window._target.button_rect().size().width() == 96


@pytest.mark.e2e
def test_position_copy_distinguishes_unsupported_waiting_and_disconnected(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    window, _now, _screen = gaze_check
    window.handle_snapshot(CheckSnapshot(position_supported=False))
    window._tick()
    assert "ne šalje" in window._position_notice.text()
    window.handle_snapshot(CheckSnapshot(position_supported=True))
    window._tick()
    assert "Čekam svježe" in window._position_notice.text()
    window.handle_tracking_status(TrackingStatus(TrackingState.RETRYING))
    assert "prekinuta" in window._position_notice.text()


@pytest.mark.e2e
def test_trial_cancels_on_eye_loss_and_uses_fresh_samples_to_complete(gaze_check, qtbot):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, screen = gaze_check
    window._start_trial()
    qtbot.wait(1)

    def feed(at):
        now[0] = at
        point = window._target.mapToGlobal(window._target.center())
        x = (point.x() - screen.left()) / (screen.width() - 1)
        y = (point.y() - screen.top()) / (screen.height() - 1)
        window.handle_snapshot(CheckSnapshot(True, True, gaze=(x, y), gaze_at=at))

    for i in range(45):
        feed(10 + i * 0.02)
    assert window._target.progress > 0
    window.handle_eye_status(True, False)
    assert window._target.progress == 0
    assert window._trial_losses == 1
    feed(10.91)
    feed(11.0)
    assert window._trial_results == []
    # Repeating the same gaze sample cannot advance selection.
    now[0] = 11.9
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(0.5, 0.5), gaze_at=11.0))
    assert window._trial_results == []
    for i in range(56):
        feed(12 + i * 0.02)
    assert window._trial_results == [True]
    for _ in range(2):
        start = window._trial_ready_at
        for i in range(56):
            feed(start + i * 0.02)
    assert window._phase == "results"
    assert "3/3" in window._trial_summary.text()


@pytest.mark.e2e
def test_check_disconnect_and_escape_require_no_valid_gaze(gaze_check, qtbot):
    window, _now, _screen = gaze_check
    window._start_precision()
    qtbot.wait(1)
    window.tracking_unavailable()
    assert window._phase == "position"
    assert window._check is None
    assert "prekinuto" in window._notice.text()
    closed = []
    window.closed.connect(lambda: closed.append(True))
    window.activateWindow()
    qtbot.keyClick(window, Qt.Key_Escape)
    assert closed == [True]


@pytest.mark.e2e
def test_trial_offscreen_gaze_does_not_overflow_or_choose_a_button(gaze_check):
    from pogled_assist.tracking.gaze_check import CheckSnapshot

    window, now, _screen = gaze_check
    window._start_trial()
    window.handle_snapshot(CheckSnapshot(True, True, gaze=(1e300, -1e300), gaze_at=now[0]))
    assert window._trial_results == []
    assert window._selection.target is None


@pytest.mark.e2e
def test_check_buttons_and_labels_fit_at_150_percent(gaze_check, qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton

    from pogled_assist.tracking.gaze_check import FixationResult

    window, _now, _screen = gaze_check
    for phase in ("position", "precision", "results", "trial", "free"):
        if phase == "precision":
            window._start_precision()
        elif phase == "results":
            window._check.results = [
                FixationResult(name, 90, 0.9, 12, 8, True, (x, y))
                for name, x, y in window._check.targets
            ]
            window._show_results()
        elif phase == "trial":
            window._start_trial()
        elif phase == "free":
            window._start_free()
        qtbot.wait(1)
        assert (window.width(), window.height()) == (1280, 720)
        for child in window.findChildren(QWidget):
            if not child.isVisible() or not isinstance(child, (QLabel, QPushButton)):
                continue
            bounds = QRect(child.mapTo(window, QPoint(0, 0)), child.size())
            assert window.rect().contains(bounds), (phase, child.text(), bounds)
            if isinstance(child, QPushButton):
                assert child.height() >= 60


@pytest.mark.e2e
@pytest.mark.parametrize("script", ["latin", "arabic"])
@pytest.mark.parametrize("letters_per_group", [2, 5])
@pytest.mark.parametrize("size", [(320, 640), (380, 640), (380, 950)])
def test_controller_keyboard_rows_fill_sidebar_width(
    qtbot, monkeypatch, script, letters_per_group, size
):
    from pogled_assist.ui import sidebar_panel

    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    window = ControllerWindow(
        GazeSettings(),
        SpeechSettings(keyboard_script=script, letters_per_group=letters_per_group),
    )
    qtbot.addWidget(window)
    window._input = FakeControllerInput()
    window.resize(*size)
    window.show()
    prefix = CONTROLLER_WINDOW_ACTION_PREFIX

    def check_row(buttons):
        qtbot.wait(1)
        rects = [QRect(button.mapTo(window, QPoint(0, 0)), button.size()) for button in buttons]
        assert min(rect.left() for rect in rects) == 10
        assert max(rect.right() for rect in rects) == window.width() - 11
        assert max(rect.width() for rect in rects) - min(rect.width() for rect in rects) <= 1
        assert all(window.rect().contains(rect) for rect in rects)
        for button in buttons:
            center = button.mapToGlobal(button.rect().center())
            expected = (
                next(
                    action for action, target in window._action_buttons.items() if target is button
                )
                if button.isEnabled()
                else None
            )
            assert window.action_at_global_point(center) == expected

    window._tab_buttons["keyboard"].click()
    for tab, group_command, key_command in (
        ("letters", "keyboard_group", "keyboard_letter:0"),
        ("numpad", "keyboard_numpad_group", "keyboard_numpad"),
        ("symbols", "keyboard_symbol_group", "keyboard_symbol"),
    ):
        window._keyboard_tab_buttons[tab].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_space", "keyboard_backspace")
            ]
        )
        if f"{prefix}keyboard-page:1" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}keyboard-page:{i}"] for i in (-1, 1)])
            window._action_buttons[f"{prefix}keyboard-page:1"].click()
            check_row(list(window._keyboard_tab_buttons.values()))
            window._action_buttons[f"{prefix}keyboard-page:-1"].click()

        window._action_buttons[f"{prefix}{group_command}:0"].click()
        check_row(list(window._keyboard_tab_buttons.values()))
        if f"{prefix}{key_command}:2" in window._action_buttons:
            check_row([window._action_buttons[f"{prefix}{key_command}:{i}"] for i in range(3)])
        check_row(
            [
                window._action_buttons[f"{prefix}{command}"]
                for command in ("keyboard_groups", "keyboard_space", "keyboard_backspace")
            ]
        )
        window.handle_gaze_action(f"{prefix}{key_command}:0")
        check_row(list(window._keyboard_tab_buttons.values()))
        check_row([window._action_buttons[f"{prefix}{group_command}:{i}"] for i in (0, 1)])

    for tab in ("general", "settings"):
        window._tab_buttons[tab].click()
        qtbot.wait(1)
        buttons = [
            button
            for button in window._action_buttons.values()
            if button.isVisible() and button.objectName() in ("shortcutButton", "checkButton")
        ]
        first_row = [
            button for button in buttons if button.y() == min(target.y() for target in buttons)
        ]
        check_row(first_row)


@pytest.mark.e2e
def test_twelve_letter_dialog_fits_150_percent_display_and_accepts_gaze(qtbot, make_speech_window):
    window = make_speech_window(
        FakeSpeech(), letters_per_group=12, library_store=FakeLibraryStore()
    )
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"].click()
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.letter)
    dialog = window._dialogs.letter
    assert dialog.height() <= window.height() - 64
    assert dialog.width() <= window.width() - 64

    bounds = dialog.rect()
    for action in window._dialogs.letter_actions:
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(dialog, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.width() >= 140, action
        assert button.height() >= 110, action
        assert window.action_at_global_point(button.mapToGlobal(button.rect().center())) == action

    last_letter = f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:11"
    window.handle_gaze_action(last_letter)
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == window._letter_groups[0][-1]


@pytest.mark.e2e
def test_single_letter_groups_fit_150_percent_display(qtbot, make_speech_window):
    window = make_speech_window(FakeSpeech(), letters_per_group=1, library_store=FakeLibraryStore())
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(window.isVisible)

    assert window.size().width() <= 1280
    assert window.size().height() <= 720
    bounds = QRect(0, 0, 1280, 720)
    group_actions = [
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:{index}" for index in range(len(window._letter_groups))
    ]
    for action in (*group_actions, f"{SPEECH_WINDOW_ACTION_PREFIX}keyboard-toggle"):
        button = window._action_buttons[action]
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert bounds.contains(rect), action
        assert button.height() >= 72, action


@pytest.mark.e2e
def test_speech_symbols_backspace_clear_and_play(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    qtbot.waitUntil(window.isVisible)

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is True
    symbol = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}symbol:0"]
    qtbot.waitUntil(symbol.isVisible)
    qtbot.mouseClick(symbol, Qt.LeftButton)
    assert window._input.text() == "1"

    qtbot.mouseClick(window._keyboard_toggle_button, Qt.LeftButton)
    assert window._symbols_mode is False
    assert f"{SPEECH_WINDOW_ACTION_PREFIX}group:0" in window._action_buttons

    for value in ("DŽ", "LJ", "NJ", "dž", "lj", "nj"):
        window._input.setText(value)
        qtbot.mouseClick(window._backspace_button, Qt.LeftButton)
        assert window._input.text() == ""

    window._input.setText("Trebam pomoć")
    qtbot.mouseClick(window._play_button, Qt.LeftButton)
    assert speech.requests[-1][0] == "TREBAM POMOĆ"
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:cancel"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == "TREBAM POMOĆ"

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window._dialogs.active is window._dialogs.confirm)
    qtbot.mouseClick(
        window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}confirm:accept"], Qt.LeftButton
    )
    qtbot.waitUntil(lambda: window._dialogs.active is None)
    assert window._input.text() == ""

    qtbot.mouseClick(window._clear_button, Qt.LeftButton)
    assert window._dialogs.active is None


@pytest.mark.e2e
def test_library_retry_is_gaze_selectable_and_preserves_the_message(
    qtbot, make_speech_window, tmp_path, monkeypatch
):
    from pathlib import Path

    from pogled_assist.speech.speech_library import (
        CategoryRecord,
        PhraseRecord,
        SpeechLibrary,
        SpeechLibraryStore,
    )

    primary, legacy = tmp_path / "library.json", tmp_path / "phrases.json"
    original = SpeechLibrary(
        [CategoryRecord("Synthetic custom", ["Synthetic answer"])],
        [PhraseRecord("Synthetic phrase", 5)],
    )
    assert SpeechLibraryStore(primary, legacy_path=legacy).save(original)
    before = primary.read_bytes()
    read_text = Path.read_text

    def unavailable(path, *args, **kwargs):
        if path == primary:
            raise PermissionError("Synthetic failure")
        return read_text(path, *args, **kwargs)

    store = SpeechLibraryStore(primary, legacy_path=legacy)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unavailable)
        window = make_speech_window(FakeSpeech(), library_store=store)
    window.resize(1280, 720)
    window.show()
    window._view_mode = "phrases"
    window._show_list_level()
    qtbot.wait(1)
    window._input.setText("SYNTHETIC MESSAGE")
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:select:0")
    message = window._input.text()
    assert "SYNTHETIC PHRASE" in message
    assert primary.read_bytes() == before
    assert window._add_item_button.isHidden()
    assert window._delete_mode_button.isHidden()
    retry = window._retry_library_button
    assert retry.isVisible() and retry.height() >= 80
    assert window.rect().contains(QRect(retry.mapTo(window, QPoint()), retry.size()))
    assert (
        window.action_at_global_point(retry.mapToGlobal(retry.rect().center()))
        == f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry"
    )
    window.handle_gaze_action(f"{SPEECH_WINDOW_ACTION_PREFIX}list:retry")
    assert not store.read_error
    assert window._library == original
    assert window._input.text() == message
    assert retry.isHidden()
    assert window._add_item_button.isVisible()


@pytest.mark.e2e
def test_speech_lifecycle_updates_status_and_ignores_previous_request(qtbot, make_speech_window):
    speech = FakeSpeech()
    window = make_speech_window(speech, library_store=FakeLibraryStore())
    window.show()
    window._input.setText("SYNTHETIC MESSAGE")
    window._play_button.click()
    first = speech.request_id
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(first, "speaking")
    assert window._status_label.text() == "Poruka se izgovara."
    speech.playback_changed.emit(first, "failed")
    assert window._status_label.text() == "Govor nije uspio. Pokušajte ponovo."
    assert window._input.text() == "SYNTHETIC MESSAGE"
    window._play_button.click()
    second = speech.request_id
    speech.playback_changed.emit(first, "finished")
    assert window._status_label.text() == "Pokrećem govor."
    speech.playback_changed.emit(second, "finished")
    assert window._status_label.text() == "Čitanje je završeno."
