from __future__ import annotations

from dataclasses import replace

import pytest
from _clock import freeze_monotonic
from _speech_fakes import FakeCredentials, FakeElevenClient
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QLineEdit

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.eleven_account import ElevenAccount
from pogled_assist.speech.elevenlabs import AccountOptions, Subscription
from pogled_assist.speech.speech_library import PhraseRecord, SpeechLibrary
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import VoiceError, VoiceState
from pogled_assist.tracking.feedback import TrackingNotice
from pogled_assist.ui.settings_window import SettingsServices, SettingsWindow
from pogled_assist.ui.speech_window import SpeechWindow
from pogled_assist.windows.credentials import CredentialError

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("dedicated", [True, False])
def test_stationary_gaze_cannot_repeat_paid_test_after_busy_completion(
    settings, qtbot, monkeypatch, dedicated
):
    window, _store, _client, account, _ = settings
    account.save_key("key")
    account.check()
    qtbot.waitUntil(lambda: account.state.options is not None)
    window.update_speech_settings(
        SpeechSettings(voice_preset="efendija", elevenlabs_voice_id="synthetic-voice")
    )
    if dedicated:
        window._open_eleven()
        qtbot.waitUntil(lambda: not account.state.credits_busy)
    else:
        window._select_tab(2)
    button = (
        window._eleven_page.test_button if dedicated else window._speech_page._test_speech_button
    )
    window._gaze_settings = replace(
        window._gaze_settings, selection_pause_ms=0, dwell_ms=200, click_cooldown_ms=100
    )
    calls = []
    signal = window.efendija_test_requested if dedicated else window.speech_test_requested

    def start():
        calls.append(True)
        window.set_speech_playback_state("preparing")

    signal.connect(start)
    qtbot.wait(1)
    now = freeze_monotonic(monkeypatch, 10.0)
    center = button.mapToGlobal(button.rect().center())

    def feed(point, seconds):
        now[0] = seconds
        window.handle_gaze(point)

    feed(center, 10)
    feed(center, 10.3)
    assert len(calls) == 1
    feed(center, 11)
    window.set_speech_playback_state("finished")
    qtbot.wait(1)
    feed(center, 12)
    feed(center, 12.3)
    assert len(calls) == 1
    feed(window.mapToGlobal(QPoint(5, 5)), 13)
    assert not window._gaze_selection.is_blocked
    assert button.isEnabled(), (account.state, account.config, window._speech_playback_state)
    assert window._controls.action_at(center)[0] is button
    feed(center, 14)
    feed(center, 14.3)
    assert len(calls) == 2


@pytest.mark.parametrize("empty", [False, True])
def test_main_settings_cannot_test_saved_voice_absent_from_my_voices(settings, qtbot, empty):
    window, _store, client, account, _ = settings
    account.save_key("key")
    if empty:
        client.options = lambda *_: AccountOptions((), (("eleven_v3", "Eleven v3"),), None)
    account.check()
    qtbot.waitUntil(lambda: account.state.options is not None)
    window.update_speech_settings(
        SpeechSettings(voice_preset="efendija", elevenlabs_voice_id="absent-voice")
    )
    window._select_tab(2)
    assert not window._speech_page._test_speech_button.isEnabled()


def test_stability_choices_and_similarity_slider_update_settings(settings):
    window, _store, _client, account, _ = settings
    window._open_eleven()
    page = window._eleven_page
    changes = []
    window.speech_settings_changed.connect(changes.append)
    assert page.stability_buttons[50].isChecked()
    for value, label in ((0, "Kreativno"), (50, "Prirodno"), (100, "Stabilno")):
        button = page.stability_buttons[value]
        assert button.height() >= 58
        assert button.accessibleName() == f"ElevenLabs Stabilnost: {label}"
        assert window._controls._actions[button] is not None
        button.click()
        assert changes[-1].elevenlabs_stability == value
        assert sum(control.isChecked() for control in page.stability_buttons.values()) == 1
    page.similarity.setValue(90)
    assert account.config.parameters["voice_settings"] == {
        "stability": 1.0,
        "similarity_boost": 0.9,
    }
    button = next(
        widget
        for widget in window._controls._actions
        if window._controls.name(widget) == "Sličnost glasa: više"
    )
    window._controls._actions[button]()
    assert page.similarity.value() == 95
    window.update_speech_settings(SpeechSettings(elevenlabs_stability=50, elevenlabs_similarity=70))
    assert page.stability_buttons[50].isChecked() and page.similarity.value() == 70


