# Agent instructions — Mongo Debugger

## Agent skills

Matt Pocock skills live in [`.agents/skills/`](.agents/skills/). Invoke in chat (e.g. `/grill-me`, `/tdd`, `/to-issues`).

**Google Stitch skills** (need Stitch MCP + `.env` `STITCH_API_KEY`): `design-md`, `stitch-react-components`, `stitch-generate-design`, `enhance-prompt`, `stitch-loop`, and others under `.agents/skills/stitch-*`. Install/update: `npx skills add google-labs-code/stitch-skills --yes`.

### Issue tracker

Local markdown under `.scratch/<feature-slug>/`. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Default five roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context: `CONTEXT.md` at repo root; tradeoffs in `docs/DESIGN_NOTES.md` §14. See [`docs/agents/domain.md`](docs/agents/domain.md).

## Documentation habit (required)

When you change behavior, APIs, architecture, or ops:

1. Read [docs/DOC_MAINTENANCE.md](docs/DOC_MAINTENANCE.md).
2. Update [docs/CHANGELOG.md](docs/CHANGELOG.md) (What / How / Why, dated, newest first).
3. Update every other doc listed in the change matrix for that work.
4. **If you chose one approach over a plausible alternative**, add or update a row in [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) **§14** (same session — see DOC_MAINTENANCE “§14 tradeoff habit”).
5. **If you explained a low-level concept** (locks, extra disk read, id semantics, etc.), add **Talking points** under the relevant §14 section (see DOC_MAINTENANCE “Low-level concept notes”).
6. **If you chose one approach over another while implementing** (even mid-task, before the user asks), document the tradeoff in **§14** same session (see DOC_MAINTENANCE “In-flight tradeoffs”).
7. Keep all substantive docs under `docs/` only.

Rule: `.cursor/rules/doc-maintenance.mdc` (always applied).

## Feature workflow (required)

Per feature branch — **do not skip steps**; **do not commit until the user asks** after code review.

| Step | What | Agent / you |
|------|------|-------------|
| 1. **Grill / discuss** | Tradeoffs, PVC, locks, scope — align before code | Q&A; optional `/grill-me`; no implementation yet |
| 2. **Test (TDD)** | Red → green; `pytest` for the slice | `/tdd` or explicit tests first |
| 3. **Code** | Minimal diff for the agreed design | Implement until tests pass |
| 4. **Docs** | §14 rows, talking points, in-flight decisions, CHANGELOG, matrix docs | Same session as code — see Documentation habit |
| 5. **Read code** | You review diff in Cursor; ask questions | Agent stops here; no commit |
| 6. **Commit** | Only when you say so | Focused message; no runtime artifacts |
| 7. **Pull / PR** | Push branch; open PR; CI | When you ask |
| 8. **Merge** | Merge to `main`; sync local | When CI green + you approve |

**Branch naming:** `feat/<slug>` (e.g. `feat/pipeline-worker`).

## Project entrypoints

| Need | Doc |
|------|-----|
| Index + quick start | [docs/README.md](docs/README.md) |
| What we improved | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| Spec / milestones | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) |
| Why / tradeoffs (mentor Q&A) | [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) §14 |
| Run the app | [docs/OPERATIONS.md](docs/OPERATIONS.md) |

## Code layout

- `frontend/` — Bootstrap Jinja templates + static JS/CSS (UI only)
- `backend/app/` — FastAPI, Simagix RCA, Phase 2 LLM
- `simagix-workspace/` — Docker pipeline, exports, uploads (data + scripts)
- `docs/` — all documentation
