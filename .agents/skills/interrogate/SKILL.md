---
name: interrogate
description: Coordinate independent reviews of Pogled Assist changes and verify their findings. Use for an independent or adversarial review, a multi-model review, or complex changes that need a second assessment; routine isolated edits do not need this workflow.
---

# Interrogate

Obtain independent reviews, then verify findings against the artifact and project requirements. Reviewers are read-only. Apply fixes only when the user's task authorizes them, after reconciling the unchanged artifact. [AGENTS.md](../../../AGENTS.md) owns compatibility, verification and human review.

## Scope the review

State the intended outcome, baseline, selected files/diff and compatibility constraints from the request and issue. Use the actual base under [contribution rules](../../../CONTRIBUTING.md#pull-request-destination). A complete local review includes committed, staged, unstaged and untracked changes, renames and deletions. Read final contents and related tests, not only hunks. Ask only about missing decisions that change correctness.

## Independent passes

Use available subagents when allowed. Start two reviewers with fresh contexts and the same neutral intent, scope, baseline, execution permissions and [compatibility contract](../../../docs/ARCHITECTURE.md#compatibility-contract). Do not seed an answer or artificial persona. Keep the artifact stable until findings are reconciled; reassess affected paths if it changes.

Honor supported user model choices or configured preferences; otherwise inherit the current model. Report actual models when known. Separate agents using one model are not model diversity. Disclose unavailable models/delegation or incomplete passes without changing configuration or silently substituting.

Ask for concrete violations: reachable failures, indirect regressions, missing behavioral coverage or complexity with a demonstrated maintenance cost. Reviewers may trace callers/consumers but must not edit files or Git. Each finding needs severity, source, trigger, consequence and evidence. Separate confirmed defects, unresolved risks and optional improvements. No findings is valid. Use relevant [impact](../blast-radius/SKILL.md) and [security](../security-review/SKILL.md) criteria, not a universal checklist.

## Reconcile and report

Deduplicate by root cause while retaining attribution. Verify each material finding against sources, consumers and test reach. Resolve disagreements through evidence, not votes. Use focused reproductions only within execution permissions and [verification rules](../../../docs/DEVELOPMENT.md#verification-before-a-pull-request).

Classify findings **Act on**, **Consider** or **Dismissed**, with reasons. Preserve unresolved correctness/security risks; missing reproduction alone does not dismiss a reachable path. Report material findings without an arbitrary count limit, their attribution and evidence/next check, material disagreements, scope, participants and coverage limits. Omit empty sections.

Name checks actually run and those Not run. Reassess authorized fixes against the final artifact; earlier reviews/tests do not prove the new version. Agent agreement never replaces required checks or [human review](../../../CONTRIBUTING.md#review-and-merge-responsibility).
