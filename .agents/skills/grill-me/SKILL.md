---
name: grill-me
description: Clarify a Pogled Assist plan or design through a focused interview. Use when explicitly requested or when the goal, scope, approach, or several connected decisions remain unclear after reading available context; handle a single uncertainty with focused questions.
---

# Grill me

Resolve product or design decisions that prevent an actionable plan. A clear task needs no interview. [AGENTS.md](../../../AGENTS.md) and the [compatibility contract](../../../docs/ARCHITECTURE.md#compatibility-contract) supply project constraints.

## Find the uncertainty

Read the request, previous answers, linked issue and relevant code/guides first. Investigate technical facts yourself. Separate established requirements from assumptions and decisions only the user can make; do not reopen settled choices without new evidence.

## Ask for decisions

Start with the decision that most affects correctness, scope, user experience or verification. Ask a small group of related, self-contained questions in the user's language. Explain the tradeoff and recommend an option when supported; leave room for another approach. Use a focused question for one uncertainty.

After each answer, check consequences and contradictions. Challenge unsafe or unnecessarily complex choices with a concrete consequence and a simpler alternative. Wait before dependent work; continue independent investigation. Silence is not an answer or approval.

## Resume

Stop when outcome, scope, constraints and acceptance criteria are clear enough to act. Summarize material decisions, tradeoffs and remaining dependencies, distinguishing user decisions from recommendations. Resume already-authorized work without another confirmation. For a planning-only request, deliver the plan. Record lasting decisions in their owning guide, not a transcript or new planning file by default.