@pytest.mark.parametrize(
    "used,percent,color",
    [(0, 100, "#91dec0"), (850, 15, "#edc779"), (950, 5, "#e48c80"), (1100, 0, "#e48c80")],
)
def test_credits_display_remaining_and_warning_thresholds(settings, used, percent, color):
    window, _store, _client, account, _ = settings
    window._open_eleven()
    account.state = replace(account.state, subscription=Subscription(used, 1000))
    window._eleven_page.refresh(account.state)
    page = window._eleven_page
    assert page.credits.value() == percent and color in page.credits.styleSheet()
    assert f"({percent}%)" in page.credits_label.text()
    assert "1.000 kredita" in page.credits_label.text()


def test_free_credit_refresh_and_missing_permission_leave_voice_options_available(settings, qtbot):
    window, _store, client, account, _ = settings
    account.save_key("key")
    account.check()
    qtbot.waitUntil(lambda: account.state.options is not None and not account.state.credits_busy)
    options = account.state.options
    client.balance = Subscription(85, 100)
    window._open_eleven()
    qtbot.waitUntil(lambda: not account.state.credits_busy)
    assert window._eleven_page.credits.value() == 15

    def denied(*_):
        raise VoiceError("permission")

    client.subscription = denied
    account.refresh_subscription()
    qtbot.waitUntil(lambda: not account.state.credits_busy)
    assert account.state.options == options
    assert account.state.subscription is None
    assert "čitanje podataka o računu" in window._eleven_page.credits_note.text()
    assert not window._eleven_page.credits.isVisible()
    assert client.calls == []


def test_playback_progress_prevents_duplicate_paid_tests_and_allows_stop(settings):
    window, _store, _client, _account, _ = settings
    window._open_eleven()
    stopped = []
    window.speech_stop_requested.connect(lambda: stopped.append(True))
    for state in ("preparing", "speaking"):
        window.set_speech_playback_state(state)
        assert window._eleven_page.playback_progress.isVisible()
        assert not window._eleven_page.test_button.isEnabled()
        assert not window._speech_page._test_speech_button.isEnabled()
        window._eleven_page.stop_button.click()
    assert len(stopped) == 2
    window.set_speech_playback_state("failed")
    assert not window._eleven_page.playback_progress.isVisible()


def test_speech_busy_control_preserves_message_and_rejects_repeat_start(speech):
    window, service, _ = speech
    text = window._input.text()
    calls = len(service.requests)
    assert window._playback_progress.isVisible()
    assert window._play_button.text() == "Zaustavi"
    window._play_button.click()
    assert len(service.requests) == calls
    assert service.stop_calls == 1
    service.playback_changed.emit(window._playback_id, "stopped")
    assert window._play_button.isEnabled()
    assert not window._playback_progress.isVisible()
    assert window._input.text() == text


def test_speech_window_tracks_active_speech_started_in_another_window(qtbot):
    service = FakeSpeech()
    service.request_id = 12
    service.playback_state = "speaking"
    window = SpeechWindow(service, library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound())
    qtbot.addWidget(window)
    window.show()
    assert window._play_button.text() == "Zaustavi"
    assert window._playback_progress.isVisible()
    service.request_id = 13
    service.playback_changed.emit(13, "preparing")
    assert window._playback_id == 13
    service.playback_changed.emit(12, "finished")
    assert window._play_button.text() == "Zaustavi"
    service.playback_changed.emit(13, "finished")
    assert window._play_button.text() == "Izgovori"


@pytest.fixture
def settings(qtbot, qapp, monkeypatch):
    monkeypatch.setattr(
        "pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False
    )
    store, client = FakeCredentials(), FakeElevenClient()
    account = ElevenAccount(qapp, store=store, client=client)
    cleared = []
    window = SettingsWindow(
        GazeSettings(),
        SpeechSettings(),
        services=SettingsServices(
            account=account, clear_audio=lambda: cleared.append(True) or True
        ),
    )
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window._select_tab(2)
    window.show()
    yield window, store, client, account, cleared
    account.cancel_check()


