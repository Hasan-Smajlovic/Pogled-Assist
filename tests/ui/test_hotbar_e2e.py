from __future__ import annotations

from dataclasses import replace

import pytest
from _ui_fakes import (
    FakeAppBar,
    FakeHotbarInput,
    FakeLibraryStore,
    FakeSpeechService,
    click_speech_action,
)
from PySide6.QtCore import QPoint, QRect

from pogled_assist.interaction.mouse_controller import (
    CONTROLLER,
    KEYBOARD,
    LEFT_CLICK,
    QUICK_ACTIONS,
    SETTINGS,
    SPEECH,
    GazeSettings,
)
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.ui.keyboard_window import KEYBOARD_WINDOW_ACTION_PREFIX
from pogled_assist.ui.speech_window import SPEECH_WINDOW_ACTION_PREFIX


@pytest.mark.e2e
def test_keyboard_script_is_global_and_persisted(hotbar_gaze, qtbot, monkeypatch):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window

    hotbar = hotbar_gaze[0]
    saved = []
    monkeypatch.setattr(
        toolbar, "save_app_settings", lambda gaze, speech: saved.append(replace(speech))
    )
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    hotbar._show_keyboard_sidebar()
    hotbar._keyboard_window._script_button.click()
    assert hotbar._speech.settings.keyboard_script == "arabic"
    assert saved[-1].keyboard_script == "arabic"
    hotbar._open_speech()
    assert hotbar._speech_window._speech_settings.keyboard_script == "arabic"
    hotbar._speech_window._input.setText("سَلَامٌ")
    hotbar._show_controller_sidebar()
    hotbar._controller_window._show_keyboard_tab()
    hotbar._controller_window._script_button.click()
    assert hotbar._speech_window._input.text() == "سَلَامٌ"
    assert hotbar._speech_window._speech_settings.keyboard_script == "latin"
    assert hotbar._keyboard_window._settings.keyboard_script == "latin"
    assert saved[-1].keyboard_script == "latin"


@pytest.mark.e2e
def test_arabic_script_gaze_switch_cannot_repeat_on_replacement_label(
    speech_gaze, qtbot, monkeypatch
):
    monkeypatch.setattr("pogled_assist.toolbar.save_app_settings", lambda *_args: None)
    window, controller, _speech, feed, actions, _progress = speech_gaze
    switch = window._script_button.mapToGlobal(window._script_button.rect().center())
    feed(switch, 0)
    feed(switch, 1001)
    assert window._speech_settings.keyboard_script == "arabic"
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}script-toggle"]
    feed(switch, 1500)
    feed(switch, 3000)
    assert window._speech_settings.keyboard_script == "arabic"
    qtbot.wait(1)
    group = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    group_point = group.mapToGlobal(group.rect().center())
    assert window.action_at_global_point(group_point) == f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"
    feed(group_point, 3100)
    feed(group_point, 3900)
    controller.handle_eye_status(True, False)
    feed(group_point, 4500)
    assert window._dialogs.active is None
    controller.handle_eye_status(True, True)
    feed(group_point, 4600)
    feed(group_point, 5599)
    assert window._dialogs.active is None
    feed(group_point, 5601)
    assert window._dialogs.active is window._dialogs.letter
    qtbot.wait(1)
    letter = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    feed(letter.mapToGlobal(letter.rect().center()), 6000)
    feed(letter.mapToGlobal(letter.rect().center()), 7001)
    assert window._input.text() == "\u0627"


@pytest.mark.e2e
def test_hotbar_coordinates_primary_ui_surfaces(qtbot, monkeypatch):
    from pogled_assist import toolbar
    from pogled_assist.ui import settings_window, sidebar_panel

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)

    window = toolbar.HotbarWindow()
    qtbot.addWidget(window)
    quit_requests = []
    window._quit_application = lambda: quit_requests.append(True)

    assert window._hide_button.text() == "Sakrij"
    assert window._settings_button.text() == "Postavke"
    assert window._quick_actions_button.text() == "Brze radnje"
    assert window._foreground.ready
    assert window._foreground.window == 50
    assert window._foreground.cursor == (600, 500)

    window._run_toolbar_action(LEFT_CLICK, checked=True, source="mouse")
    assert window._mouse.active_mode == LEFT_CLICK

    window._run_toolbar_action(QUICK_ACTIONS, checked=True, source="mouse")
    assert window._mouse.quick_actions_enabled is True
    assert window._buttons[LEFT_CLICK].isHidden()

    window._run_toolbar_action(KEYBOARD, checked=True, source="mouse")
    assert window._keyboard_window is not None and window._keyboard_window.isVisible()

    window._run_toolbar_action(CONTROLLER, checked=True, source="mouse")
    assert window._keyboard_window.isHidden()
    assert window._controller_window is not None and window._controller_window.isVisible()

    window._run_toolbar_action(SPEECH, source="mouse")
    assert window._speech_window is not None and window._speech_window.isVisible()
    window._speech_window.quit_requested.emit()
    assert quit_requests == [True]

    window._run_toolbar_action(SETTINGS, source="mouse")
    assert window._controller_window.isHidden()
    assert window._settings_window is not None and window._settings_window.isVisible()


