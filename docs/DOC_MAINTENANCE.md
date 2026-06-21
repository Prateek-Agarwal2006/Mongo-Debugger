# Documentation maintenance guide

How agents and humans keep project docs accurate. **This is the source of truth for which file to update when.**

**Last updated:** 2026-06-18

---

## Golden rule

**Same session as the code change:** update `CHANGELOG.md` plus every doc row that applies from the matrix below. Do not defer doc updates to a follow-up unless the user stops the task mid-flight.

Cursor enforces this via `.cursor/rules/doc-maintenance.mdc` (`alwaysApply: true`).

---

## Doc roles (no overlap)

| Document | Owns | Does not own |
|----------|------|----------------|
| [CHANGELOG.md](CHANGELOG.md) | What improved, how, why (dated narrative) | Spec scorecard |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | PDF spec alignment, milestones, future work | Step-by-step ops |
| [DESIGN_NOTES.md](DESIGN_NOTES.md) | Why architecture impresses / demo talking points; **§14 tradeoff table** (mentor “why not X?”) | API field lists |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, data flow, role split | Command cheatsheet |
| [OPERATIONS.md](OPERATIONS.md) | Setup, Colima, pipeline, upload, Grafana, env troubleshooting | REST request bodies |
| [RCA_BACKEND.md](RCA_BACKEND.md) | REST + web routes, backend module layout | MCP tool semantics |
| [PHASE2_LLM.md](PHASE2_LLM.md) | Agent, MCP, 3-phase RCA, budgets, prompts policy | Export tier schema |
| [export_contract.md](export_contract.md) | Bundle schema `v1.0.0` | Why tiers exist (→ EVIDENCE_GUIDE) |
| [EVIDENCE_GUIDE.md](EVIDENCE_GUIDE.md) | Tier optimization rationale | OpenAPI |
| [FALLBACK_INDEX.md](FALLBACK_INDEX.md) | `fallback_retrieval_index.json` fields | Pipeline scripts |
| [SIMAGIX_WORKSPACE.md](SIMAGIX_WORKSPACE.md) | Folder layout, inputs, cloned repos | Duplicate command blocks |
| [SIMAGIX_TOOLCHAIN.md](SIMAGIX_TOOLCHAIN.md) | Tool matrix, Docker scripts, blocked tools | RCA API |
| [FTDC_REFERENCE.md](FTDC_REFERENCE.md) | Long-form FTDC/mongo-ftdc research | **Current** status (historical OK) |
| [SUPERLOG_ANALYSIS.md](SUPERLOG_ANALYSIS.md) | External product lessons | Implementation |
| [README.md](README.md) | Doc index + quick start | Deep content (link out) |

Root [README.md](../README.md), [backend/README.md](../backend/README.md), and [simagix-workspace/README.md](../simagix-workspace/README.md) are **stubs only** — link to `docs/`.

---

## Change matrix — what to update

| If you changed… | Update these docs |
|-----------------|-------------------|
| **Any user-visible behavior, bug fix, or refactor** | `CHANGELOG.md` |
| **REST/web routes, request/response, persistence paths** | `CHANGELOG.md`, `RCA_BACKEND.md`, `OPERATIONS.md` (if operator-facing), `PROJECT_STATUS.md` (if spec item) |
| **Phase 2 agent, MCP tools, prompts, budgets, 3-phase flow** | `CHANGELOG.md`, `PHASE2_LLM.md`, `RCA_BACKEND.md`, `DESIGN_NOTES.md` (if design choice) |
| **Upload, pipeline scripts, Docker/Grafana/Colima** | `CHANGELOG.md`, `OPERATIONS.md`, `SIMAGIX_WORKSPACE.md`, `SIMAGIX_TOOLCHAIN.md`, `ARCHITECTURE.md` (if flow changes) |
| **Evidence bundle files, tiers, export flags** | `CHANGELOG.md`, `export_contract.md`, `EVIDENCE_GUIDE.md`, `FALLBACK_INDEX.md` (if index shape), `ARCHITECTURE.md` |
| **System architecture / role split** | `CHANGELOG.md`, `ARCHITECTURE.md`, `DESIGN_NOTES.md` (+ **§14 row** if a tradeoff was decided) |
| **Architecture choice with alternatives** (memory, orchestration, provider, UI pattern, etc.) | `DESIGN_NOTES.md` **§14** (required), `CHANGELOG.md` if behavior changed, `PROJECT_STATUS.md` if future-work scope shifted |
| **Milestone done or spec gap closed** | `CHANGELOG.md`, `PROJECT_STATUS.md` |
| **New future idea (not implemented)** | `PROJECT_STATUS.md` § Future enhancements only |
| **Demo / interview narrative** | `DESIGN_NOTES.md`, optionally `CHANGELOG.md` if behavior tied |
| **Low-level concept explained in chat** (locks, I/O, ids, polling) | `DESIGN_NOTES.md` **§14** talking points (see § Low-level concept notes) |
| **Tradeoff decided while implementing** (agent or human chose X over Y mid-task) | `DESIGN_NOTES.md` **§14** row and/or talking points (see § In-flight tradeoffs) |
| **Tests/demo script paths** | `CHANGELOG.md`, `OPERATIONS.md`, `PROJECT_STATUS.md` § How to demo |
| **New doc file or doc consolidation** | `CHANGELOG.md`, `README.md` (index), this file if matrix changes |
| **Research / external product analysis** | New or existing research doc + `CHANGELOG.md` + link from `README.md` |

