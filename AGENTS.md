# Agent instructions — Mongo Debugger

## Documentation habit (required)

When you change behavior, APIs, architecture, or ops:

1. Read [docs/DOC_MAINTENANCE.md](docs/DOC_MAINTENANCE.md).
2. Update [docs/CHANGELOG.md](docs/CHANGELOG.md) (What / How / Why, dated, newest first).
3. Update every other doc listed in the change matrix for that work.
4. Keep all substantive docs under `docs/` only.

Rule: `.cursor/rules/doc-maintenance.mdc` (always applied).

## Project entrypoints

| Need | Doc |
|------|-----|
| Index + quick start | [docs/README.md](docs/README.md) |
| What we improved | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| Spec / milestones | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) |
| Run the app | [docs/OPERATIONS.md](docs/OPERATIONS.md) |

## Code layout

- `backend/app/` — FastAPI, web UI, Simagix RCA, Phase 2 LLM
- `simagix-workspace/` — Docker pipeline, exports, uploads (data + scripts)
- `docs/` — all documentation