def test_caregiver_sets_key_checks_connection_and_selects_voice_and_model(settings, qtbot):
    window, store, client, account, _cleared = settings
    changes = []
    window.speech_settings_changed.connect(changes.append)
    window._speech_page._voice_buttons["efendija"].click()
    assert changes[-1].voice_preset == "efendija"
    assert window._speech_page._test_speech_button.text() == "Isprobaj Efendiju"
    window._speech_page._eleven_button.click()
    page = window._eleven_page
    assert page.key_input.echoMode() == QLineEdit.Password
    page.key_input.setText("synthetic-private-key")
    page.save_key.click()
    assert store.key == "synthetic-private-key"
    assert page.key_input.text() == ""
    assert "synthetic-private-key" not in page.connection.text()
    page.check_button.click()
    qtbot.waitUntil(lambda: account.state.options is not None)
    assert client.calls == []
    page.voice.setCurrentIndex(page.voice.findData("synthetic-voice"))
    assert changes[-1].elevenlabs_voice_id == "synthetic-voice"
    assert changes[-1].elevenlabs_model_id == "eleven_v4"
    tests = []
    window.efendija_test_requested.connect(lambda: tests.append(True))
    page.test_button.click()
    assert tests == [True]
    assert client.calls == []
    page.key_input.setText("unsaved-private-key")
    window._select_tab(2)
    assert page.key_input.text() == ""
    assert window._speech_page._voice_buttons["efendija"].isChecked()


def test_setup_pages_fit_display_and_controls_keep_gaze_size(settings, qtbot):
    window, _store, _client, _account, _cleared = settings
    window._speech_page._voice_buttons["efendija"].click()
    for open_page, controls in (
        (lambda: window._select_tab(2), tuple(window._speech_page._voice_buttons.values())),
        (
            window._open_eleven,
            (
                window._eleven_page.key_input,
                window._eleven_page.save_key,
                window._eleven_page.voice,
                window._eleven_page.model,
                window._eleven_page.test_button,
            ),
        ),
        (window._open_audio, (window._audio_page.clear_button,)),
    ):
        open_page()
        qtbot.wait(1)
        assert window.size().width() == 1280 and window.size().height() == 720
        for control in controls:
            assert control.isVisible()
            assert control.height() >= 58
            assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))


def test_voice_dropdown_contains_only_my_voices_and_requires_explicit_reselection(settings, qtbot):
    window, _store, _client, account, _cleared = settings
    account.save_key("synthetic-key")
    window.update_speech_settings(SpeechSettings(elevenlabs_voice_id="old-default-voice"))
    window._open_eleven()
    page = window._eleven_page
    page.check_button.click()
    qtbot.waitUntil(lambda: account.state.options is not None)
    assert [page.voice.itemData(index) for index in range(page.voice.count())] == [
        "synthetic-voice"
    ]
    assert page.voice.currentIndex() == -1
    assert not page.test_button.isEnabled()
    assert window._speech_settings.elevenlabs_voice_id == "old-default-voice"
    page._cycle(page.voice)
    assert window._speech_settings.elevenlabs_voice_id == "synthetic-voice"
    assert page.test_button.isEnabled()
    page._cycle(page.voice)
    assert page.voice.currentData() == "synthetic-voice"


def test_empty_my_voices_disables_selection_and_test_without_inserting_saved_id(settings, qtbot):
    window, _store, client, account, _cleared = settings
    account.save_key("synthetic-key")
    window.update_speech_settings(SpeechSettings(elevenlabs_voice_id="removed-voice"))
    client.options = lambda *_: AccountOptions((), (("eleven_v3", "Eleven v3"),), None)
    window._open_eleven()
    page = window._eleven_page
    page.check_button.click()
    qtbot.waitUntil(lambda: account.state.options is not None)
    assert page.voice.count() == 0
    assert page.voice.placeholderText() == "Nema glasova"
    assert not page.voice.isEnabled() and not page.test_button.isEnabled()
    assert window._speech_settings.elevenlabs_voice_id == "removed-voice"


def test_audio_clear_preserves_voice_and_settings_choice(settings):
    window, _store, _client, _account, cleared = settings
    window._speech_page._voice_buttons["efendija"].click()
    before = replace(window._speech_settings)
    window._open_audio()
    window._audio_page.clear_button.click()
    assert cleared == [True]
    assert "Fraze i odgovori ostaju" in window._audio_page.status.text()
    assert window._speech_settings == before


