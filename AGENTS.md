# Agent instructions — Mongo Debugger

## Documentation habit (required)

When you change behavior, APIs, architecture, or ops:

1. Read [docs/DOC_MAINTENANCE.md](docs/DOC_MAINTENANCE.md).
2. Update [docs/CHANGELOG.md](docs/CHANGELOG.md) (What / How / Why, dated, newest first).
3. Update every other doc listed in the change matrix for that work.
4. **If you chose one approach over a plausible alternative**, add or update a row in [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) **§14** (same session — see DOC_MAINTENANCE “§14 tradeoff habit”).
5. Keep all substantive docs under `docs/` only.

Rule: `.cursor/rules/doc-maintenance.mdc` (always applied).

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
