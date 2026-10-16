"""Settings speech tests and their status on the hotbar."""

import logging
from .keyboard_layouts import ARABIC_SCRIPT
from .speech.speech_library import saved_entry_texts

logger = logging.getLogger(__name__)
SPEECH_TEST_TEXT = "Zdravo. Ovo je test govora na bosanskom jeziku."
ARABIC_SPEECH_TEST_TEXT = "مَرْحَبًا. هٰذَا اخْتِبَارٌ لِلصَّوْتِ بِاللُّغَةِ الْعَرَبِيَّةِ."

class HotbarSpeech:
    def _setup_speech(self, speech, library_store):
        self._speech = speech
        self._speech_test_id: int | None = None
        self._efendija_test_id: int | None = None
        self._speech.playback_changed.connect(self._speech_playback_changed)
        self._speech.test_finished.connect(self._efendija_test_finished)
        self._settings_save_failed = False
        self._speech.update_settings(self._initial_speech_settings)
        self._speech_library_store = library_store
        library = self._speech_library_store.load()
        self._speech.set_saved_texts(saved_entry_texts(self._speech_library_store, library))

    def _test_current_speech_settings(self) -> None:
        if self._speech.is_busy:
            return
        if self._speech.settings.uses_efendija:
            self._test_efendija()
            return
        try:
            text = (
                ARABIC_SPEECH_TEST_TEXT
                if self._speech.settings.keyboard_script == ARABIC_SCRIPT
                else SPEECH_TEST_TEXT
            )
            if self._speech.speak(text):
                self._speech_test_id = self._speech.request_id
                if self._settings_window is not None:
                    self._settings_window.set_speech_playback_state("preparing")
                self._set_speech_test_status("Test govora je pokrenut.")
            else:
                self._set_speech_test_status(
                    "Govor nije uspio: odabrani glas nije pronađen ili se nije mogao pokrenuti.",
                    "Govor nije uspio.",
                )
        except Exception:
            logger.exception("Speech settings test failed.")
            self._set_speech_test_status("Govor nije uspio.")

    def _speech_playback_changed(self, request_id: int, state: str) -> None:
        if self._settings_window is not None:
            self._settings_window.set_speech_playback_state(state)
        if request_id not in (self._speech_test_id, self._efendija_test_id):
            return
        if request_id == self._efendija_test_id and state in ("finished", "failed"):
            # test_finished already carries the provider's actionable result.
            return
        message = {
            "preparing": "Pripremam govor.",
            "speaking": "Test govora je pokrenut.",
            "finished": "Test govora je završen.",
            "failed": "Govor nije uspio. Pokušajte ponovo.",
            "stopped": "Govor je zaustavljen.",
        }[state]
        self._set_speech_test_status(message)

    def _test_efendija(self) -> None:
        if self._speech.is_busy:
            return
        self._speech_test_id = None
        if self._speech.test_efendija():
            self._efendija_test_id = self._speech.request_id
            if self._settings_window is not None:
                self._settings_window.set_speech_playback_state("preparing")
            self._set_speech_test_status("Pripremam probu Efendije. Proba troši kredite.")
        else:
            self._set_speech_test_status("Proba Efendije se nije mogla pokrenuti.")

    def _efendija_test_finished(self, request_id: int, message: str) -> None:
        if request_id == self._efendija_test_id:
            self._set_speech_test_status(message)

    def _set_speech_test_status(self, text: str, settings_text: str | None = None) -> None:
        self._set_status(text)
        if self._settings_window is not None:
            self._settings_window.set_status(text if settings_text is None else settings_text)

