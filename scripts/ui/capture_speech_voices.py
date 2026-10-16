"""Deterministic ElevenLabs and speech provider gallery scenarios."""

from dataclasses import replace
from pogled_assist.speech.eleven_account import AccountState
from pogled_assist.speech.elevenlabs import AccountOptions, Subscription
from pogled_assist.speech.voice_state import VoiceState


class CaptureSpeechVoices:
    def capture_eleven_settings(self, size) -> None:
        settings = replace(
            self.speech_settings,
            voice_preset="efendija",
            elevenlabs_voice_id="preview-voice",
            elevenlabs_model_id="eleven_v4",
        )
        account = self.settings._eleven_account
        options = AccountOptions(
            (("preview-voice", "Efendija Fikret"),),
            (("eleven_v4", "Eleven v4"),),
            None,
        )
        account.state = AccountState(
            True,
            message="ElevenLabs je povezan.",
            options=options,
            subscription=Subscription(6000, 30000),
            credits_message="Posljednje provjereno stanje računa.",
        )
        self.settings.update_speech_settings(settings)
        self.settings._account_changed(account.state)
        self.settings._select_tab(2)
        self.capture(self.settings, "settings-efendija", "Settings: Efendija", size=size)
        self.settings._open_eleven()
        for name, state in _account_scenarios(options, account.state):
            account.state = state
            self.settings._eleven_page.refresh(state)
            if name in ("replacing", "save-failed"):
                self.settings._eleven_page._replace_key()
            if name == "save-failed":
                self.settings._eleven_page.key_input.setText("synthetic-replacement")
            self.capture(
                self.settings, f"settings-elevenlabs-{name}", f"ElevenLabs: {name}", size=size
            )
            self.settings._eleven_page.clear_input()
        for name, subscription in (
            ("low-credits", Subscription(25500, 30000)),
            ("critical-credits", Subscription(28500, 30000)),
        ):
            account.state = AccountState(
                True,
                message="ElevenLabs je povezan.",
                options=options,
                subscription=subscription,
                credits_message="Posljednje provjereno stanje računa.",
            )
            self.settings._eleven_page.refresh(account.state)
            self.capture(
                self.settings, f"settings-elevenlabs-{name}", f"ElevenLabs: {name}", size=size
            )
        for state in ("preparing", "speaking"):
            self.settings.set_speech_playback_state(state)
            self.capture(
                self.settings, f"settings-elevenlabs-{state}", f"ElevenLabs: {state}", size=size
            )
        self.settings.set_speech_playback_state("finished")
        self.settings._open_audio()
        self.capture(self.settings, "settings-saved-audio", "Settings: saved audio", size=size)
        account.state = AccountState()
        self.settings.update_speech_settings(self.speech_settings)

    def capture_speech_voices(self) -> None:
        settings = replace(self.speech_settings, voice_preset="efendija")
        self.speech.update_settings(settings)
        self.speech._input.setText("SELAM. DOBRO MI DOŠLI.")
        for state in ("preparing", "speaking"):
            self.speech.set_playback_state(state)
            self.speech._status_label.setText(
                "Pripremam govor." if state == "preparing" else "Poruka se izgovara."
            )
            self.capture(self.speech, f"speech-{state}", f"Speech: {state}")
        self.speech.set_playback_state("finished")
        for name, state in (
            ("efendija", VoiceState()),
            ("quota", VoiceState("human_like", "quota")),
            ("offline", VoiceState("human_like", "offline")),
            ("timeout", VoiceState("human_like", "timeout")),
            ("invalid", VoiceState("human_like", "invalid_key")),
            ("standard", VoiceState("default", "offline")),
            ("cached", VoiceState(cached=True)),
            ("partial", VoiceState(partial=True)),
            ("recovered", VoiceState(recovered=True)),
        ):
            self.speech.set_speech_notice(state, immediate=True)
            self.speech._status_label.setText(f"Glas: {state.label}")
            self.capture(self.speech, f"speech-voice-{name}", f"Speech voice: {name}")
        self.speech.update_settings(self.speech_settings)
        self.speech._input.clear()



def _account_scenarios(options, connected):
    return (
            ("connected", connected),
            ("replacing", connected),
            (
                "empty-voices",
                AccountState(
                    True,
                    message="ElevenLabs je povezan.",
                    options=replace(options, voices=()),
                ),
            ),
            ("missing", AccountState()),
            ("invalid", AccountState(True, message="Provjerite ElevenLabs ključ u Postavkama.")),
            (
                "permission",
                AccountState(
                    True, message="Za listu glasova dozvolite čitanje glasova na ElevenLabs ključu."
                ),
            ),
            ("save-failed", AccountState(True, message="Ključ nije sačuvan. Pokušajte ponovo.")),
            (
                "quota",
                AccountState(
                    True,
                    message="Nema dovoljno ElevenLabs kredita. Koristi se Prirodni glas.",
                    options=options,
                    subscription=Subscription(30000, 30000),
                    credits_message="Posljednje provjereno stanje računa.",
                ),
            ),
        )
