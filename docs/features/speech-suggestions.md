# Bosnian speech suggestions

The five `Brzi izbor` buttons in the Speech screen help a person compose their
own Bosnian message in Latin script with fewer gaze selections. They complete
the word being typed or suggest the next word. Prediction runs offline from
bundled language data; the person's learned words stay on the local machine.

This document defines the feature's behaviour and acceptance criteria. The
[user guide](../USER_GUIDE.md#speech) explains how to use it. The
[architecture](../ARCHITECTURE.md) owns runtime responsibilities and persistent
data, the [development guide](../DEVELOPMENT.md) owns commands and UI review,
and the [Windows release guide](../WINDOWS_RELEASE.md) owns installation and
rollback. The [HTML design reference](../design/speech-keyboard-reference.html)
owns visible layout and interaction states.

## Where suggestions appear

Suggestions work in the conversation message and while adding a saved phrase or
answer. They use the text of the active input and never edit another input.
Category names have no suggestions and do not contribute to learning. Opening
or closing an editor preserves the conversation message. Switching inputs
invalidates pending results and gaze dwell so a result from one input cannot
be selected in another.

All five button positions stay fixed. An unfinished word requests completions;
text ending in a space requests the next word. An empty input offers useful
sentence starters. Refresh after typing, deletion, punctuation, selection, or
undo. Show at most five distinct candidates, leave unused positions inactive,
and leave all positions inactive when no word matches. Do not fill them with
unrelated words or rotate unchanged results.

Suggestions apply only when the caret is at the end of the active input and no
text is selected. Moving the caret or selecting text disables the buttons and
cancels pending selection. Returning to the end restores applicable candidates
without moving the caret or changing the text. Before displaying or applying a
result, check its input, text, caret, selection, and request revision so an old
worker result cannot bypass these conditions.

## Choosing and editing a word

Selecting a completion replaces only the unfinished final word. Selecting a
next word appends it. Both leave one ordinary space for continued typing and
keep the rest of the message. Selection refreshes suggestions; only `Izgovori`
starts speech.

In these examples, `␠` represents an ordinary trailing space:

| Before selection | Selected word | After selection |
| --- | --- | --- |
| `ŽELIM VO` | `VODU` | `ŽELIM VODU␠` |
| `ŽELIM␠` | `RAZGOVARATI` | `ŽELIM RAZGOVARATI␠` |
| Empty input | `SELAM` | `SELAM␠` |

### Spacing around punctuation

If the next typed character after a suggestion is `.`, `,`, `?`, or `!`, remove
only the space inserted by that suggestion and put punctuation against the word.
Typing `.` or `?` at the end also adds one space for the next sentence. Ignore
an immediately repeated space. These rules apply to gaze keyboard, mouse, and
physical keyboard input in every supported editor; they do not reformat older
text or add punctuation keys to the gaze keyboard.

Punctuation is a later text edit, so it expires suggestion undo. Removing the
automatic space does not count as correcting or deleting the selected word for
personal learning.

Selecting a next word immediately after punctuation inserts a separating space
if needed and the usual trailing space after the word. Existing whitespace is
reused. For example:

| Before action | Action | After action |
| --- | --- | --- |
| `ŽELIM VODU␠` | Type `.` | `ŽELIM VODU.␠` |
| `ŽELIM VODU.` | Select `HVALA` | `ŽELIM VODU. HVALA␠` |
| `ŽELIM VODU.␠` | Select `HVALA` | `ŽELIM VODU. HVALA␠` |

### Undo

One selection of the suggestion undo control restores the exact text from
before the most recent suggestion. It has no time limit. Looking away, waiting,
or using `Izgovori` leaves it available. A later text edit, including
punctuation or deletion, expires it so undo cannot discard newer text. Selecting
another suggestion replaces the undo opportunity; undo never opens an older
editing history.

Undo belongs to the input where the suggestion was selected. The conversation
keeps its undo state while a phrase or answer editor is open. Each editor has
its own undo, discarded when it closes after save or cancel. A failed save keeps
the editor and its undo available. Undo reverses that selection's personal
learning contribution, even if the message was already submitted for speech;
it cannot reverse audio already played.

## Bosnian text and prediction context

The conversation message, suggestions, category names, answers, and phrases
display and enter in uppercase. Grouped-keyboard input, physical-keyboard
input, pasted text, gaze, and mouse follow the same rule. Normalize the active
input immediately. Older saved library entries may keep their stored case until
edited, but the Speech screen displays and inserts them in uppercase. Matching
and learning treat case variants as the same word without merging distinct
Bosnian letters.

Prefix matching accepts common typing without diacritics while preserving the
candidate's Bosnian spelling. Showing a match does not rewrite typed text;
selection inserts the candidate's spelling.

| Typed prefix | Eligible match |
| --- | --- |
| `zel` | `ŽELIM` |
| `caj` | `ČAJ` |
| `c` | Words starting with `C`, `Č`, or `Ć` |
| `š` | `Š` words, without broadening to plain `S` |
| `d` or `dj` | `Đ` words as well as eligible literal `D` or `DJ` words |
| `dodj` | `DOĐI` |
| `đ` | `Đ` words only |

The `d` and `dj` alternatives also work inside a prefix. They do not make `DŽ`
equivalent to `Đ`. `DŽ`, `LJ`, and `NJ` produce the same matches whether entered
through one grouped key or separate characters; existing grouped-key deletion
still removes each letter pair as one unit. Preserve distinct inflections such
as `VODA`, `VODU`, and `VODE`, and allow personal words absent from the seed.
An apostrophe inside a word is supported, so `KUR` or `KURAN` can complete to
`KUR'AN`.

`.`, `?`, and `!` start a new prediction context. A comma keeps the current
sentence's context. Sentence starters can appear immediately after a boundary,
before a separating space is typed. Base and personal learning use these same
boundaries: short word sequences must not cross a sentence boundary. Earlier
message text and personal preferences remain intact. After editing or undo,
recompute context from the current text.

## Gaze behaviour

Mouse and gaze selection call the same text-editing behaviour. After a
suggestion activates, continuing to look at its button cannot activate the
replacement label. The person must look outside the button and return. A label
change does not count as looking away. Changing text during a pending dwell
cancels that selection.

The existing [gaze compatibility contract](../ARCHITECTURE.md#compatibility-contract)
also applies: both eyes must remain valid before gaze actions continue, and
losing either eye cancels dwell state. The shared selection timing lives in
[`gaze_selection.py`](../../pogled_assist/interaction/gaze_selection.py).

## Personal learning and privacy

The feature learns from the person's intent to speak and from successfully
saved phrase or answer text. It stores word counts and short word contexts in
`data/speech_learning.json`, not full messages or conversation archives. The
bundled base model is separate so application updates cannot erase the personal
profile. Prediction does not send typed text or learned counts to an online
service. The optional online speech voice keeps its separate behaviour described
in the [user guide](../USER_GUIDE.md#speech).

| Event | Learning rule |
| --- | --- |
| Select a suggestion in the conversation | Credit that occurrence and its preceding context. |
| Undo it | Reverse only that selection's credit. |
| Manually change or delete the selected word before submitting that occurrence | Reverse its credit, even if the undo control has expired. Do not reverse it twice or remove earlier uses. |
| Invoke an available `Izgovori` action with nonempty text | Learn new typed occurrences and short contexts when requested, even if voice playback fails. Do not count already credited selections twice. |
| Invoke `Izgovori` again on unchanged text | Add no credit. |
| Extend or revise a submitted message, then invoke `Izgovori` | Credit new or replaced occurrences and new contexts without recrediting unchanged parts. |
| Clear the conversation, compose the same text again, then invoke `Izgovori` | Treat it as a new use. Opening an editor does not count as clearing the conversation. |
| Edit a phrase or answer draft | Offer predictions without learning from the draft or its selections. |
| Successfully save a new or changed phrase or answer | Learn once from the final saved text. Cancelled, failed, or unchanged saves add nothing. |

An unavailable speech action or empty input adds no learning. Earlier submitted
uses remain learned when text is later edited. Message-start frequencies affect
starters; preceding-word evidence affects continuations so a popular word does
not displace contextual candidates everywhere.

### Forgetting a word

`Zaboravi naučenu riječ` in Settings removes the selected word's personal
entry and associated ranking contribution. Other learned words, the current
message, and saved phrases or answers remain unchanged. Forgetting persists
after restart. A base-model word may still appear without its personal boost;
a word known only from learning disappears until later qualifying use teaches
it again. Existing saved text alone must not recreate the removed entry.

### Storage failure

If the personal file cannot be read, preserve it and continue with the bundled
model. Do not overwrite it with an empty profile. If a write fails, keep the
last saved version, show a nonblocking status, and offer a retry through
Settings for gaze and mouse. A failed save or removal must never be reported as
successful. Do not silently restore an old backup that could bring back a
forgotten word. Editing and speech remain available during these failures.

Do not add the person's biography, family details, private correspondence, or
real conversations to the public language data. Evaluation text is synthetic
or project-authored.

## Bundled language data

The general model is prepared from the CC0
[CLASSLA-web.bs 2.0 corpus](https://www.clarin.si/repository/xmlui/handle/11356/2079)
and reviewed Bosnian conversation material. A separate reviewed Islamic layer
adds terminology and phrases without replacing the general model. Preparation
runs before distribution; first launch needs no corpus download, paid inference
service, or network connection. The full source archive is a development input
and is not included in the application.

If the prediction engine is unavailable, message editing and speech remain
usable.

The model uses a sorted prefix index and unigram, bigram, and trigram counts.
Longer contexts back off to shorter ones when evidence is sparse. Personal
counts adjust ranking in the applicable context. The implementation uses the
Python standard library and avoids a new native packaging dependency. This is
a short-context statistical model, so candidate usefulness must be measured;
the engine does not rewrite sentences or use an LLM.

The editable input files, generated reports, and their roles are listed in
[`language/bs/README.md`](../../language/bs/README.md). The prepared model
[metadata](../../pogled_assist/assets/bosnian-model.meta.json) and
[Islamic layer metadata](../../pogled_assist/assets/bosnian-islamic-model.meta.json)
record exact sources, hashes, counts, and configuration. Rebuild commands live
in the [development guide](../DEVELOPMENT.md).

## Evaluation and acceptance

The [frozen evaluation protocol](../../tests/fixtures/speech_suggestions/protocol.md)
compares the grouped keyboard, frequency-only suggestions, and contextual
suggestions. It counts button activations, typing, corrections, spacing, and
undo under the same keyboard rules. It reports sentence starters, next words
before their first letter, and completions after a typed prefix separately.
Gaze departure and return are recorded separately from button activations.

The initial usefulness target is at least 20% fewer required gaze selections
than the grouped keyboard on at least 100 reviewed synthetic messages covering
everyday needs, conversation, humour, memories, and opinions, with results by
conversation type. Development examples can guide model choices.
The original 100-message held-out set has since been inspected in repeated
reviews, so its results are regression evidence. Fresh independent quality
validation requires a new, separately authored set frozen before the model is
selected. Do not train or tune on that set.

The current [development report](../../language/bs/evaluation/reports/development.json),
[held-out regression report](../../language/bs/evaluation/reports/heldout.json),
[learning report](../../language/bs/evaluation/reports/learning.json),
[ranking comparison](../../language/bs/benchmarks/ranking.json), and
[model vocabulary benchmark](../../language/bs/benchmarks/model.json) contain the
measured regression results for the rebuilt model. Their timings describe the
machine used for each run, not the reference Tobii setup. The held-out
regression reports a 46.03% reduction in ideal
button activations against the grouped keyboard. That simulation does not
measure real communication speed or gaze usability.

Full acceptance also requires the following checks on the reference Windows
laptop with real speech and gaze active:

- At least 95% of applicable suggestion updates appear within 100 ms after
  loading. Record initial load time, memory use, and prepared data size
  separately. The prediction worker must not stall the UI.
- The frozen Windows package loads and queries both bundled models offline on
  first launch. Installation, update, and rollback preserve
  `data/speech_learning.json` and a working previous version after failure.
- Mouse and real Tobii selection produce the same text, including spacing and
  Bosnian letters. Both-eye gating, dwell cancellation, reactivation after a
  changing label, AppBar, calibration, and speech work on the target setup.
- A real user can find and select useful words while composing messages with
  gaze; simulated button counts do not establish that experience.
- The actual display resolution and scaling are reviewed against the
  [design reference](../design/speech-keyboard-reference.html).

Software tests and model-only measurements do not establish these Windows and
device results. Follow the [development](../DEVELOPMENT.md#ui-review) and
[release](../WINDOWS_RELEASE.md) checklists and record what actually ran in the
reviewing pull request. The installed user's behaviour remains the compatibility
baseline until those checks are complete.
