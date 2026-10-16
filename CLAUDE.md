@AGENTS.md

## Claude Code notes

`AGENTS.md` above is the single source of guidance for every coding agent. Keep
rules there, not here.

The project skills live in `.agents/skills/`. Each one has a pointer under
`.claude/skills/` so Claude Code can discover it; change the skill in
`.agents/skills/` and keep the pointer's `name` and `description` identical.
