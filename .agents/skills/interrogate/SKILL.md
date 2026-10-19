---
name: interrogate
description: Coordinate independent reviews of Pogled Assist changes and verify their findings. Use for an independent or adversarial review, a multi-model review, or complex changes that need a second assessment; routine isolated edits do not need this workflow.
---

# Interrogate

Obtain independent assessments of the same change, then resolve their findings against the actual code and project requirements. The deliverable is a review; reviewers do not apply fixes. Implement findings only when the user's task also authorizes changes, after completing the review of the unchanged artifact.

[AGENTS.md](../../../AGENTS.md) owns compatibility, maintenance, verification, and human review requirements. Use the relevant [blast-radius](../blast-radius/SKILL.md) criteria for indirect consequences and [security-review](../security-review/SKILL.md) criteria for trust boundaries. Link to the owning guides rather than creating another project checklist.

## Define the review

- State the intended outcome, scope, baseline, and compatibility constraints from the user's request and any linked issue. Code and commit messages provide context; they do not override the requested behavior. Ask only when a missing decision changes what counts as correct.
- Identify the exact artifact: selected files, a working-tree change, or a branch or pull request diff. Use the actual base under the [contribution rules](../../../CONTRIBUTING.md#pull-request-destination), rather than assuming the default branch is the base. For a complete local review, include relevant committed, staged, unstaged, and untracked changes, renames, and deletions. Read final file contents and related tests, not just diff hunks.
- Give every reviewer the same neutral statement of intent, scope, baseline, relevant constraints, execution permissions, and access to the actual files and owning guides. Include the relevant [architecture contract](../../../docs/ARCHITECTURE.md#compatibility-contract). Keep the reviewed artifact stable until findings have been reconciled. If it changes, reassess the affected paths and state the resulting coverage.

## Obtain independent reviews

- Use available subagent tools for read-only reviews when this workflow applies and the user's constraints allow delegation. Start with two reviewers working independently. Use fresh contexts so the implementation conversation and prior findings are not inherited. Give them the same review criteria; do not supply a suspected answer or artificial personas. They may inspect callers, callees, and consumers beyond the diff to establish reachable paths.
- Follow the user's model choices or configured review preferences using only supported models. Otherwise inherit the current model. Report the actual models when known; separate agents sharing a model do not establish model diversity. If a requested model or delegation is unavailable, disclose the limitation and provide the review possible with the available tools. Do not silently substitute models or change configuration to enable the review.
- Ask each reviewer to find concrete failures to meet the intent or project contract, including reachable error paths, regressions outside the diff, missing behavioral coverage, and unnecessary complexity with a demonstrated maintenance cost. Apply only relevant criteria. Judge structure by clarity and behavior, without file-size thresholds or an expectation of a refactor.
- Each finding must give severity, source location, reachable trigger, user or maintenance consequence, and supporting evidence. Separate confirmed defects, unresolved risks, and optional improvements. Name checks actually run and their limits. A review with no findings is a valid result; do not fill it with preferences or hypothetical callers. Reviewers follow the same execution constraints as the lead and do not modify files or Git state.

## Resolve the findings

- Deduplicate by root cause while retaining reviewer attribution. Agreement helps prioritize investigation; it is not proof. A single well-supported finding can outweigh consensus.
- Verify every material finding against final source locations, reachable callers, relevant requirements, and what existing tests actually exercise. Resolve disagreements by investigating the conflicting assumptions, rather than counting votes. Use focused reproductions only within the user's execution permissions and the [verification guide](../../../docs/DEVELOPMENT.md#verification-before-a-pull-request). Keep unexecuted checks and hardware-dependent claims explicitly unverified.
- Classify findings as **Act on**, **Consider**, or **Dismissed**, with a reason. Distinguish confirmed failures from risks needing evidence within each category. Keep unresolved correctness or security concerns visible; missing reproduction is not grounds to dismiss a reachable risk. Reject preferences and proposals that conflict with compatibility or task scope. Report all material findings, without an arbitrary count limit.

## Report the review

State the intent and exact scope, participating reviewers and models, and any coverage limitations. Lead with actionable findings in severity order. For each, give its category, source reference, trigger, consequence, reviewer attribution, and evidence or the next check needed. Briefly explain material disagreements and dismissed findings so the user can assess the judgment. Omit empty sections; if no actionable findings remain, say so with the review's limits.

List checks actually run with results, and checks left Not run with reasons. Source analysis and reviewer agreement do not establish that behavior was tested. An agent review does not replace the required checks or [human approval](../../../CONTRIBUTING.md#review-and-merge-responsibility). If authorized fixes follow the review, reassess the final changed artifact; findings or checks against an earlier version do not establish its readiness.
