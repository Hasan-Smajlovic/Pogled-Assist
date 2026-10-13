# Bosnian language data

This directory keeps editable model inputs separate from evaluation data and
generated reports. The installed application does not load these files. It uses
the prepared models under `pogled_assist/assets`.

## Model inputs

- `model/core/conversation.tsv` contains reviewed everyday phrases used to
  supplement the general Bosnian corpus.
- `model/core/spelling.tsv` maps ASCII web-corpus variants to reviewed Bosnian
  spellings during model preparation.
- `model/core/starters.tsv` assigns additional weight to useful sentence
  starters.
- `model/domains/islamic.tsv` contains project-authored Islamic terminology and
  conversation phrases for the separate Islamic model layer.

These TSV files are maintained by hand. Rebuild the corresponding prepared
model and rerun its tests and evaluations after changing one of them.

The prepared models' metadata records the archive or reviewed source, inputs,
preparation script, tokenizer, and model checksums used for each build. Compare
those hashes with the current files before review. Refactoring or formatting a
preparation script can require a rebuild even without an intended behavior change;
follow the [preparation and evaluation commands](#preparation-and-evaluation) for
the rebuild order and commands.

## Evaluation

`evaluation/learning.tsv` contains synthetic personal-learning scenarios. The
JSON files under `evaluation/reports` are generated regression reports and must
match the current prepared models and frozen test fixtures.

## Benchmarks

The JSON files under `benchmarks` are generated model-selection and ranking
reports. Regenerate them with the
[preparation and evaluation commands](#preparation-and-evaluation); do not edit
their measured results by hand.

## Preparation and evaluation

Set up the Windows Python 3.10 environment through `dev.ps1` as described in the
[development guide](../../docs/DEVELOPMENT.md#first-setup). Run the commands below
from the repository root.

Before running the model commands below in Windows PowerShell, use UTF-8 for
Python's output so printed Bosnian text works with older console encodings:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

Reproduce the frozen Bosnian suggestion measurements from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset development --output language\bs\evaluation\reports\development.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset heldout --output language\bs\evaluation\reports\heldout.json
```

The development set is available for model decisions. Do not tune from the
held-out result. The scoring contract and frozen hashes are under
`tests\fixtures\speech_suggestions`.

The original held-out messages have now been inspected in repeated reviews;
keep their frozen text as a regression set, not a fresh blind quality estimate.
The frozen fixture protocol records the rules used for the first comparison;
its instruction to withhold those messages no longer describes their current
status.
An independently authored and reviewed set, withheld until model selection is
complete, is still needed for that claim. Reports separate sentence starters,
exact next-word hits before the first letter, and completion queries along the
simulated typing path. Their percentages are not interchangeable.

When changing the prepared language data, compare the supported vocabulary
sizes in one corpus pass before rebuilding the bundled model:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\benchmark_speech_models.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz --output-dir .dev-tools\speech-model-benchmark --report language\bs\benchmarks\model.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_speech_model.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz
.\.venv\Scripts\python.exe scripts\speech_suggestions\compare_speech_ranking.py --output language\bs\benchmarks\ranking.json
```

The ranking comparison holds language data fixed and compares the original fixed
weights with adaptive discounts of 2, 10, and 40 on development messages only.
It rejects latency or quality regressions, checks that sparse contexts back off
while supported contexts remain useful, and records its selection rule and
recommendation. If changing the chosen discount, update
`WordModel.context_discount` and rerun the vocabulary comparison before
evaluating the regression set.

The verified CLASSLA archive is a local development input and is not downloaded
by setup or included in a release. Its source URL and integrity hashes are in the
bundled model metadata. Candidate selection uses only the development set; run
the held-out evaluation once after the model choice is fixed.
The [model metadata](../../pogled_assist/assets/bosnian-model.meta.json) records the
archive, inputs, preparation script, and tokenizer used for that build. Compare
those recorded checksums with the files being reviewed; the presence of a bundled
model does not establish that it was built from the current source. Keep the
archive outside the repository's tracked files for future rebuilds.

`language\bs\model\core\conversation.tsv`, `starters.tsv`, and `spelling.tsv`
are build inputs that the installed application does not load. Rebuild the
bundled model after changing them or the preparation script. Spelling
replacements apply only to web training data; personal spelling and typed text
are preserved. The vocabulary budget
reserves space for reviewed words, and reviewed word combinations survive the
web-only pruning limits. Run the commands above to refresh the generated model,
metadata, and comparison reports before review. An old report does not validate
a model with a different checksum.

Preparation and tokenizer checksums cover the complete source files. A refactor
or formatting change therefore requires rebuilding the affected model even when
prediction behavior is intended to stay the same. Run `.\dev.ps1 format` before
preparation so formatting cannot immediately invalidate the new metadata. Never
replace a recorded checksum by hand to make a test pass.

The reviewed Islamic terminology is a separate offline layer, so it can be
rebuilt without downloading the 2.63 GB CLASSLA archive:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_islamic_model.py
```

`language\bs\model\domains\islamic.tsv` contains project-authored examples informed by the
terminology of the Islamic Community in Bosnia and Herzegovina. The generated
`bosnian-islamic-model.json.gz` and metadata are packaged beside the general
model and merged in memory at startup. Rebuild the layer after changing its TSV,
tokenisation, or preparation script, then run both frozen evaluations and the
focused suggestion tests. Do not copy articles, sermons, private correspondence,
or a user's messages into the repository.

The evaluation report includes each exact-word miss before typing, classified
as missing vocabulary, missing context, or a word ranked below the five visible
candidates. Completion remains a separate metric. Compare these causes as well
as activation counts when choosing the next data change.

Measure personal learning and large synthetic profiles separately:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_learning.py --stress-sizes 0 10000 50000 150000 --output language\bs\evaluation\reports\learning.json
```

This uses synthetic scenarios from `language/bs/evaluation/learning.tsv`, with separate
profiles and checkpoints after zero, one, three, and ten message uses. It also
records unrelated control predictions and exits unsuccessfully if a target is
not visible after one use, not first after three uses, or displaces an unrelated
expected top-five result. The optional stress measurements report index
construction, the first query, and reused-index queries separately. They exclude
Qt dispatch, display, file I/O, and Tobii processing, so they cannot establish
the Windows end-to-end latency target.

For fresh quality validation, have a separate author prepare and freeze a TSV
with `id`, `category`, and `text` columns and its SHA-256 before the candidate is
selected. Use synthetic text with the same punctuation supported by the frozen
keyboard protocol. Keep those messages out of preparation and tuning. After
selecting the candidate, evaluate that exact file:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --cases C:\Temp\speech-evaluation.tsv --expected-sha256 "<previously-frozen-sha256>" --output .dev-tools\speech-external-evaluation.json
```

The script verifies the supplied checksum and reports miss diagnostics. It does
not certify independent authorship or freeze a set retroactively. Do not add
private conversations to the repository. Existing regression fixtures remain
unchanged.
