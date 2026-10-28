---
name: blast-radius
description: Assess what a Pogled Assist change could break outside the diff. Use for impact reviews, questions about what could break, and refactors or contract and lifecycle changes that affect other components.
---

# Blast radius

Trace what a change can break outside its diff. Scale the analysis to the affected behavior; isolated edits do not need a separate impact report. [AGENTS.md](../../../AGENTS.md) owns compatibility, maintenance and verification.

## Trace the boundary

Identify the baseline, final files and intended user outcome. Start with the [compatibility contract](../../../docs/ARCHITECTURE.md#compatibility-contract), then follow actual consumers across relevant boundaries: Qt signals/threads/timers/shutdown, persisted formats and older readers, coordinate spaces, bridge messages, generated models and packaged assets. An empty symbol search does not prove there are no consumers. When behavior depends on a library, inspect the pinned version and local wrappers.

For each material risk, trace a concrete trigger to an observable failure with source locations. Check error/recovery paths and each independent compatibility condition. Separate confirmed failures, plausible risks lacking evidence and checked cases; do not invent probabilities or universal checklists.

## Establish evidence

Use the [boundary fakes](../../../docs/TESTING.md#test-boundary-map) and inspect what existing tests reach. A synchronous fake cannot establish queued-thread ordering or native behavior. When authorized, add the smallest faithful pytest reproduction for missing coverage. Before interactive work, account for real input and persistent data: the [mouse simulator](../../../docs/UI_DEVELOPMENT.md#mouse-gaze-simulation) can issue Windows clicks.

Follow [verification rules](../../../docs/DEVELOPMENT.md#verification-before-a-pull-request). If execution is deferred, finish analysis and authorized edits, mark checks Not run and supply executable tests or precise reproduction steps. Leave only unreached boundaries to [manual Windows/Tobii checks](../../../docs/UI_DEVELOPMENT.md#manual-windows-checks). Load applicable shipping/security workflows when the change crosses their boundaries.

## Report

Name affected behavior/consumers and material findings: trigger, consequence, source and evidence or uncertainty. Summarize cleared cases with their limits and the next check for unresolved risks. Distinguish source tracing, executed tests and hardware observations. Focused proof does not establish review or merge readiness.