@pytest.fixture(params=[(1920, 1080), (1280, 720)])
def hotbar_gaze(qtbot, monkeypatch, request):
    from pogled_assist import toolbar
    from pogled_assist.ui import sidebar_panel
    from scripts.ui.capture_ui import PreviewSuggestionService

    monkeypatch.setattr(toolbar, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(toolbar, "WindowsInputController", FakeHotbarInput)
    monkeypatch.setattr(toolbar, "SpeechService", FakeSpeechService)
    monkeypatch.setattr(toolbar, "SuggestionService", PreviewSuggestionService)
    monkeypatch.setattr(toolbar, "speech_library_store", lambda _root: FakeLibraryStore())
    monkeypatch.setattr(toolbar, "load_app_settings", lambda: (GazeSettings(), SpeechSettings()))
    monkeypatch.setattr(toolbar.HotbarWindow, "_start_services", lambda _self: None)
    monkeypatch.setattr(toolbar, "save_app_settings", lambda *_settings: None)
    monkeypatch.setattr(sidebar_panel, "WindowsAppBar", FakeAppBar)
    monkeypatch.setattr(sidebar_panel, "WindowsInputController", FakeHotbarInput)
    hotbar = toolbar.HotbarWindow(simulate_gaze=True)
    qtbot.addWidget(hotbar)
    width, height = request.param
    hotbar.show()
    hotbar.setGeometry(0, 0, width, hotbar.BAR_HEIGHT)
    qtbot.wait(1)
    controller = hotbar._mouse
    controller._logical_screen_rect = (0, 0, width, height)
    controller._physical_screen_rect = (0, 0, 1920, 1080)
    controller.handle_eye_status(True, True)
    now = [10.0]
    monkeypatch.setattr("pogled_assist.interaction.mouse_controller.time.monotonic", lambda: now[0])
    actions = []
    progress = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.interaction_progress_changed.connect(
        lambda _point, value, _label: progress.append(value)
    )

    def feed(point, milliseconds):
        now[0] = 10.0 + milliseconds / 1000
        controller.handle_gaze(point.x() / (width - 1), point.y() / (height - 1), milliseconds)

    return hotbar, controller, feed, actions, progress


@pytest.mark.e2e
def test_hotbar_status_uses_real_simulator_state_and_ignores_diagnostic_text(hotbar_gaze):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    hotbar._gaze.start()
    status = hotbar._tracking_status
    assert status._title.text() == "Simulacija mišem"
    assert status._detail.text() == "Upravljanje mišem"
    hotbar._gaze.status_changed.emit("Praćenje simulacijom miša je aktivno.")
    hotbar._gaze.tracker_changed.emit("retrying")
    hotbar._set_status("Otvoren je izbornik brzih radnji.")
    assert status._title.text() == "Simulacija mišem"
    hotbar._gaze.stop()
    assert status._title.text() == "Praćenje zaustavljeno"


@pytest.mark.e2e
def test_hotbar_status_stays_available_when_icon_fonts_cannot_load(hotbar_gaze, monkeypatch):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus
    from pogled_assist.ui import tracking_status

    def unavailable_font(*_args, **_kwargs):
        raise OSError("Synthetic font-loading failure")

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    monkeypatch.setattr(tracking_status.qta, "icon", unavailable_font)
    status = hotbar._tracking_status
    status.set_tracking_status(TrackingStatus(TrackingState.SIMULATING))
    assert status._title.text() == "Simulacija mišem"
    assert status._icon.text() == "↖"
    assert status._icon.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("eyes", "detail"),
    [
        ((False, True), "Lijevo —    Desno ✓"),
        ((True, False), "Lijevo ✓    Desno —"),
        ((False, False), "Lijevo —    Desno —"),
    ],
)
def test_hotbar_status_requires_fresh_gaze_and_updates_on_eye_loss(
    hotbar_gaze, qtbot, eyes, detail
):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    hotbar._gaze.tracking_status_changed.emit(
        TrackingStatus(TrackingState.CONNECTED, "Fake tracker")
    )
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.eye_status_changed.emit(True, True)
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    assert status._title.text() == "Praćenje spremno"
    hotbar._gaze.eye_status_changed.emit(*eyes)
    assert status._title.text() == "Praćenje pauzirano"
    assert status._detail.text() == detail
    assert status._detail.isVisible()
    assert "nema validnog podatka" in status.accessibleName()
    assert controller._both_eyes_open is False
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 1)
    assert status._title.text() == "Praćenje pauzirano"
    hotbar._gaze.eye_status_changed.emit(True, True)
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 2)
    assert status._title.text() == "Praćenje spremno"
    # The display watchdog must also cover loss of gaze while eye data stays valid.
    status._last_gaze_at -= 0.6
    qtbot.waitUntil(lambda: status._title.text() == "Čekam podatke")
    assert status._detail.text() == "Podaci o pogledu kasne"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 3)
    assert status._title.text() == "Praćenje spremno"


