from __future__ import annotations

from dataclasses import replace

import pytest
from _speech_fakes import FakeCredentials, FakeElevenClient
from _ui_fakes import FakeAlarmSound, FakeLibraryStore, FakeSpeech
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QLineEdit

from pogled_assist.interaction.mouse_controller import GazeSettings
from pogled_assist.speech.eleven_account import ElevenAccount
from pogled_assist.speech.speech_library import PhraseRecord, SpeechLibrary
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.speech.voice_state import VoiceState
from pogled_assist.tracking.feedback import TrackingNotice
from pogled_assist.ui.settings_window import SettingsWindow
from pogled_assist.ui.speech_window import SpeechWindow

pytestmark = pytest.mark.e2e


@pytest.fixture
def settings(qtbot, qapp, monkeypatch):
    monkeypatch.setattr("pogled_assist.ui.settings_window.is_windows_startup_enabled", lambda: False)
    for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    store, client = FakeCredentials(), FakeElevenClient()
    account = ElevenAccount(qapp, store=store, client=client)
    cleared = []
    window = SettingsWindow(
        GazeSettings(), SpeechSettings(), eleven_account=account,
        clear_audio=lambda: cleared.append(True) or True,
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
    window._voice_buttons["efendija"].click()
    assert changes[-1].voice_preset == "efendija"
    assert window._test_speech_button.text() == "Isprobaj Efendiju"
    window._eleven_button.click()
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
    assert changes[-1].elevenlabs_model_id == "eleven_v3"
    tests = []
    window.efendija_test_requested.connect(lambda: tests.append(True))
    page.test_button.click()
    assert tests == [True]
    assert client.calls == []
    page.key_input.setText("unsaved-private-key")
    window._select_tab(2)
    assert page.key_input.text() == ""
    assert window._voice_buttons["efendija"].isChecked()


def test_setup_pages_fit_display_and_controls_keep_gaze_size(settings, qtbot):
    window, _store, _client, _account, _cleared = settings
    window._voice_buttons["efendija"].click()
    for open_page, controls in (
        (lambda: window._select_tab(2), tuple(window._voice_buttons.values())),
        (window._open_eleven, (window._eleven_page.key_input, window._eleven_page.save_key,
                              window._eleven_page.voice, window._eleven_page.model,
                              window._eleven_page.test_button)),
        (window._open_audio, (window._audio_page.clear_button,)),
    ):
        open_page()
        qtbot.wait(1)
        assert window.size().width() == 1280 and window.size().height() == 720
        for control in controls:
            assert control.isVisible()
            assert control.height() >= 58
            assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))


def test_audio_clear_preserves_voice_and_settings_choice(settings):
    window, _store, _client, _account, cleared = settings
    window._voice_buttons["efendija"].click()
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
        VoiceState(), VoiceState("human_like", "quota"), VoiceState("human_like", "offline"),
        VoiceState("human_like", "timeout"), VoiceState("human_like", "invalid_key"),
        VoiceState("default", "offline"), VoiceState(cached=True),
        VoiceState(partial=True), VoiceState(recovered=True),
    ):
        service.publish_voice(state)
        window.set_speech_notice(state, immediate=True)
        qtbot.wait(1)
        assert window._input.text() == "SAČUVANA FRAZA."
        assert service.settings.voice_preset == "efendija"
        assert {key: QRect(button.geometry()) for key, button in window._action_buttons.items()} == before
        notice = window._message_header.notice
        assert notice.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert notice.focusPolicy() == Qt.NoFocus
        if state.notice is not None:
            assert notice.notice.title == state.notice[1]
            assert notice.notice.detail == state.notice[2]


def test_recovery_hides_itself_after_five_seconds_and_tracking_has_priority(speech, qtbot, monkeypatch):
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
    assert service.saved_texts == set()
