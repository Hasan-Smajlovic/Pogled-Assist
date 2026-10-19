"""Settings access to credentials and free account checks on the Qt thread."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal, Slot

from ..windows.credentials import CredentialError, WindowsCredentialStore
from .elevenlabs import (
    AccountOptions,
    BoundedCall,
    ElevenClient,
    Subscription,
    configuration,
    env_override,
)
from .voice_state import CREDITS_UNAVAILABLE_NOTE, REASONS, SpeechCancelled, VoiceError


@dataclass(frozen=True)
class AccountState:
    has_key: bool = False
    environment_key: bool = False
    busy: bool = False
    message: str = "Dodajte ElevenLabs ključ."
    options: AccountOptions | None = None
    subscription: Subscription | None = None
    credits_busy: bool = False
    credits_message: str = CREDITS_UNAVAILABLE_NOTE


class ElevenAccount(QObject):
    changed = Signal(object)
    credentials_changed = Signal()
    checked = Signal(object, object)
    _completed = Signal(int, object, str)
    _subscription_completed = Signal(int, object, str, bool)

    def __init__(self, parent: QObject, *, store=None, client=None) -> None:
        super().__init__(parent)
        self.store = store or WindowsCredentialStore()
        self.client = client or ElevenClient()
        self._network = BoundedCall()
        self._balance_network = BoundedCall()
        self._key = ""
        self._revision = 0
        self._cancel = Event()
        self._settings = None
        self.state = AccountState()
        self._completed.connect(self._finish, Qt.QueuedConnection)
        self._subscription_completed.connect(self._finish_subscription, Qt.QueuedConnection)
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

    @property
    def can_test_voice(self) -> bool:
        state = self.state
        if not state.has_key:
            return False
        if state.busy or state.options is None:
            return False
        config = self.config
        return _valid_choice(
            config.voice, state.options.voices, "ELEVENLABS_VOICE_ID"
        ) and _valid_choice(config.model, state.options.models, "ELEVENLABS_MODEL_ID")

    def save_key(self, value: str) -> bool:
        return self._change_credential(value.strip())

    def remove_key(self) -> bool:
        return self._change_credential(None)

    def _change_credential(self, value: str | None) -> bool:
        removing = value is None
        try:
            if removing:
                self.store.delete()
            else:
                self.store.write(value)
        except (CredentialError, OSError):
            self._publish(
                "Ključ nije uklonjen. Pokušajte ponovo."
                if removing
                else "Ključ nije sačuvan. Pokušajte ponovo."
            )
            return False
        self.cancel_check()
        self._key = value or ""
        self.state = AccountState()
        self._publish("Ključ je uklonjen." if removing else "Ključ je sačuvan. Provjerite vezu.")
        self.credentials_changed.emit()
        return True

    @staticmethod
    def _start_worker(name, work, failed) -> None:
        try:
            Thread(target=work, daemon=True, name=name).start()
        except RuntimeError:
            failed()

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

        self._start_worker(
            "elevenlabs-account",
            work,
            lambda: self._publish("Provjera veze se nije mogla pokrenuti."),
        )

    def cancel_check(self) -> None:
        self._cancel.set()
        self._cancel = Event()
        self._revision += 1
        if self.state.credits_busy:
            self.state = replace(self.state, credits_busy=False)
        if self.state.busy:
            self._publish("Provjera veze je prekinuta.", options=self.state.options)

    @Slot(int, object, str)
    def _finish(self, revision: int, options: AccountOptions | None, reason: str) -> None:
        if revision != self._revision:
            return
        if reason:
            self.state = replace(
                self.state, subscription=None, credits_message=CREDITS_UNAVAILABLE_NOTE
            )
            self._publish(REASONS.get(reason, REASONS["offline"]))
            return
        self._publish("ElevenLabs je povezan. Provjera veze ne troši kredite.", options=options)
        self.checked.emit(self.config, None)
        self.refresh_subscription(allow_recovery=True)

    def refresh_subscription(self, *, allow_recovery: bool = False) -> None:
        """Refresh the free account balance without changing voice availability."""
        if not self.state.has_key:
            return
        if self.state.credits_busy or self.state.busy:
            return
        revision, cancel, key = self._revision, self._cancel, self.config.key
        self.state = replace(self.state, credits_busy=True, credits_message="Osvježavam kredite…")
        self.changed.emit(self.state)

        def work() -> None:
            subscription, reason = None, ""
            try:
                subscription = self._balance_network.run(
                    lambda stop, end: self.client.subscription(key, stop, end), cancel, 5.0
                )
            except SpeechCancelled:
                return
            except VoiceError as error:
                reason = error.reason
            if not cancel.is_set():
                self._subscription_completed.emit(revision, subscription, reason, allow_recovery)

        self._start_worker(
            "elevenlabs-credits",
            work,
            lambda: self._finish_subscription(revision, None, "offline", allow_recovery),
        )

    @Slot(int, object, str, bool)
    def _finish_subscription(self, revision, subscription, reason, allow_recovery=False) -> None:
        if revision != self._revision:
            return
        self.state = replace(
            self.state,
            subscription=subscription,
            credits_busy=False,
            credits_message=(
                CREDITS_UNAVAILABLE_NOTE if reason else "Posljednje provjereno stanje računa."
            ),
        )
        self.changed.emit(self.state)
        if allow_recovery and subscription is not None:
            self.checked.emit(self.config, subscription)

    def _publish(self, message: str, *, busy=False, options=None) -> None:
        environment_key = bool(env_override("ELEVENLABS_API_KEY"))
        has_key = bool(self._key) or environment_key
        if not has_key and message == "Ključ je sačuvan. Provjerite vezu.":
            message = "Dodajte ElevenLabs ključ."
        if environment_key:
            message += " Koristi se razvojna environment varijabla."
        self.state = replace(
            self.state,
            has_key=has_key,
            environment_key=environment_key,
            busy=busy,
            message=message,
            options=options,
        )
        self.changed.emit(self.state)


def _valid_choice(value, choices, variable):
    return bool(value) and (value in dict(choices) or bool(env_override(variable)))