@pytest.mark.e2e
def test_tracking_status_distinguishes_no_samples_from_live_invalid_eyes(qtbot, monkeypatch):
    from pogled_assist.tracking import gaze_provider
    from pogled_assist.ui.tracking_status import TrackingStatusWidget

    callbacks = []

    class FakeBackend:
        label = "Synthetic tracker"

        def __init__(self, gaze, eyes):
            callbacks.append((gaze, eyes))

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(
        gaze_provider.TobiiGazeProvider, "_start_with_tobii_research", lambda _: False
    )
    monkeypatch.setattr(gaze_provider, "TobiiStreamEngineBackend", FakeBackend)
    provider = gaze_provider.TobiiGazeProvider()
    status = TrackingStatusWidget()
    qtbot.addWidget(status)
    status.show()
    provider.tracking_status_changed.connect(status.set_tracking_status)
    provider.eye_status_changed.connect(status.set_eye_status)
    provider.gaze_updated.connect(status.handle_gaze)
    try:
        for _connection in range(2):
            provider.start()
            assert status._detail.text() == "Čekam stanje očiju"
            callbacks[-1][1](False, False, 1)
            assert status._title.text() == "Praćenje pauzirano"
            assert status._detail.text() == "Lijevo —    Desno —"
            callbacks[-1][1](True, True, 2)
            assert status._title.text() == "Čekam podatke"
            callbacks[-1][0](0.5, 0.5, 2)
            provider._emit_latest_gaze_sample()
            assert status._title.text() == "Praćenje spremno"
            assert "Synthetic tracker" in status.toolTip()
            provider.stop()
            assert status._title.text() == "Praćenje zaustavljeno"
    finally:
        provider.stop()


@pytest.mark.e2e
def test_hotbar_status_waiting_and_retry_survive_eye_and_text_notifications(hotbar_gaze):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.WAITING))
    hotbar._gaze.eye_status_changed.emit(False, False)
    assert status._title.text() == "Čekam podatke"
    assert status._detail.text() == "Podaci o očima kasne"
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.RETRYING))
    hotbar._gaze.eye_status_changed.emit(True, True)
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 0)
    hotbar._gaze.status_changed.emit("Praćenje je aktivno putem uređaja.")
    assert status._title.text() == "Uređaj nije povezan"
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.CONNECTED))
    assert status._title.text() == "Čekam podatke"
    hotbar._gaze.gaze_updated.emit(0.5, 0.5, 1)
    assert status._title.text() == "Praćenje spremno"


@pytest.mark.e2e
def test_hide_removes_entire_status_and_show_restores_latest_state(hotbar_gaze):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    assert status.isVisible()
    assert not status.isWindow()
    assert hotbar.action_at_global_point(status.mapToGlobal(status.rect().center())) is None
    hotbar._hide_hotbar()
    assert not status.isVisible()
    assert not status._title.isVisible()
    assert not status._detail.isVisible()
    assert hotbar._restore_button.isVisible()
    hotbar._gaze.tracking_status_changed.emit(TrackingStatus(TrackingState.RETRYING))
    assert not status.isVisible()
    assert status._title.text() == "Uređaj nije povezan"
    hotbar._show_hotbar()
    assert status.isVisible()
    assert status._title.text() == "Uređaj nije povezan"
    assert not hotbar._restore_button.isVisible()


