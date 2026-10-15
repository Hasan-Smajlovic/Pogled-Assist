from __future__ import annotations

import threading

import pytest
from _speech_fakes import FakeCredentials, FakeElevenClient
from PySide6.QtCore import QObject

from pogled_assist.speech.eleven_account import ElevenAccount
from pogled_assist.speech.speech_service import SpeechSettings
from pogled_assist.windows.credentials import CredentialError


@pytest.fixture
def account(qapp, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    owner = QObject()
    store, client = FakeCredentials(), FakeElevenClient()
    account = ElevenAccount(owner, store=store, client=client)
    account.configure(SpeechSettings())
    yield account, store, client
    account.cancel_check()


def test_saved_key_is_reloaded_by_next_account_without_using_settings_json(account):
    current, store, client = account
    assert current.save_key("synthetic-private-key")
    reopened = ElevenAccount(current.parent(), store=store, client=client)
    reopened.configure(SpeechSettings())
    assert reopened.config.key == "synthetic-private-key"
    assert "synthetic-private-key" not in repr(reopened.state)
    assert "synthetic-private-key" not in repr(reopened.config)
    assert "synthetic-private-key" not in repr(reopened._settings)


def test_connection_check_only_reads_account_and_does_not_generate_audio(account, qtbot):
    current, _store, client = account
    current.save_key("synthetic-key")
    checked = []
    current.checked.connect(lambda *_: checked.append(True))
    current.check()
    qtbot.waitUntil(lambda: bool(checked))
    assert client.calls == []
    assert current.state.options.voices[0][0] == "synthetic-voice"


def test_removed_key_invalidates_late_check(account, qtbot):
    current, store, client = account
    current.save_key("synthetic-key")
    entered, release = threading.Event(), threading.Event()
    original = client.options

    def blocked(*args):
        entered.set()
        release.wait(3)
        return original(*args)

    client.options = blocked
    try:
        current.check()
        assert entered.wait(1)
        current.remove_key()
        release.set()
        qtbot.wait(50)
        assert not current.state.has_key and store.key == ""
        assert current.state.options is None
    finally:
        release.set()


def test_credential_write_failure_preserves_previous_key(account):
    current, store, _client = account
    current.save_key("original-key")

    def fail(_value):
        raise CredentialError("private key must never appear in UI")

    store.write = fail
    assert not current.save_key("replacement-key")
    assert current.config.key == "original-key"
    assert "private key" not in current.state.message
