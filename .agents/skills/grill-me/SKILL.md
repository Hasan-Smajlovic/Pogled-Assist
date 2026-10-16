---
name: grill-me
description: Clarify a Pogled Assist plan or design through a focused interview. Use when explicitly requested or when the goal, scope, approach, or several connected decisions remain unclear after reading available context; handle a single uncertainty with focused questions.
---

# Grill me

Turn an unclear request or design into an agreed outcome and actionable plan. Probe decisions that affect correctness, user experience, compatibility, or verification. Match the depth to the uncertainty; a clear task does not need an interview.

[AGENTS.md](../../../AGENTS.md) owns project constraints and routes to the relevant guides. Use the [compatibility contract](../../../docs/ARCHITECTURE.md#compatibility-contract) when evaluating proposed behavior changes. This skill is self-contained and does not require another command or skill to conduct the interview.

## Establish what remains undecided

- Start with the user's request, prior answers, any linked issue, and the relevant project guides. Establish what is already known about the intended outcome, scope, constraints, and acceptance criteria.
- Investigate technical facts in the code and existing tests yourself. Ask the user about intent, priorities, and tradeoffs that those sources cannot decide; do not ask them to locate facts available in the repository.
- Separate established requirements from unresolved decisions and assumptions. Prioritize questions whose answers would change the plan. Do not invent uncertainty or reopen decisions already answered without new evidence.

## Interview for decisions

- Start with the most consequential unresolved decision, then follow its dependencies. Ask small groups of related questions rather than a long questionnaire or repeated single questions about the same topic. Use the available question tool when suitable; otherwise ask in the conversation.
- Make each question self-contained: explain what is unclear, why it matters, and the viable options with their tradeoffs. Give a reasoned recommendation when the evidence supports one, while allowing the user to propose another approach. Use the user's language and explain technical details plainly.
- After each answer, check its consequences for scope, existing behavior, and how success would be demonstrated. Ask focused follow-ups for contradictions or remaining decisions that materially affect the work. Use only the relevant owning guides, including the UI development workflow for visible changes.
- Challenge an unsafe, unsupported, or unnecessarily complex proposal with a concrete consequence and a simpler alternative where possible. Be candid about uncertainty; keep the discussion collaborative rather than trying to win agreement or interrogating the user about facts you can inspect.
- Wait for answers before work that depends on them. Continue independent investigation while waiting. Silence is not an answer or approval, and an unanswered material decision must remain visible.

## Finish and resume the task

Stop when the outcome, scope, constraints, acceptance criteria, and material decisions are clear enough to act. Summarize the agreed plan, key tradeoffs, and remaining verification or external dependencies. Distinguish decisions the user made from recommendations and unresolved questions.

Resume work already authorized by the user without another confirmation. If the request is only to explore or plan, deliver the agreed plan. Keep any lasting documentation in its owning guide under the rules in AGENTS.md; do not create a transcript or separate planning file by default.
