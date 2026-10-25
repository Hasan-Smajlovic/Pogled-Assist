# Bosnian language data

This directory keeps editable model inputs separate from evaluation data and generated reports. The installed application does not load these files. It uses the prepared models under `pogled_assist/assets`.

## Model inputs

- `model/core/conversation.tsv` contains reviewed everyday phrases used to supplement the general Bosnian corpus.
- `model/core/spelling.tsv` maps ASCII web-corpus variants to reviewed Bosnian spellings during model preparation.
- `model/core/starters.tsv` assigns additional weight to useful sentence starters.
- `model/domains/islamic.tsv` contains project-authored Islamic terminology and conversation phrases for the separate Islamic model layer.

Maintain these TSV files by hand and rebuild the affected model after editing them. Prepared-model metadata records source, input, script, tokenizer and model checksums. The [commands below](#preparation-and-evaluation) define rebuild order and evaluation.

## Evaluation

`evaluation/learning.tsv` contains synthetic personal-learning scenarios. The JSON files under `evaluation/reports` are generated regression reports and must match the current prepared models and frozen test fixtures.

## Benchmarks

The JSON files under `benchmarks` are generated model-selection and ranking reports. Regenerate them with the [preparation and evaluation commands](#preparation-and-evaluation); do not edit their measured results by hand.

## Preparation and evaluation

Set up the Windows Python 3.10 environment through `dev.ps1` as described in the [development guide](../../docs/DEVELOPMENT.md#first-setup). Run the commands below from the repository root.

Before running the model commands below in Windows PowerShell, use UTF-8 for Python's output so printed Bosnian text works with older console encodings:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

Reproduce the frozen Bosnian suggestion measurements from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset development --output language\bs\evaluation\reports\development.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --dataset heldout --output language\bs\evaluation\reports\heldout.json
```

Use the development set for model decisions; do not tune from held-out results. The original held-out messages have been inspected in repeated reviews and now provide regression evidence, not a fresh blind estimate. `tests/fixtures/speech_suggestions/protocol.md` and its checksum are frozen records of the first comparison; do not rewrite that protocol to describe a later review. Fresh validation requires an independently authored set withheld until model selection is complete. Reports distinguish starters, next-word hits before typing and completions along the typing path; their percentages are not interchangeable.

When changing the prepared language data, compare the supported vocabulary sizes in one corpus pass before rebuilding the bundled model:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\benchmark_speech_models.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz --output-dir .dev-tools\speech-model-benchmark --report language\bs\benchmarks\model.json
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_speech_model.py .dev-tools\corpora\CLASSLA-web.bs.2.0.jsonl.gz
.\.venv\Scripts\python.exe scripts\speech_suggestions\compare_speech_ranking.py --output language\bs\benchmarks\ranking.json
```

The ranking comparison holds language data fixed and compares the original fixed weights with adaptive discounts of 2, 10, and 40 on development messages only. It rejects latency or quality regressions, checks that sparse contexts back off while supported contexts remain useful, and records its selection rule and recommendation. If changing the chosen discount, update `WordModel.context_discount` and rerun the vocabulary comparison before evaluating the regression set.

The CLASSLA archive is a local input, neither downloaded by setup nor bundled in releases. Keep it outside tracked files. Its URL and integrity hashes are in [model metadata](../../pogled_assist/assets/bosnian-model.meta.json). Choose candidates using development data, then run the held-out regression after fixing the choice.

Spelling replacements affect web training data only; personal spelling and typed text stay intact. Reviewed words receive reserved vocabulary space and their combinations survive web-only pruning. Generated reports must match the reviewed model and source checksums.

Run `.\dev.ps1 format` before preparation. Checksums cover complete preparation/tokenizer files, so even a formatting-only source change requires rebuilding the affected model and reports. Compare metadata to final source before review; never replace hashes by hand to make tests pass.

The reviewed Islamic terminology is a separate offline layer, so it can be rebuilt without downloading the 2.63 GB CLASSLA archive:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\prepare_islamic_model.py
```

`language\bs\model\domains\islamic.tsv` contains project-authored examples informed by the terminology of the Islamic Community in Bosnia and Herzegovina. The generated `bosnian-islamic-model.json.gz` and metadata are packaged beside the general model and merged in memory at startup. Rebuild the layer after changing its TSV, tokenisation, or preparation script, then run both frozen evaluations and the focused suggestion tests. Do not copy articles, sermons, private correspondence, or a user's messages into the repository.

The evaluation report includes each exact-word miss before typing, classified as missing vocabulary, missing context, or a word ranked below the five visible candidates. Completion remains a separate metric. Compare these causes as well as activation counts when choosing the next data change.

Measure personal learning and large synthetic profiles separately:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_learning.py --stress-sizes 0 10000 50000 150000 --output language\bs\evaluation\reports\learning.json
```

This uses synthetic scenarios from `language/bs/evaluation/learning.tsv`, with separate profiles and checkpoints after zero, one, three, and ten message uses. It also records unrelated control predictions and exits unsuccessfully if a target is not visible after one use, not first after three uses, or displaces an unrelated expected top-five result. The optional stress measurements report index construction, the first query, and reused-index queries separately. They exclude Qt dispatch, display, file I/O, and Tobii processing, so they cannot establish the Windows end-to-end latency target.

For fresh quality validation, have a separate author prepare and freeze a TSV with `id`, `category`, and `text` columns and its SHA-256 before the candidate is selected. Use synthetic text with the same punctuation supported by the frozen keyboard protocol. Keep those messages out of preparation and tuning. After selecting the candidate, evaluate that exact file:

```powershell
.\.venv\Scripts\python.exe scripts\speech_suggestions\evaluate_speech_model.py --cases C:\Temp\speech-evaluation.tsv --expected-sha256 "<previously-frozen-sha256>" --output .dev-tools\speech-external-evaluation.json
```

The script verifies the supplied checksum and reports miss diagnostics. It does not certify independent authorship or freeze a set retroactively. Do not add private conversations to the repository. Existing regression fixtures remain unchanged.
