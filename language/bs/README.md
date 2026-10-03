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
follow the [development guide](../../docs/DEVELOPMENT.md#command-reference) for
the rebuild order and commands.

## Evaluation

`evaluation/learning.tsv` contains synthetic personal-learning scenarios. The
JSON files under `evaluation/reports` are generated regression reports and must
match the current prepared models and frozen test fixtures.

## Benchmarks

The JSON files under `benchmarks` are generated model-selection and ranking
reports. Regenerate them with the commands in the
[development guide](../../docs/DEVELOPMENT.md#command-reference); do not edit
their measured results by hand.
