# Bosnian voice listening comparison

This procedure supports [issue #3](https://github.com/Hasan-Smajlovic/Pogled-Assist/issues/3): decide whether a candidate sounds acceptably close to ef. Fikret while remaining understandable. It prepares a repeatable listening session; it does not record a passed comparison or select a voice on the user's behalf.

## Agree before listening

Ask ef. Fikret which characteristics matter: familiar timbre, comfortable pace, natural sentence endings, pauses and Bosnian pronunciation. These are discussion prompts, not an agreed description of his voice. Agree on the sentences below and allow him to replace any unsuitable sentence before the first comparison. Keep the agreed set unchanged when comparing candidates.

The issue includes a cleaned lecture sample in [Hasan's reference comment](https://github.com/Hasan-Smajlovic/Pogled-Assist/issues/3#issuecomment-6151391766). Confirm that it is the intended reference and select a short passage for listening. The lecture and test sentences contain different words: compare voice characteristics against the lecture, and intelligibility against the written test sentence. Do not treat the cleaned recording as proof of synthesis quality or upload it to a voice service as part of this procedure.

## Candidate and setup

- Compare **Standardni** (eSpeak NG, Bosnian), **Prirodni** (Goran) and the intended **Efendija** voice where available. Efendija is proposed in [PR #83](https://github.com/Hasan-Smajlovic/Pogled-Assist/pull/83); this guide does not imply it is already in an installed release.
- Follow the [Speech section of the user guide](../USER_GUIDE.md#speech) for the revision being tested. Record the exact app commit/build, Windows version, audio output device and volume, selected voice and model, stability/similarity settings, and standard-voice speed. Keep device, volume and settings fixed during a comparison round.
- Verify Goran can actually speak before comparing it. [PR #88](https://github.com/Hasan-Smajlovic/Pogled-Assist/pull/88) updates edge-tts to 7.3.0 for the HTTP 403 failure. Record the installed dependency version; a failed online request is not a low-quality voice sample.
- The candidate in #83 requires an ElevenLabs account, access to the intended saved voice, a compatible Bosnian model, internet and credits. It uses an existing voice; this comparison does not create or clone one. Use the setup instructions in that candidate's user guide rather than copying credentials into a report.
- Standardni works offline. Prirodni sends text to Microsoft; Efendija sends text to ElevenLabs and may spend credits. Use only the agreed test sentences. Do not publish API keys, account details, private messages, reference recordings or generated voice clips in the repository.

## Proposed sentence set

These sentences are synthetic test material, not quotations from ef. Fikret. Confirm the final set with him before generating paid samples.

| ID | Sentence | Listen for |
| --- | --- | --- |
| V01 | Selam. Dobro mi došli. | Greeting, timbre and sentence endings |
| V02 | Molim te, dodaj mi čašu vode. | Short everyday request; č and š |
| V03 | Želim razgovarati s porodicom. | ž, connected speech and clarity |
| V04 | Đak će doći, a džem je već na stolu. | Distinction between đ, dž, ć and č |
| V05 | Ljiljana i njena prijateljica čekaju ispred kuće. | lj, nj and longer words |
| V06 | Možeš li otvoriti prozor? Hvala ti. | Question versus statement and pause |
| V07 | Danas je lijep dan, ali bih prvo želio malo odmoriti. | Longer sentence, pace and comma pause |
| V08 | Sastanak je u 14:30, a cijena je 12,50 KM. | Numbers, time and local abbreviations |

For V08, agree on acceptable spoken forms before scoring; for example, whether the listener expects a 24-hour time or a conversational equivalent. Do not mark one form wrong after hearing it without an agreed expectation.

## Run the comparison

1. Let the listener hear the agreed reference passage at a comfortable volume. Ask whether he is ready to continue; allow breaks or an early stop.
2. Use the same agreed sentence for every voice. Have a helper label the voices A/B/C and keep the mapping separate until scoring is finished. Rotate the order between sentences so the same voice is not always first. If a helper cannot hide the labels, record that the session was unblinded.
3. Have another listener who has not seen the sentence repeat or write what they understood after the first playback. Record incorrect or missing words. If no second listener is available, mark this check Not run; reading along is not a substitute for it.
4. Ask ef. Fikret for separate similarity, clarity and comfort ratings. Record each replay, interruption, missing sample or obvious pronunciation problem. A clip that did not play receives Not run/Failed, not a numeric quality rating.
5. Check the application's **actual** voice/status, not only the selected preset. In #83, failed Efendija preparation can use Prirodni, then Standardni. Label fallback audio with the voice actually heard; exclude it from the Efendija similarity score. Record cached playback separately from a newly generated sample so an old clip is not mistaken for a changed setting.
6. After scoring, reveal the mapping and ask which option he prefers and whether it is acceptable for everyday use. Change one setting at a time for another round, label the new round, and agree before spending more credits. Do not generate every sentence repeatedly by default.

The proposed rating scale is 1 to 5: similarity from **not similar** to **very similar**, clarity from **hard to understand** to **fully clear**, and comfort from **uncomfortable** to **comfortable for everyday use**. Confirm that these labels are usable for the listener; a verbal preference or yes/no response is acceptable if the scale is tiring. Record the method used.

## Record the result

Use one row per sentence and voice. Keep the reference audio and any voice samples outside the public repository; a text-only summary is enough for the issue.

| Round / sentence | Hidden label / actual voice | Model and tuning | New / cached / fallback | Similarity | Clarity | Comfort | Misheard words or failure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Not run | — | — | — | — | — | — | — |

Record the session date, tested commit/build, agreed reference passage, agreed sentence set, listener roles, settings, and the final preference. Do not infer an acceptable result from a high average: retain individual pronunciation failures and the user's explicit accept/reject/defer decision. Ask whether the accepted option is suitable for ordinary conversation, not only for the greeting.

Issue #3 remains open until the user confirms acceptable similarity and clarity and setup, runtime requirements and fallback behavior are documented for the chosen implementation. This comparison does not replace the [manual Windows/Tobii checks](../UI_DEVELOPMENT.md), verify gaze accuracy, or establish packaged online playback. Those results must be recorded separately.