@pytest.mark.e2e
@pytest.mark.parametrize(
    "state",
    [
        "connecting",
        "connected",
        "waiting",
        "retrying",
        "stopped",
        "simulating",
        "unavailable",
        "ready",
        "gaze-waiting",
    ],
)
def test_hotbar_status_and_all_actions_fit_target_display(hotbar_gaze, state):
    from pogled_assist.tracking.status import TrackingState, TrackingStatus

    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    status = hotbar._tracking_status
    lifecycle = "connected" if state in ("ready", "gaze-waiting") else state
    status.set_tracking_status(TrackingStatus(TrackingState(lifecycle)))
    status.set_eye_status(state in ("ready", "gaze-waiting"), True)
    if state == "ready":
        status.handle_gaze(0.5, 0.5, 0)
    hotbar.layout().activate()
    assert hotbar.BAR_HEIGHT == 76
    assert hotbar.rect().contains(status.geometry())
    for button in hotbar._buttons.values():
        if button is hotbar._restore_button:
            continue
        rect = QRect(button.mapTo(hotbar, QPoint()), button.size())
        assert hotbar.rect().contains(rect)
        assert not rect.intersects(status.geometry())
        assert button.height() == 58
    for label in (status._title, status._detail):
        assert status.rect().contains(label.geometry()), (state, label.geometry())
        assert (
            label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width()
        ), (
            state,
            label.text(),
            label.geometry(),
            label.fontMetrics().horizontalAdvance(label.text()),
        )


@pytest.fixture
def speech_gaze(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    hotbar._open_speech()
    window = hotbar._speech_window
    window.showNormal()
    window.setGeometry(*controller._logical_screen_rect)
    qtbot.waitUntil(window.isVisible)
    qtbot.wait(1)
    return window, controller, hotbar._speech, feed, actions, progress


@pytest.mark.e2e
@pytest.mark.parametrize("action", [SPEECH, KEYBOARD, SETTINGS])
@pytest.mark.parametrize("y", [0, 1])
def test_hotbar_gaze_acquires_buttons_at_top_edge(hotbar_gaze, monkeypatch, action, y):
    hotbar, _controller, feed, actions, _progress = hotbar_gaze
    from pogled_assist.ui import settings_window

    monkeypatch.setattr(settings_window, "is_windows_startup_enabled", lambda: False)
    point = hotbar._buttons[action].mapToGlobal(QPoint(50, 0))
    point.setY(y)
    assert hotbar.action_at_global_point(point) == action
    feed(point, 0)
    feed(point, 800)
    assert hotbar._buttons[action].property("gazeTarget") is True
    feed(point, 1001)
    assert actions == [action]
    opened = {
        SPEECH: hotbar._speech_window,
        KEYBOARD: hotbar._keyboard_window,
        SETTINGS: hotbar._settings_window,
    }[action]
    assert opened is not None and opened.isVisible()


@pytest.mark.e2e
def test_hotbar_top_edge_has_distinct_targets_and_neutral_gaps(hotbar_gaze):
    hotbar, _controller, _feed, _actions, _progress = hotbar_gaze
    bounds = [(action, hotbar.action_bounds(action)) for action in hotbar._buttons]
    bounds = [(action, rect) for action, rect in bounds if rect is not None]
    for x in range(hotbar.width()):
        point = QPoint(x, 0)
        matches = [action for action, rect in bounds if rect.contains(point)]
        assert len(matches) <= 1
        assert hotbar.action_at_global_point(point) == (matches[0] if matches else None)
    hotbar._buttons[SPEECH].setEnabled(False)
    assert hotbar.action_bounds(SPEECH) is None
    hotbar.hide()
    assert hotbar.action_at_global_point(QPoint(50, 0)) is None


@pytest.fixture(params=["hotbar", "keyboard"])
def edge_surface(hotbar_gaze, qtbot, request):
    hotbar, controller, feed, actions, progress = hotbar_gaze
    if request.param == "hotbar":
        window = hotbar
        action = QUICK_ACTIONS
        button = hotbar._buttons[action]
    else:
        hotbar._show_keyboard_sidebar()
        window = hotbar._keyboard_window
        _, _, width, height = controller._logical_screen_rect
        window.setGeometry(width - 380, hotbar.BAR_HEIGHT, 380, height - hotbar.BAR_HEIGHT)
        qtbot.wait(1)
        action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}space"
        button = window._space_button
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    return window, controller, feed, actions, progress, action, center, outside


