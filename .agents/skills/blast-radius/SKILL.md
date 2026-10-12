---
name: blast-radius
description: Assess what a Pogled Assist change could break outside the diff. Use for impact reviews, questions about what could break, and refactors or contract and lifecycle changes that affect other components.
---

# Blast radius

Trace indirect consequences of a proposed change and establish the evidence for
the assumptions that make it safe. Scale the review to the affected behavior;
routine isolated edits do not need a separate impact report.

[AGENTS.md](../../../AGENTS.md) owns compatibility rules, the maintenance matrix,
verification, and human review requirements. Use the applicable
[shipping-a-change](../shipping-a-change/SKILL.md) and
[security-review](../security-review/SKILL.md) sections for their workflows.
This skill adds impact analysis; it does not replace those requirements or
expand the user's authorized scope.

## Establish the change and its consumers

- Identify the baseline and the exact change being reviewed, including related
  new files. State what changes for the user and what must remain compatible.
  Start from the [architecture contract](../../../docs/ARCHITECTURE.md#compatibility-contract)
  and read only the component sections relevant to the change.
- Follow data and control flow beyond direct callers. Check the boundaries the
  change crosses: queued Qt signals, thread affinity, timers and shutdown;
  persisted formats and older readers; logical and physical coordinates;
  bridge messages; generated models and frozen-package assets. Use the actual
  implementation and owning guides rather than treating this as a universal
  checklist.
- When safety depends on library behavior, inspect the pinned version and any
  local wrapper or patch. Do not transfer assumptions from another version or
  infer that there are no consumers from an empty symbol search.

## Identify the assumptions and failure paths

- State each independent condition required for compatibility. One proven
  condition does not clear other risks. For each material risk, trace a concrete
  trigger through the affected components to an observable failure or side
  effect, with source locations.
- Check lifecycle and error paths as well as normal operation when they cross
  the changed boundary. For example, a gaze-delivery change may work in a
  sequential test yet allow an invalid-eye transition to disappear in the Qt
  queue or let pending callbacks act after shutdown.
- Separate confirmed failures, plausible risks with missing evidence, and
  cases checked and cleared. Explain likelihood using reachable conditions and
  impact using the user consequence; do not invent numerical probabilities.
  A cleared case must name the conditions and evidence that cleared it.

## Exercise the important conditions

- Use the [test strategy and existing boundary fakes](../../../docs/DEVELOPMENT.md#test-strategy)
  to find a check that exercises the production components and the relevant
  ordering, persistence, or side effect. Check what a test actually reaches;
  its name or a passing unrelated test is not proof. A synchronous fake cannot
  establish behavior that depends on worker-thread dispatch or a native device.
- Reuse or extend the matching pytest tests when authorized and coverage is
  missing. Choose the smallest faithful reproduction, with an assertion that
  exposes the failure. Do not create a new script for every review or substitute
  a standalone function call for the lifecycle being investigated.
- Follow the [verification guide](../../../docs/DEVELOPMENT.md#verification-before-a-pull-request)
  for execution and deferred checks. When the user defers execution or the
  required environment is unavailable, finish the source analysis and authorized
  edits, mark execution Not run, and leave executable checks or precise
  reproduction steps. Do not present an unexecuted test as proof.
- Leave only the boundaries those checks cannot reach to the applicable
  [manual Windows and Tobii checks](../../../docs/UI_DEVELOPMENT.md#manual-windows-checks).
  Distinguish software evidence from hardware validation. Before an interactive
  reproduction, account for real input and persistent data; the
  [mouse simulator](../../../docs/UI_DEVELOPMENT.md#mouse-gaze-simulation)
  can perform real Windows clicks and is not an isolated runtime.

## Report the result

Keep the report proportional to the change. Name the changed behavior and
affected consumers, then give the material findings with their trigger, user
consequence, source references, and evidence or remaining uncertainty. Summarize
cleared cases with their limits. List checks actually run and their results,
checks left Not run and why, and the next check needed for each unresolved risk.
Source tracing, executed tests, and target-machine observations support different
claims; name which evidence supports each conclusion. Focused proof does not
establish readiness for review or merge.