@pytest.fixture
def speech(qtbot):
    service = FakeSpeech()
    service._settings = SpeechSettings(voice_preset="efendija", elevenlabs_voice_id="voice")
    library = FakeLibraryStore(SpeechLibrary(phrases=[PhraseRecord("SAČUVANA FRAZA.")]))
    window = SpeechWindow(service, library_store=library, alarm_sound=FakeAlarmSound())
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    window._input.setText("SAČUVANA FRAZA.")
    window._play()
    return window, service, library


def test_all_voice_notices_keep_targets_fixed_and_preserve_message_and_selection(speech, qtbot):
    window, service, _library = speech
    qtbot.wait(1)
    before = {key: QRect(button.geometry()) for key, button in window._action_buttons.items()}
    for state in (
        VoiceState(),
        VoiceState("human_like", "quota"),
        VoiceState("human_like", "offline"),
        VoiceState("human_like", "timeout"),
        VoiceState("human_like", "invalid_key"),
        VoiceState("default", "offline"),
        VoiceState(cached=True),
        VoiceState(cache_failed=True),
        VoiceState(partial=True),
        VoiceState(recovered=True),
    ):
        service.publish_voice(state)
        qtbot.wait(1)
        assert window._input.text() == "SAČUVANA FRAZA."
        assert service.settings.voice_preset == "efendija"
        assert {
            key: QRect(button.geometry()) for key, button in window._action_buttons.items()
        } == before
        notice = window._message_header.notice
        assert notice.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert notice.focusPolicy() == Qt.NoFocus
        if state.notice is not None:
            assert notice.notice.title == state.notice[1]
            assert notice.notice.detail == state.notice[2]


def test_recovery_hides_itself_after_five_seconds_and_tracking_has_priority(
    speech, qtbot, monkeypatch
):
    window, service, _library = speech
    service.publish_voice(VoiceState(recovered=True))
    assert window._speech_notice_timer.interval() == 5000
    tracking = TrackingNotice("Praćenje oba oka je prekinuto", eyes=(False, False))
    window.set_tracking_notice(tracking, immediate=True)
    assert window._message_header.notice.notice == tracking
    assert not window._speech_notice_timer.isActive()
    monkeypatch.setattr("pogled_assist.ui.speech_surface.RECOVERY_NOTICE_MS", 20)
    window.set_tracking_notice(None, immediate=True)
    assert window._message_header.notice.notice.title == "Efendijin glas je ponovo dostupan."
    qtbot.waitUntil(lambda: window._speech_notice is None)
    qtbot.waitUntil(lambda: not window._message_header.notice.isVisible())
    assert window._status_label.text() == "Glas: Efendija"


def test_new_failure_replaces_recovery_and_cancels_its_timer(speech):
    window, service, _library = speech
    service.publish_voice(VoiceState(recovered=True))
    service.publish_voice(VoiceState("human_like", "quota"))
    assert not window._speech_notice_timer.isActive()
    assert window._speech_notice.title == "Nema dovoljno ElevenLabs kredita."
    assert window._speech_notice.detail == "Koristi se Prirodni glas."


def test_partial_failure_retains_text_and_requires_explicit_replay(speech):
    window, service, _library = speech
    service.publish_voice(VoiceState(partial=True))
    service.playback_changed.emit(service.request_id, "failed")
    assert len(service.requests) == 1
    assert window._input.text() == "SAČUVANA FRAZA."
    assert window._speech_notice.title == "Izgovor nije završen."
    window._play()
    assert len(service.requests) == 2


def test_storage_warning_keeps_speech_finished_and_has_no_recovery_timer(speech):
    window, service, _library = speech
    service.publish_voice(VoiceState(cache_failed=True))
    service.playback_changed.emit(service.request_id, "finished")
    assert window._speech_notice.title == "Zvuk nije sačuvan."
    assert window._speech_notice.detail == "Ponavljanje može trošiti kredite."
    assert window._speech_notice.tone == "warning"
    assert not window._speech_notice_timer.isActive()
    assert window._input.text() == "SAČUVANA FRAZA."
    assert len(service.requests) == 1
    service.publish_voice(VoiceState(cached=True))
    assert window._speech_notice.title == "Koristi se sačuvani Efendijin glas."