@pytest.mark.e2e
def test_hotbar_and_keyboard_hold_progress_without_selecting_outside(edge_surface):
    _window, _controller, feed, actions, progress, action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(outside, 860)
    assert progress[-1] == pytest.approx(0.6)
    assert actions == []
    feed(center, 900)
    feed(center, 1099)
    assert actions == []
    feed(center, 1101)
    assert actions == [action]
    feed(outside, 1120)
    feed(center, 1160)
    feed(center, 2500)
    assert actions == [action]


@pytest.mark.e2e
@pytest.mark.parametrize("reset", ["eye", "long-departure", "hide", "resize"])
def test_hotbar_and_keyboard_discard_progress_after_interruption(edge_surface, reset):
    window, controller, feed, actions, _progress, _action, center, outside = edge_surface
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if reset == "eye":
        controller.handle_eye_status(True, False)
        controller.handle_eye_status(True, True)
    elif reset == "long-departure":
        feed(outside, 950)
    elif reset == "hide":
        if hasattr(window, "_hide_hotbar"):
            window._hide_hotbar()
        else:
            window.hide_sidebar()
    else:
        window.resize(window.width() - 1, window.height())
    feed(center, 980)
    feed(center, 1200)
    assert actions == []


@pytest.mark.e2e
def test_keyboard_letter_entry_survives_brief_edge_jitter(hotbar_gaze, qtbot):
    hotbar, controller, feed, actions, _progress = hotbar_gaze
    hotbar._show_keyboard_sidebar()
    window = hotbar._keyboard_window
    _, _, width, height = controller._logical_screen_rect
    window.setGeometry(width - 380, 76, 380, height - 76)
    window._show_letter_group(0)
    qtbot.wait(1)
    action = f"{KEYBOARD_WINDOW_ACTION_PREFIX}letter:0:0"
    button = window._action_buttons[action]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 2, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    feed(center, 900)
    feed(center, 1101)
    assert actions == [action]
    assert window._input.typed == ["A"]
    assert window._active_group_index is None


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["group:0", "letter:0:0", "suggestion:0", "play"])
def test_speech_gaze_keeps_progress_through_brief_edge_excursion(speech_gaze, qtbot, command):
    window, _controller, speech, feed, actions, progress = speech_gaze
    window._input.setText("ŽELIM ")
    if command.startswith("letter:"):
        click_speech_action(qtbot, window, "group:0")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    expected_word = button.text()

    feed(center, 0)
    feed(center, 800)
    assert progress[-1] == pytest.approx(0.6)
    feed(outside, 820)
    feed(outside, 840)
    feed(center, 860)
    assert progress[-1] == pytest.approx(0.6)
    feed(center, 1040)
    assert actions == []
    feed(center, 1061)

    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    if command == "letter:0:0":
        assert window._input.text() == "ŽELIM A"
    elif command == "suggestion:0":
        assert window._input.text() == f"ŽELIM {expected_word} "
    elif command == "play":
        assert speech.requests[0][0] == "ŽELIM"
    else:
        assert window._dialogs.active is window._dialogs.letter


@pytest.mark.e2e
@pytest.mark.parametrize("near_edge", [True, False])
def test_speech_gaze_switches_letters_without_transferring_progress(speech_gaze, qtbot, near_edge):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    first_center = first.mapToGlobal(first.rect().center())
    second_point = second.mapToGlobal(
        QPoint(2, second.height() // 2) if near_edge else second.rect().center()
    )
    assert window.action_at_global_point(second_point) == f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"
    feed(first_center, 0)
    feed(first_center, 980)
    feed(second_point, 1000)
    feed(second_point, 1100)
    assert actions == []
    feed(second_point, 1121)
    finish = 2122 if near_edge else 2001
    feed(second_point, finish - 2)
    assert actions == []
    feed(second_point, finish)
    assert window._input.text() == "B"
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]