When in doubt, add a short `CHANGELOG.md` entry and at least one technical doc.

---

## §14 tradeoff habit (mentor Q&A)

**When:** You or the user chose an approach over a plausible alternative (e.g. disk transcript vs Hindsight, fixed 3-phase vs LangGraph, `web_fetch` vs Google Search).

**Do:** In the **same session**, add or update one row in [DESIGN_NOTES.md](DESIGN_NOTES.md) **§14** with:

| Column | Content |
|--------|---------|
| Topic | Short label |
| What we chose | One line |
| Why | Product/engineering reason |
| Why not the alternative | What we rejected and why |
| Code / config | File or env pointer |

**Do not:** Create `DESIGN_DILEMMAS.md`, `MY_UNDERSTANDING.md`, or duplicate the table elsewhere. **§14** is the single source for “why this, not that.”

**Optional:** Add a sound bite under §14.1 if it will come up in demos.

---

## Low-level concept notes (required)

**When:** During implementation or Q&A you explain **how something works under the hood** — locks, disk I/O, id semantics, polling vs events, atomic renames, RAM vs PVC, “extra load,” etc.

**Do:** In the **same session**, add or extend a **Talking points** subsection under the relevant **DESIGN_NOTES.md §14** topic (e.g. §14.4 Pipeline worker). Include:

- Plain-language definition (what the mechanism is)
- Why we chose it vs the alternative
- Mentor/demo **sound bite** (one line)
- Code pointer (`jobs/queue.py`, `store.py`, …)

**Do not:** Leave good explanations only in chat — if it came up in review, it belongs in docs for the next demo.

**Examples to capture:** `job_id` vs `run_id`; claim = `Path.replace()`; worker poll interval; queue denormalization vs second disk read; crash recovery `processing/` → `pending/`.

---

## In-flight tradeoffs (required)

**When:** While **writing code** (including agent implementation), you **decide** between plausible options — e.g. standalone worker vs embedded thread, queue denormalization vs job-id-only, soft reset scope, where to persist first.

**Do:** In the **same session** (before finishing the task), record the decision in [DESIGN_NOTES.md](DESIGN_NOTES.md) **§14**:

| If the decision is… | Write… |
|---------------------|--------|
| Architectural / “why not X?” | New or updated **§14 table row** (Topic, What we chose, Why, Why not, Code pointer) |
| Implementation detail worth explaining in demos | **Talking points** or **Decision:** bullet under the relevant §14 subsection (e.g. §14.4) |
| Both | Row + talking points |

Include **what you rejected** and **why**, not only what you shipped. If the choice is provisional (“target refactor”), say so explicitly.

**Do not:** Rely on chat history or chain-of-thought as the only record — if you reasoned “I’ll use atomic rename because…”, that belongs in §14 for the mentor.

**Same as §14 tradeoff habit:** one table (§14), no separate dilemma docs. In-flight coding decisions use the same destination as mentor Q&A.

---

## CHANGELOG entry template

Add at the **top** (below the “How to read this” section), newest date first:

```markdown
## YYYY-MM-DD — Short title

**What:** …

**How:**
- …

**Why:** …
```

---

## Session checklist (agents)

Before marking work complete:

- [ ] `docs/CHANGELOG.md` — dated entry with What / How / Why
- [ ] Each row from the matrix above — touched and `Last updated:` bumped
- [ ] **`DESIGN_NOTES.md` §14** — new/updated row if an architecture tradeoff was decided or debated
- [ ] `docs/README.md` — new doc linked if added
- [ ] Internal markdown links still resolve
- [ ] `uv run pytest backend/tests -q` if backend changed
- [ ] No duplicate status tables introduced outside `PROJECT_STATUS.md`

---

## Humans

After merging a PR or finishing a local feature, skim `CHANGELOG.md` for that day. For demos, read `DESIGN_NOTES.md` (§14 for tradeoffs) + latest changelog section.