def test_arabic_suppresses_bosnian_notice_and_restores_selected_voice(speech):
    window, service, _library = speech
    service.publish_voice(VoiceState("human_like", "quota"))
    window.update_settings(replace(service.settings, keyboard_script="arabic"))
    assert window._speech_notice is None
    window.update_settings(service.settings)
    assert window._speech_notice.detail == "Koristi se Prirodni glas."


def test_library_reload_updates_cache_eligibility_and_unreadable_library_disables_it(speech):
    window, service, library = speech
    assert service.saved_texts == {"SAČUVANA FRAZA."}
    library.library = SpeechLibrary(phrases=[PhraseRecord("DRUGA FRAZA.")])
    window._retry_library()
    assert service.saved_texts == {"DRUGA FRAZA."}
    library.read_error = True
    window._retry_library()
    assert service.saved_texts is None


def test_failed_key_save_retains_masked_input_and_previous_credential(settings):
    window, store, _client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page
    page.replace_key.click()
    page.key_input.setText("replacement-key")
    page.show_key.click()

    def fail(_key):
        raise CredentialError("must not display private key")

    store.write = fail
    page.save_key.click()
    assert page.key_input.text() == "replacement-key"
    assert page.key_input.echoMode() == QLineEdit.Password
    assert not page.show_key.isChecked()
    assert account.config.key == "original-key"
    assert "Ključ nije sačuvan" in page.connection.text()
    assert "private key" not in page.connection.text()


def test_pending_replacement_must_be_saved_before_connection_check(settings, qtbot):
    window, _store, client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page
    page.replace_key.click()
    checked = []
    original = client.options

    def options(key, *args):
        checked.append(key)
        return original(key, *args)

    client.options = options
    page.key_input.setText("replacement-key")
    page.check_button.click()
    assert checked == []
    assert "Sačuvajte novi ključ" in page.connection.text()
    page.save_key.click()
    assert page.key_input.text() == ""
    assert not page.key_input.isVisible()
    page.check_button.click()
    qtbot.waitUntil(lambda: account.state.options is not None)
    assert checked == ["replacement-key"]


def test_pending_replacement_cannot_test_and_bill_previous_key(settings, qtbot):
    window, _store, _client, account, _cleared = settings
    account.save_key("original-key")
    account.configure(SpeechSettings(elevenlabs_voice_id="synthetic-voice"))
    account.check()
    qtbot.waitUntil(lambda: account.state.options is not None)
    window.update_speech_settings(SpeechSettings(elevenlabs_voice_id="synthetic-voice"))
    window._open_eleven()
    page = window._eleven_page
    page.replace_key.click()
    requests = []
    window.efendija_test_requested.connect(lambda: requests.append(True))
    assert page.test_button.isEnabled()
    page.key_input.setText("replacement-key")
    page.test_button.click()
    assert requests == []
    assert "Sačuvajte novi ključ" in page.connection.text()
    page.save_key.click()
    page.check_button.click()
    qtbot.waitUntil(lambda: account.state.options is not None)
    page.test_button.click()
    assert requests == [True]


def test_saved_key_hides_editor_and_replacement_cancel_preserves_credential(settings):
    window, store, _client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page
    assert page.saved_key.isVisible()
    assert page.replace_key.isVisible() and page.remove_key.isVisible()
    assert not any(
        control.isVisible() for control in (page.key_input, page.show_key, page.save_key)
    )
    page.replace_key.click()
    assert page.key_input.isVisible() and page.key_input.text() == ""
    assert page.cancel_key.isVisible() and not page.saved_key.isVisible()
    page.key_input.setText("unsaved-replacement")
    page.show_key.click()
    page.cancel_key.click()
    assert store.key == account.config.key == "original-key"
    assert page.key_input.text() == "" and page.key_input.echoMode() == QLineEdit.Password
    assert not page.key_input.isVisible() and page.saved_key.isVisible()


def test_removing_saved_key_opens_empty_masked_editor(settings):
    window, store, _client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page
    page.remove_key.click()
    assert store.key == "" and not account.state.has_key
    assert page.key_input.isVisible() and page.key_input.text() == ""
    assert page.key_input.echoMode() == QLineEdit.Password
    assert not page.cancel_key.isVisible() and not page.saved_key.isVisible()