@pytest.mark.e2e
def test_speech_gaze_can_return_from_neighbor_without_selecting_it(speech_gaze, qtbot):
    window, _controller, _speech, feed, actions, progress = speech_gaze
    click_speech_action(qtbot, window, "group:0")
    first = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:0"]
    second = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}letter:0:1"]
    center = first.mapToGlobal(first.rect().center())
    neighbor = second.mapToGlobal(QPoint(2, second.height() // 2))
    feed(center, 0)
    feed(center, 980)
    feed(neighbor, 1000)
    feed(neighbor, 1060)
    assert actions == []
    assert progress[-1] == pytest.approx(0.96)
    feed(center, 1080)
    assert actions == []
    feed(center, 1101)
    assert window._input.text() == "A"


@pytest.mark.e2e
@pytest.mark.parametrize("cancel", ["eye_loss", "mouse", "resize", "disable"])
def test_speech_gaze_discards_held_progress_when_context_is_lost(speech_gaze, qtbot, cancel):
    window, controller, _speech, feed, actions, _progress = speech_gaze
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    feed(outside, 820)
    if cancel == "eye_loss":
        controller.handle_eye_status(True, False)
        feed(center, 840)
        controller.handle_eye_status(True, True)
    elif cancel == "mouse":
        click_speech_action(qtbot, window, "group:1")
        click_speech_action(qtbot, window, "letters:close")
    elif cancel == "resize":
        window.resize(window.width() - 20, window.height())
        qtbot.wait(1)
    else:
        button.setEnabled(False)
        feed(center, 840)
        button.setEnabled(True)
    center = button.mapToGlobal(button.rect().center())
    feed(center, 860)
    feed(center, 1061)
    assert actions == []
    if cancel in {"mouse", "resize"}:
        other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:1"]
        feed(other.mapToGlobal(other.rect().center()), 1080)
        feed(center, 1100)
    feed(center, 2101)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]


@pytest.mark.e2e
@pytest.mark.parametrize("during_hold", [False, True])
def test_speech_gaze_changed_suggestion_requires_confirmed_departure(speech_gaze, during_hold):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    button = window._prediction_buttons[0]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 800)
    if during_hold:
        feed(outside, 820)
    window._input.setText("ŽELIM ")
    feed(center, 860)
    feed(center, 2000)
    assert actions == []
    feed(outside, 2020)
    feed(center, 2060)
    feed(center, 3500)
    assert actions == []
    other = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    feed(other.mapToGlobal(other.rect().center()), 3520)
    feed(center, 3540)
    feed(center, 4541)
    assert window._input.text() == "ŽELIM VODU "


@pytest.mark.e2e
def test_speech_gaze_switch_during_cooldown_waits_before_starting_selection(speech_gaze):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    play = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    group = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}group:0"]
    play_center = play.mapToGlobal(play.rect().center())
    group_center = group.mapToGlobal(group.rect().center())
    feed(play_center, 0)
    feed(play_center, 1001)
    feed(group_center, 1020)
    feed(group_center, 1340)
    feed(group_center, 1360)
    feed(group_center, 2359)
    assert actions == [f"{SPEECH_WINDOW_ACTION_PREFIX}play"]
    assert window._dialogs.active is None
    feed(group_center, 2361)
    assert actions == [
        f"{SPEECH_WINDOW_ACTION_PREFIX}play",
        f"{SPEECH_WINDOW_ACTION_PREFIX}group:0",
    ]
    assert window._dialogs.active is window._dialogs.letter


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
def test_speech_gaze_edge_jitter_cannot_repeat_completed_action(speech_gaze, command):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    assert len(actions) == 1
    feed(outside, 1020)
    feed(center, 1060)
    feed(center, 2400)
    feed(outside, 2420)
    feed(center, 2460)
    feed(center, 3800)
    assert len(actions) == 1
    feed(outside, 3820)
    feed(outside, 3941)
    feed(center, 3960)
    feed(center, 4961)
    assert len(actions) == 2


@pytest.mark.e2e
@pytest.mark.parametrize("command", ["play", "suggestion:0"])
@pytest.mark.parametrize("during_cooldown", [False, True])
def test_speech_gaze_can_repeat_after_departure_with_no_expiry_sample(
    speech_gaze, command, during_cooldown
):
    window, _controller, _speech, feed, actions, _progress = speech_gaze
    window._input.setText("ŽELIM ")
    button = window._action_buttons[f"{SPEECH_WINDOW_ACTION_PREFIX}{command}"]
    center = button.mapToGlobal(button.rect().center())
    outside = button.mapToGlobal(QPoint(button.width() + 4, button.height() // 2))
    feed(center, 0)
    feed(center, 1001)
    feed(center, 1010 if during_cooldown else 1400)
    assert len(actions) == 1
    feed(outside, 1020 if during_cooldown else 1420)
    # Return after the 120 ms hold, without another sample while outside.
    feed(center, 1160 if during_cooldown else 1560)
    start = 1360 if during_cooldown else 1560
    feed(center, start)
    feed(center, start + 999)
    assert len(actions) == 1
    feed(center, start + 1001)
    assert len(actions) == 2
