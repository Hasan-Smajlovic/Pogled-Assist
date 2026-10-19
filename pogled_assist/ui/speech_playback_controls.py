"""Playback actions and voice notices shared by the Speech screen."""

from __future__ import annotations

import logging

from ..keyboard_layouts import ARABIC_SCRIPT
from ..speech.voice_state import VoiceState

logger = logging.getLogger(__name__)


class SpeechPlaybackControls:
    def _sync_voice_notice(self) -> None:
        enabled = self._speech_settings.uses_efendija
        self.set_speech_notice(self._speech.voice_state if enabled else None)

    def _voice_changed(self, request_id: int, state: VoiceState) -> None:
        if request_id == self._playback_id:
            enabled = self._speech_settings.uses_efendija
            self.set_speech_notice(state if enabled else None)
            if enabled:
                self._status_label.setText(f"Glas: {state.label}")

    def _playback_changed(self, request_id: int, state: str) -> None:
        if request_id != self._playback_id:
            if request_id != self._speech.request_id:
                return
            self._playback_id = request_id
        self.set_playback_state(state)
        self._update_view_controls()
        message = {
            "preparing": "Pripremam govor.",
            "speaking": "Poruka se izgovara.",
            "finished": "Čitanje je završeno.",
            "failed": "Govor nije uspio. Pokušajte ponovo.",
            "stopped": "Govor je zaustavljen.",
        }[state]
        if state == "finished" and self._speech_settings.uses_efendija:
            message = f"Glas: {self._speech.voice_state.label}"
        self._set_status(message)

    def _play(self, *, source: str = "keyboard") -> None:
        if self._speech.is_busy:
            self._speech.stop()
            return
        if self._editor is not None or self._dialogs.active is not None:
            return
        if not self._play_button.isEnabled():
            return
        text = self._input.text().strip()
        if not text:
            self._set_status("Prvo sastavite poruku.")
            return
        self._speak_message(text, source)

    def _speak_message(self, text, source):
        logger.info("Speech playback requested: source=%s.", source)
        if self._speech_settings.keyboard_script != ARABIC_SCRIPT:
            self._composition.submit()
            self._suggestions.persist()
        if self._speech.speak(text, self._speech_settings):
            self._playback_id = self._speech.request_id
            self.set_playback_state("preparing")
            self._set_status("Pokrećem govor.")
        else:
            self._playback_id = None
            self.set_playback_state("failed")
            self._set_status("Odabrani glas nije dostupan.")