def test_failed_removal_keeps_saved_key_and_editor_closed(settings):
    window, store, _client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page

    def fail():
        raise CredentialError("private diagnostic")

    store.delete = fail
    page.remove_key.click()
    assert store.key == account.config.key == "original-key"
    assert page.saved_key.isVisible() and not page.key_input.isVisible()
    assert "nije uklonjen" in page.connection.text()


def test_empty_replacement_requires_save_or_cancel_before_check(settings):
    window, _store, _client, account, _cleared = settings
    account.save_key("original-key")
    window._open_eleven()
    page = window._eleven_page
    page.replace_key.click()
    page.check_button.click()
    assert not account.state.busy
    assert "Odustani" in page.connection.text()
    window._select_tab(2)
    window._open_eleven()
    assert not page.key_input.isVisible()


@pytest.mark.parametrize("preset", ["default", "human_like", "efendija"])
def test_clicking_current_voice_keeps_exactly_one_voice_selected(settings, preset):
    window, _store, _client, _account, _cleared = settings
    changes = []
    window.speech_settings_changed.connect(changes.append)
    button = window._speech_page._voice_buttons[preset]
    if not button.isChecked():
        button.click()
    before = len(changes)
    for _ in range(2):
        button.click()
        assert button.isChecked()
        assert (
            sum(control.isChecked() for control in window._speech_page._voice_buttons.values()) == 1
        )
    assert window._speech_settings.voice_preset == preset
    assert len(changes) == before


def test_account_refresh_does_not_interrupt_dwell_on_unrelated_control(settings, monkeypatch):
    window, _store, _client, account, _ = settings
    window._select_tab(2)
    window._gaze_settings = replace(
        window._gaze_settings, selection_pause_ms=0, dwell_ms=200, click_cooldown_ms=100
    )
    button = window._speech_page._saved_audio_button
    point = button.mapToGlobal(button.rect().center())
    now = freeze_monotonic(monkeypatch, 10.0)
    window.handle_gaze(point)
    account.changed.emit(replace(account.state, credits_message="Osvježavam kredite…"))
    assert window._gaze_selection.target is button
    now[0] = 10.3
    window.handle_gaze(point)
    assert window._stack.currentWidget() is window._audio_page


def test_standard_speech_second_press_stops_without_another_request(qtbot):
    service = FakeSpeech()
    window = SpeechWindow(service, library_store=FakeLibraryStore(), alarm_sound=FakeAlarmSound())
    qtbot.addWidget(window)
    window.show()
    window._input.setText("SELAM")
    window._play_button.click()
    service.playback_changed.emit(service.request_id, "speaking")
    assert window._play_button.text() == "Zaustavi"
    window._play_button.click()
    assert len(service.requests) == 1 and service.stop_calls == 1
    assert window._input.text() == "SELAM"


@pytest.mark.parametrize("mode", ["phrases", "answers"])
def test_stop_remains_available_while_editing_saved_entry(speech, mode):
    window, service, _ = speech
    window._view_mode = mode
    if mode == "answers":
        window._category_index = 0
    window._show_list_level()
    window._start_editor()
    window._input.setText("NACRT")
    assert window._play_button.isEnabled()
    assert window._play_button.text() == "Zaustavi"
    previous = len(service.requests)
    window._play_button.click()
    assert service.stop_calls == 1 and len(service.requests) == previous
    assert window._input.text() == "NACRT"
    assert not window._play_button.isEnabled()


def test_missing_selected_model_cannot_start_paid_test(settings, qtbot):
    window, _store, client, account, _ = settings
    account.save_key("key")
    client.options = lambda *_: AccountOptions(
        (("synthetic-voice", "Probni glas"),), (("other-model", "Drugi model"),)
    )
    account.check()
    qtbot.waitUntil(lambda: account.state.options is not None)
    window.update_speech_settings(
        SpeechSettings(voice_preset="efendija", elevenlabs_voice_id="synthetic-voice")
    )
    window._select_tab(2)
    assert not window._speech_page._test_speech_button.isEnabled()
    window._open_eleven()
    assert not window._eleven_page.test_button.isEnabled()
