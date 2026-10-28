# Efendija voice and ElevenLabs setup

Open **Postavke > Govor i tastatura**, choose **Efendija**, then **Podesi ElevenLabs**. Voice and model choices are grouped with stability and similarity; test playback, credits and privacy information have a separate group. **Provjeri vezu** checks the account. Its adjacent information button explains the check without making a speech request; open it by mouse, gaze, Space or Enter, and close it with Escape or the same button. Required warnings remain visible outside this help. The ElevenLabs account must have access to the intended ef. Fikret voice and a model supporting Bosnian. The app does not create or clone the voice.

## Set up the key and voice

1. Create an ElevenLabs API key with **Text to Speech**, **Voices: Read**, and **Models: Read** enabled. Text to Speech alone cannot load the voice/model choices. **User: Read** is optional for reading the credit balance.
2. Enter the key and select **Sačuvaj ključ**. A successful save hides the input and shows **Ključ je sačuvan**, **Zamijeni ključ**, and **Ukloni ključ**. **Zamijeni ključ** opens an empty masked editor. **Odustani** discards the new input and retains the previous key; **Ukloni ključ** deletes it and opens an empty editor. Windows Credential Manager retains the saved key for the current Windows user across application restarts and updates. A failed save keeps the input masked for retry and preserves the previous credential. Save a replacement before checking it or testing speech; both actions use the saved key.
3. Select **Provjeri vezu**, then choose the intended voice from **Moji glasovi** and a Bosnian model. New settings start with `eleven_v4`; existing saved model choices are retained. The list includes only voices saved in the ElevenLabs account, including saved library voices, rather than the default catalog. If a previously selected voice is absent, select a voice from this list before testing; the app does not replace it automatically. An empty collection shows **Nema glasova**. Add the voice on ElevenLabs and check again. Voice/model selections save automatically. The connection check only reads catalogs and optional account information; it neither generates speech nor proves that Text to Speech is permitted or that audio will play.
4. Choose **Kreativno**, **Prirodno**, or **Stabilno** for **Stabilnost** (0%, 50%, or 100%; default **Prirodno**). Existing percentages load as the nearest choice. **Sličnost glasa** defaults to **80%**; use its slider or large **− / +** buttons to change it by five percentage points. Changes save automatically. Efendija preparation/playback stops when its voice, model or tuning changes; these unused settings do not interrupt Standardni or Prirodni speech.
5. Select **Isprobaj Efendiju** to hear **SELAM. DOBRO MI DOŠLI.** This spends ElevenLabs credits. The test succeeds only with Efendija, without cached audio or a fallback. Confirm similarity, pronunciation and clarity by listening.

## Credits and connection errors

The credit bar shows the latest account balance as **Preostalo / limit** and a percentage, yellow below 20% and red below 10%. It refreshes without generating speech when ElevenLabs settings open and after Efendija speech finishes. Enable **User: Read** to see it. Missing permission or a failed request shows **Stanje kredita nije dostupno** and does not disable speech. Account credits do not establish an API key's separate quota or the final cost of the next message.

Settings disable the test button during preparation/playback and provide **Zaustavi**. For the shared Speech button and Enter behavior, see [Speech](../USER_GUIDE.md#speech).

An explicit permission error identifies missing catalog access separately from an invalid key. A failed check retains the saved key and voice choice. Development overrides `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, and `ELEVENLABS_MODEL_ID` take precedence over saved values; overridden controls are disabled.

## Text transfer and fallback

Efendija sends sentence-case text to ElevenLabs; square brackets become parentheses to prevent audio-tag interpretation. The displayed message stays unchanged. ElevenLabs may retain submitted text. Its [Zero Retention Mode](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode) is restricted to eligible Enterprise customers; it is not a general guarantee for every account.

If preparation fails, the same message tries Prirodni (Microsoft's online service), then Standardni (offline), while the selected voice remains Efendija. The display names the voice actually used. Preparation waits at most 30 seconds for ElevenLabs generation and the full audio download, and three seconds for Prirodni before falling back. An interrupted playback preserves the message and requires another **Izgovori**; it does not repeat automatically in another voice. Changing the active Efendija voice, model or tuning cancels its preparation/playback. The five-second connection check only reads catalogs; its success does not measure synthesis time.

After a quota failure, uncached messages use fallback for 60 seconds before retrying ElevenLabs. **Provjeri vezu** can permit an earlier retry if a positive balance is newly available or improved; passive balance refresh does not. After the cooldown, a new **Izgovori** can retry even without User: Read. The green **Efendijin glas je ponovo dostupan** notice disappears after five visible seconds. Tracking warnings take priority; the recovery notice receives a fresh five seconds when it becomes visible again. Key-specific quotas may differ from the account balance. Automatic top-ups are controlled on the ElevenLabs account; disable them there if unwanted.

## Saved audio

**Sačuvani zvuk** keeps downloaded Efendija audio when the whole message matches one saved phrase or answer, ignoring case and repeated whitespace. Stopping playback or an output failure retains the clip; unreadable audio is discarded. Repetition works offline without new credits.

**Zvuk nije sačuvan** warns that storage failed: speech can finish, but repetition may spend credits. Other messages and combinations are not cached.

Editing/deleting an entry removes all its clips. Changing voice, model or tuning retains earlier clips for switching back. The 256 MiB limit removes least recently used clips first. A library read failure disables cache access until a successful retry without deleting clips. **Obriši sačuvani zvuk** removes clips, not phrases or answers; removing the API key does not clear clips. Incompatible cache formats or text-preparation versions require regeneration, which can spend credits. See [storage details](../ARCHITECTURE.md#persistent-data-and-logs) for file locations and backup behavior.
