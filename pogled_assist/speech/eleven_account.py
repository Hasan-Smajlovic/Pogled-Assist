"""Settings access to credentials and free account checks on the Qt thread."""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..windows.credentials import CredentialError, WindowsCredentialStore
from .elevenlabs import AccountOptions, BoundedCall, ElevenClient, configuration
from .voice_state import REASONS, SpeechCancelled, VoiceError


@dataclass(frozen=True)
class AccountState:
    has_key: bool = False
    environment_key: bool = False
    busy: bool = False
    message: str = "Dodajte ElevenLabs ključ."
    options: AccountOptions | None = None


class ElevenAccount(QObject):
    changed = Signal(object)
    credentials_changed = Signal()
    checked = Signal(object, object)
    _completed = Signal(int, object, str)

    def __init__(self, parent: QObject, *, store=None, client=None) -> None:
        super().__init__(parent)
        self.store = store or WindowsCredentialStore()
        self.client = client or ElevenClient()
        self._network = BoundedCall()
        self._key = ""
        self._revision = 0
        self._cancel = Event()
        self._settings = None
        self.state = AccountState()
        self._completed.connect(self._finish, Qt.QueuedConnection)
        try:
            self._key = self.store.read()
            self._publish("Ključ je sačuvan. Provjerite vezu.")
        except (CredentialError, UnicodeError, OSError):
            self._publish("Windows nije mogao pročitati sačuvani ključ.")

    def configure(self, settings) -> None:
        self._settings = settings

    @property
    def config(self):
        return configuration(self._settings, self._key)

    def save_key(self, value: str) -> bool:
        try:
            self.store.write(value)
        except (CredentialError, OSError):
            self._publish("Ključ nije sačuvan. Pokušajte ponovo.")
            return False
        self.cancel_check()
        self._key = value.strip()
        self._publish("Ključ je sačuvan. Provjerite vezu.")
        self.credentials_changed.emit()
        return True

    def remove_key(self) -> bool:
        try:
            self.store.delete()
        except (CredentialError, OSError):
            self._publish("Ključ nije uklonjen. Pokušajte ponovo.")
            return False
        self.cancel_check()
        self._key = ""
        self._publish("Ključ je uklonjen.")
        self.credentials_changed.emit()
        return True

    def check(self) -> None:
        self.cancel_check()
        revision, cancel, config = self._revision, self._cancel, self.config
        self._publish("Provjeravam vezu…", busy=True)

        def work() -> None:
            options, reason = None, ""
            try:
                options = self._network.run(
                    lambda stop, end: self.client.options(config.key, stop, end), cancel, 5.0
                )
            except SpeechCancelled:
                return
            except VoiceError as error:
                reason = error.reason
            if not cancel.is_set():
                self._completed.emit(revision, options, reason)

        try:
            Thread(target=work, daemon=True, name="elevenlabs-account").start()
        except RuntimeError:
            self._publish("Provjera veze se nije mogla pokrenuti.")

    def cancel_check(self) -> None:
        self._cancel.set()
        self._cancel = Event()
        self._revision += 1
        if self.state.busy:
            self._publish("Provjera veze je prekinuta.", options=self.state.options)

    @Slot(int, object, str)
    def _finish(self, revision: int, options: AccountOptions | None, reason: str) -> None:
        if revision != self._revision:
            return
        if reason:
            self._publish(REASONS.get(reason, REASONS["offline"]))
            return
        message = "ElevenLabs je povezan. Provjera veze ne troši kredite."
        if options.subscription is not None and options.subscription.remaining == 0:
            message = REASONS["quota"] + " Koristi se Prirodni glas."
        self._publish(message, options=options)
        self.checked.emit(self.config, options.subscription)

    def _publish(self, message: str, *, busy=False, options=None) -> None:
        environment_key = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())
        has_key = bool(self._key) or environment_key
        if not has_key and message == "Ključ je sačuvan. Provjerite vezu.":
            message = "Dodajte ElevenLabs ključ."
        if environment_key:
            message += " Koristi se razvojna environment varijabla."
        self.state = AccountState(has_key, environment_key, busy, message, options)
        self.changed.emit(self.state)
