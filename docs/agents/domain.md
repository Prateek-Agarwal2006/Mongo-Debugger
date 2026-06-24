# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — shared vocabulary (glossary). If missing, proceed silently; `/domain-modeling` extends it when terms are resolved.
- **`docs/DESIGN_NOTES.md`** — architecture narrative and **§14 tradeoff table** (ADR-equivalent for this repo).
- **`docs/ARCHITECTURE.md`** — system design and data flow.

This repo uses **`docs/DESIGN_NOTES.md` §14** instead of a separate `docs/adr/` tree. When a skill would write an ADR, add or extend a row in §14 (same session as the decision).

## File structure (single-context)

```
/
├── CONTEXT.md
├── AGENTS.md
├── docs/
│   ├── DESIGN_NOTES.md      ← tradeoffs / ADR-equivalent (§14)
│   ├── ARCHITECTURE.md
│   └── agents/              ← issue tracker + triage + this file
└── backend/app/
```

## Use the glossary's vocabulary

When output names a domain concept (issue title, refactor, test name), use terms from `CONTEXT.md`. Avoid synonyms the glossary flags.

## Flag tradeoff conflicts

If output contradicts `DESIGN_NOTES.md` §14, surface it explicitly:

> _Contradicts §14 row on worker vs thread — but worth reopening because…_
