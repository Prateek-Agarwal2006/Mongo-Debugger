# Phase 2 — LLM Integration

Phase 2 wires the **agentic LLM brain** on top of the deterministic mongo-ftdc evidence pipeline.

**Last updated:** 2026-06-29

**Status:** Complete (Cursor SDK **or** Gemini ADK + shared MCP registry + Skill WorkArea + 3-phase RCA flow + live Graylog client).

## Components


| Component             | Location                                         | Status   |
| --------------------- | ------------------------------------------------ | -------- |
| Prompt builders       | `backend/app/simagix/llm/prompts.py`             | Complete |
| Providers             | `backend/app/simagix/llm/providers/`             | Complete |
| Cursor provider       | `providers/cursor/provider.py`                   | Complete |
| Gemini ADK provider   | `providers/adk/provider.py` + `runner.py`        | Complete |
| Mock provider         | `providers/mock.py`                              | Complete |
| Shared MCP layer      | `backend/app/simagix/llm/mcp/`                   | Complete |
| MCP servers           | `mcp/servers/{evidence,graylog,hatchet}.py`      | Complete |
| MCP registry | `mcp/registry.py` (`to_cursor_sdk_servers`, `to_adk_mcp_toolsets`) | Complete |
| Skill catalog | `skills/registry.py`, `/skill-workarea` | Complete |
| Phase 2 orchestration | `backend/app/simagix/llm/service.py`             | Complete |
| Web fetch (shared)    | `backend/app/simagix/llm/web_fetch.py`           | Complete |
| Post-report chatbot   | `service.py` + `/phase2/chatbot` API             | Complete |
| Operator MCP registry | `mcp/connectors.py`, `/mcp-workarea`, run checkboxes | Complete |
| Operator skill catalog | `skills/registry.py`, `/skill-workarea`, attach-all | Complete |

## LLM providers

Set `LLM_PROVIDER` in `.env` (see `.env.example`):

| Value | Provider | Requirements |
|-------|----------|--------------|
| `cursor` (default) | `CursorLLMProvider` | `CURSOR_API_KEY` — SDK runs tool loop + stdio MCP |
| `gemini` | `GeminiAdkLLMProvider` | `GOOGLE_API_KEY` from [AI Studio](https://aistudio.google.com/apikey) — ADK `InMemoryRunner` + native `McpToolset` / `SkillToolset` |
| `mock` | `MockLLMProvider` | None — deterministic, reads real bundle |

`get_llm_provider()` also falls back to mock when `LLM_PROVIDER=cursor` and no `CURSOR_API_KEY`. Pass `llm=mock` in API bodies or use `{"llm":"mock"}` on `POST .../phase2/run`.

**Per-run LLM slot:** Each run stores Phase 2 artifacts under `phase2/llm/{mock|cursor|gemini}/`. The run detail UI (`/runs/{run_id}`) uses one **LLM** dropdown (`#llm-context-select`) for both starting RCA and viewing status/trace/report for that slot. Re-running with the same LLM overwrites only that folder.

Install Gemini deps: `uv sync --extra dev --extra llm`.

## Shared vs per-LLM

| Layer | Scoped by | Notes |
|-------|-----------|-------|
| FTDC export bundle | `run_id` only | `uploads/{run_id}/phase1/mongo-ftdc/` — same tier-1 data for all LLMs |
| Hatchet log summary | `run_id` only | `uploads/{run_id}/phase1/hatchet/summary.json` — optional tier-1 log evidence when logs were uploaded |
| `SimagixEvidenceService` | `(run_id, llm)` | New instance per `Phase2Session`; own `RetrievalBudget` |
| Phase 2 artifacts | `llm` | investigation, iterative_state, tool_trace, report, budget, metadata |


## 3-phase RCA flow (PDF 3.4)

```text
POST /phase2/run  (body: {"llm": "mock"} or {"llm_provider": "gemini"})
  Phase A — Investigation (MCP ON, budget: PHASE2_INVESTIGATION_MAX_TOOL_CALLS)
    → InvestigationSummary persisted to phase2/llm/{llm}/investigation.json
  Phase B — Clarify (MCP OFF, max 10 LLM questions from investigation gaps)
    → ClarifyingQuestionsBlock in phase2/llm/{llm}/iterative_state.json

POST /phase2/clarify?llm=mock
  Phase C — Final RCA (MCP ON, budget: PHASE2_RCA_MAX_TOOL_CALLS)
    → tier-1 + investigation + operator answers → RCAReportDraft

GET /phase2/status?llm=mock
  → investigation, questions, answers, status for that LLM slot
```

## Design rules

1. **Start from tier_1 analyzed evidence.** Findings are authoritative.
2. **Investigate before asking.** Tier-2 MCP (+ Graylog when configured) runs before clarifying questions.
3. **Ask user once.** Up to 10 LLM-generated questions in a single block.
4. **Cite everything.** Final RCA cites findings, metric slices, logs, operator answers, and web sources.
5. **Web search is explicit.** The Cursor SDK does not search the internet unless the prompt says so. Phase A and Phase C prompts include *search the web* instructions; results land in `web_insights` (investigation) and `evidence_citations` / `reference_urls` (final RCA).
6. **Tool trace is ground truth.** Every SDK `tool_call` during investigation and final RCA is persisted to `phase2/llm/{llm}/tool_trace.json` and shown in the run page **Agent Tool Activity** panel. Provider-specific adapters normalize into one `ToolTraceEntry` schema (see below). A Web count of 0 means the harness did not invoke web/fetch tools.
7. **Evidence-first mechanisms.** Prompt `EXAMPLES` are non-authoritative placeholders; `EVIDENCE_RULES` forbid keyword-only inference and copying example wording. Mock provider uses `[mock]` stubs for why/mechanism fields.
8. **Local vs MCP tools.** Phase A/C and chatbot may use **read/grep/shell** for analysis; **writes only** under `phase2/llm/{llm}/chatbot_scratch/`. MCP stdio `cwd` stays workspace root; Cursor agent `cwd` for MCP-on phases is `chatbot_scratch/`.
  - **Clarify-only** runs: `cwd` = export bundle, MCP off.
  - **Investigation / final RCA / chatbot** (MCP on): agent `cwd` = `chatbot_scratch/`; bundle and session artifacts reachable by absolute paths in read/grep.
  - **MCP budget** counts simagix-evidence calls; local/shell/web appear separately in the trace UI.
9. **Post-report chatbot (Phase 3).** After `latest_report.json` exists, `GET|POST /phase2/chatbot` drives an agentic thread per `(run_id, llm)`. Full history in `chatbot_chat.json`; prompt uses report + investigation + `summary_of_older` + last N messages. Summarize runs via text-only LLM call when thread exceeds `PHASE2_CHATBOT_SUMMARIZE_AFTER_MESSAGES`. **Attachments:** `POST .../chatbot/attachments` stores files under `chatbot_scratch/attachments/` (text-friendly types, size cap).
10. **Trusted web fetch.** `web_fetch.py` validates HTTPS URLs (SSRF blocks; optional `PHASE2_WEB_ALLOWLIST_SUFFIXES`). Used by Cursor and Gemini — not mongodb-only.
11. **Hatchet waits when logs exist.** If `inputs/mongodb-logs/` contains files, Phase 2 blocks (HTTP 409) until `phase1/hatchet/summary.json` exists. A failed Hatchet job is retried via `POST …/logs/retry`; v1 does not provide a default "run without logs" path after logs were uploaded.
12. **Hatchet prompt section.** Log evidence is appended after mongo-ftdc tier 1:

```text
--- Tier-1 analyzed mongo-ftdc evidence ---
...

--- Tier-1 analyzed Hatchet log evidence ---
...
```

Do not rewrite mongo-ftdc `executive_context.json`; omit the Hatchet section when no logs were uploaded.

13. **Phase A retrievable metric catalog.** After tier-1 findings/windows/highlights, the investigation prompt lists **all** unique metric names from `fallback_retrieval_index.json` (`retrievable_metrics` in prompt context — same set as MCP `list_fallback_metrics`). Clarify and final RCA prompts omit the full list to save tokens; investigation text notes highlights are priorities, not the full set.

**Deferred (not in this iteration):** curated runbook MCP / MCP resources from project PDFs — see [PROJECT_STATUS.md](PROJECT_STATUS.md) future enhancements.

## Operator MCP connectors (MCP WorkArea)

Operators configure optional MCPs at **`GET /mcp-workarea`** (also linked from home and the run page). Connectors persist to:

`{DATA_ROOT}/simagix-workspace/operator/mcp_connectors/registry.json`

| Transport | How configured | Runtime |
|-----------|----------------|---------|
| `http` | Operator-entered `https://` URL + optional headers | `HttpMcpServerConfig` in Cursor SDK |
| `stdio_template` | Template picker only (v1: `github-mcp` Docker) + required env vars | `StdioMcpServerConfig` from `STDIO_TEMPLATES` |

**REST:** `GET/POST/DELETE /simagix/mcp-connectors` — see [RCA_BACKEND.md](RCA_BACKEND.md).

**Per-run selection (stateless):** On `/runs/{run_id}`, checkboxes list user connectors plus locked **simagix-evidence**. Nothing is pre-checked except the built-in. At click time:

- `POST /phase2/run` → `enabled_mcp_ids` for **Phase A** (investigation)
- `POST /phase2/clarify` → `enabled_mcp_ids` for **Phase C** (final RCA — uses **current** checkbox state)

`build_mcp_server_specs()` always includes built-ins (`simagix-evidence`, optional `graylog`, optional `hatchet-evidence`) and merges selected user ids from the WorkArea registry. **Cursor** passes specs to the SDK via `to_cursor_sdk_servers()`; **Gemini ADK** uses native `McpToolset` via `to_adk_mcp_toolsets()`. All operator skills attach automatically via provider-native paths (see Skill WorkArea). Mock accepts MCP fields but ignores them.

**Not in this slice:** saved default selection, free-form stdio commands (templates only).

## Operator skill catalog (Skill WorkArea)

Operators upload skill packages at **`GET /skill-workarea`**. Each upload is a **slot name** + **ZIP** stored pass-through under:

`{DATA_ROOT}/simagix-workspace/operator/skills/{slot_name}/`

| Concern | MCP WorkArea | Skill WorkArea |
|---------|--------------|----------------|
| Configure | Form → `registry.json` | ZIP upload → directory tree |
| Per-run selection | Checkboxes → `enabled_mcp_ids` | **None** — entire catalog attaches on every tool phase |
| Cursor wiring | `AgentOptions.mcp_servers` | `copytree` → `{scratch}/.cursor/skills/` + `setting_sources=["project"]` |
| ADK wiring | `McpToolset` per spec | `SkillToolset(load_skill_from_dir × all)` |

**REST:** `GET/POST/DELETE /simagix/skills` — see [RCA_BACKEND.md](RCA_BACKEND.md).

**Phases with skills:** Phase A, Phase C, chatbot (`include_tools=True`). Clarify unchanged. Mock ignores skills.

## Unified MCP layout (implemented 2026-06-26)

```text
backend/app/simagix/llm/
├── mcp/
│   ├── specs.py          # McpServerSpec, bare-tool server names
│   ├── connectors.py     # WorkArea registry (registry.json)
│   ├── registry.py       # build_mcp_server_specs(), to_cursor_sdk_servers(), to_adk_mcp_toolsets()
│   └── servers/          # @mcp.tool() source of truth (evidence, graylog, hatchet)
├── skills/
│   └── registry.py       # operator skill catalog; Cursor copytree + ADK SkillToolset
├── providers/
│   ├── cursor/provider.py
│   ├── adk/{provider,runner}.py
│   └── mock.py
└── service.py            # get_llm_provider() → providers/*
```

Both Cursor and ADK call `build_mcp_server_specs(session, settings, enabled_mcp_ids=...)`. `adk_evidence_tools.py` is removed; legacy paths re-export or raise.

## Mentor Q&A — Cursor vs Gemini ADK layout, MCP client, and WorkArea (v1)

> **Implementation note (2026-06-26):** Unified MCP is implemented: both providers use `build_mcp_server_specs()` + `enabled_mcp_ids`. ADK attaches tools via native **`McpToolset`** (`to_adk_mcp_toolsets()` in `mcp/registry.py`); the custom `mcp/client.py` bridge was removed. Operator skills upload via **`/skill-workarea`** and attach provider-natively (Cursor: `copytree` + `setting_sources=["project"]`; ADK: `SkillToolset`). The Q&A below captures the *pre-unify* design walkthrough — keep for interview context on why the split existed before consolidation.

Captured from design walkthrough (2026-06-26). Code pointers (current): `providers/cursor/provider.py`, `providers/adk/runner.py`, `mcp/registry.py`, `skills/registry.py`, `mcp/servers/evidence.py`, `mcp/connectors.py`, `session.py` (`mcp_server_env()`).

---

### Q: Why does Cursor look like one file (`cursor_provider.py`) but ADK has `gemini_adk_provider.py`, `adk_runner.py`, and `adk_evidence_tools.py`?

**A:** The short answer: **Cursor doesn’t really live in one file either** — the split just *looks* different because Cursor outsources tools to **MCP subprocesses**, while ADK keeps the tool loop and tools **in-process**.

#### What each “provider file” actually is

Both providers implement the same seam (`LLMProvider`):

| Role | Cursor | Gemini ADK |
|------|--------|------------|
| Provider (A/B/C/chatbot entrypoints) | `cursor_provider.py` (~293 lines) | `gemini_adk_provider.py` (~139 lines) |
| Run the agent + tool loop | **Inside Cursor SDK** (`Agent.create`, `agent.send`, `run.wait`) | **`adk_runner.py`** (~172 lines) — you wire this yourself |
| Evidence tools | **Separate MCP servers** | **`adk_evidence_tools.py`** (~118 lines) — Python functions |

So ADK’s “extra files” aren’t duplicate providers — they’re work **Cursor SDK already does for you**.

#### Cursor: one provider file, but tools elsewhere

`cursor_provider.py` mostly:

1. Builds `AgentOptions` (model, cwd, sandbox, MCP list)
2. Calls `Agent.create` → `send` → collects text
3. Parses JSON into `InvestigationSummary` / report / questions

It does **not** implement metric retrieval. That lives in subprocess MCP servers the SDK spawns:

- `mcp_evidence_server.py` — same tools as ADK, but over MCP stdio
- `graylog_mcp_server.py`, `hatchet_mcp_server.py` — optional
- `web_fetch.py` — shared; Cursor gets it via `build_cursor_sdk_web_tools()`

```text
cursor_provider.py
    └── AgentOptions.mcp_servers → spawns:
            python -m mcp_evidence_server
            python -m graylog_mcp_server   (optional)
            python -m hatchet_mcp_server   (optional)
            + user HTTP/Docker MCPs (WorkArea)
```

**Cursor SDK** = managed runtime (tool loop + MCP lifecycle). **Your code** = config + parse.

#### ADK: three files because nothing is outsourced

Google ADK has no stdio MCP for your evidence layer. Tools are **in-process Python callables** on `Agent(tools=[...])`. You own:

**`gemini_adk_provider.py`** — Same shape as `cursor_provider.py`: call runner, parse output. Shorter because it delegates to `adk_runner`.

**`adk_runner.py`** — Stuff Cursor hides inside the SDK:

- `asyncio` + `InMemoryRunner.run_debug`
- `GOOGLE_API_KEY` / Vertex env
- `after_tool_callback` → write `tool_trace.json`
- Extract assistant text from ADK **events** (not a simple message stream)
- Sync wrapper for FastAPI (`asyncio.run(...)`)

Without this file, `gemini_adk_provider.py` would balloon with ADK plumbing.

**`adk_evidence_tools.py`** — Direct mirror of `mcp_evidence_server.py`:

```python
class AdkEvidenceTools:
    """Function tools for Google ADK — same surface as mcp_evidence_server."""
```

Same `get_metric_window`, `get_raw_path`, Hatchet hooks, `web_fetch` — but as methods ADK can call directly, not MCP JSON-RPC over stdin.

#### Side-by-side mental model

```text
CURSOR PATH                          GEMINI ADK PATH
─────────────────                    ─────────────────
cursor_provider.py                   gemini_adk_provider.py
       │                                      │
       ▼                                      ▼
Cursor SDK (tool loop)               adk_runner.py (tool loop)
       │                                      │
       ▼                                      ▼
MCP subprocesses                     adk_evidence_tools.py
  mcp_evidence_server.py                 (in-process functions)
  graylog / hatchet MCP
       │                                      │
       └──────────► SimagixEvidenceService ◄──┘
```

Same evidence service underneath. Different wiring: MCP subprocess vs Python functions.

#### Why not collapse ADK into one file?

You could merge `gemini_adk_provider.py` + `adk_runner.py` + `adk_evidence_tools.py` into one ~430-line module. The split is **intentional**:

| File | Rationale |
|------|-----------|
| `adk_evidence_tools` ↔ `mcp_evidence_server` | Parallel tool surfaces — easy to diff “do Cursor MCP and ADK expose the same tools?” |
| `adk_runner` | ADK/async/trace glue, testable without parsing RCA JSON |
| `gemini_adk_provider` | Stays thin like other `LLMProvider` implementations |

Cursor *looks* like one file because the SDK absorbed runner + MCP protocol. ADK didn’t, so those layers stay visible in the repo.

#### Fair line-count comparison

| Stack | Provider + runtime + tools |
|-------|---------------------------|
| Cursor | ~293 + ~421 (MCP servers + web_fetch used by Cursor) ≈ **714** |
| ADK | ~139 + ~172 + ~118 ≈ **429** (+ shared `web_fetch`, `tool_trace`, etc.) |

ADK isn’t more complex overall — the responsibility is just **named explicitly** instead of living inside `cursor-sdk` or MCP subprocesses.

**Interview one-liner:** “Cursor: we configure MCP servers; the SDK runs ReAct. Gemini ADK: we implement the tool loop runner and in-process evidence tools ourselves — that’s why `adk_runner` and `adk_evidence_tools` exist alongside a thin `gemini_adk_provider`.”

**Tradeoffs (intent):**

| What we chose (v1) | Why | Pros | Why not the alternative |
|--------------------|-----|------|-------------------------|
| Cursor → MCP servers + SDK client | SDK owns ReAct + MCP lifecycle; we only ship `@mcp.tool` servers | Less Python agent-loop code; WorkArea plugs into `mcp_servers` | **In-process only for Cursor** — SDK model is subprocess MCP |
| ADK → in-process `AdkEvidenceTools` | ADK native API is `Agent(tools=[callables])`; no MCP client in repo | Faster calls (no subprocess JSON-RPC); simpler local dev for Gemini slot | **Duplicate tool surface** vs `mcp_evidence_server`; **WorkArea ignored** on Gemini |
| Split ADK into provider / runner / tools | Match Cursor’s hidden layers with testable seams | Thin provider; runner testable without parse; tools diffable vs MCP | **One fat ADK file** — harder to review and test |

**Superseded (2026-06-26):** MCP unification is implemented — ADK uses native **`McpToolset`** (not a custom client bridge). See [DESIGN_NOTES.md](DESIGN_NOTES.md) §13.18 and §14 row **ADK MCP attachment**.

---

### Q: Does ADK use WorkArea / `enabled_mcp_ids` like Cursor?

> **Superseded (2026-06-26):** ADK now passes `enabled_mcp_ids` into `run_adk_agent_text()` and attaches the same MCP specs via native **`McpToolset`**. The answer below describes **pre-unify v1** only.

**A (historical v1):** **It doesn’t — not in v1.** MCP WorkArea is wired for **Cursor only**. With **Gemini ADK** selected, operator connectors from WorkArea have **no effect** on the agent.

#### What actually happens today

**Shared (all LLMs):**

- `/mcp-workarea` — create/list/delete connectors in `registry.json`
- Run page checkboxes — send `enabled_mcp_ids` on `POST /phase2/run` and `POST /phase2/clarify`
- `service.py` — passes `enabled_mcp_ids` into every provider’s `run_investigation` / `run`

**Cursor path:**

`enabled_mcp_ids` flows into `CursorLLMProvider._mcp_config()` → `build_user_mcp_servers()` → extra entries on `AgentOptions.mcp_servers` (HTTP or Docker stdio templates).

**Gemini ADK path:**

`gemini_adk_provider.py` **accepts** `enabled_mcp_ids` on the method signature (so the shared `LLMProvider` interface compiles) but **never uses it**:

```python
def run_investigation(..., enabled_mcp_ids: list[str] | None = None) -> InvestigationSummary:
    raw_text = run_adk_agent_text(
        session,
        user_message,
        settings=self.settings,
        include_tools=True,
        phase="investigation",
        # enabled_mcp_ids NOT passed
    )
```

No `enabled_mcp_ids` is passed to `run_adk_agent_text`. Same for `run()` (Phase C).

`adk_runner.py` always builds a fixed tool list:

```python
tools = build_adk_agent_tools(session.evidence) if include_tools else []
```

And `build_adk_agent_tools` is only what’s in `adk_evidence_tools.py`:

- Metric / raw / budget tools
- `web_fetch`
- Hatchet tools if `hatchet.db` exists

No registry lookup, no GitHub MCP, no operator HTTP MCPs.

#### Why ADK doesn’t get WorkArea “for free”

MCP WorkArea produces configs for **Cursor SDK’s MCP model** (`HttpMcpServerConfig` / `StdioMcpServerConfig` → subprocess MCP servers).

ADK doesn’t use that model. It uses **in-process Python functions** on `Agent(tools=[...])`. There is no `mcp_servers=` knob in `adk_runner.py`.

Operator connectors are **Cursor-shaped**; ADK would need a **separate bridge** (MCP client).

#### What ADK “has” instead of WorkArea MCPs

| Capability | Cursor | Gemini ADK |
|------------|--------|------------|
| Simagix evidence | MCP `simagix-evidence` | `AdkEvidenceTools` (always on in tool phases) |
| Hatchet | MCP `hatchet-evidence` (when ready) | Same tools as functions (when ready) |
| Graylog | MCP `graylog` (if `GRAYLOG_*` in env) | **Not wired** in ADK tools today |
| Operator GitHub / HTTP MCP | WorkArea + checkboxes | **Ignored** |
| User MCP registry | `build_user_mcp_servers()` | **Not read** |

Checking boxes on the run page while **LLM = Gemini** still POSTs `enabled_mcp_ids`, but the ADK agent never sees those servers.

#### Practical takeaway

- **Configure connectors in WorkArea** — works for any user (disk registry is provider-agnostic).
- **Use them in RCA** — only when **LLM = Cursor**.
- **Gemini ADK** — fixed built-in evidence + `web_fetch` (+ Hatchet when present); WorkArea is a no-op.

**Tradeoffs (WorkArea v1 scope):**

| What we chose | Why | Pros | Why not in v1 |
|---------------|-----|------|----------------|
| WorkArea → Cursor only | Ship operator MCPs without building ADK MCP client | Smaller v1 slice; Cursor SDK already is the client | **ADK MCP client** — extra subprocess/HTTP plumbing + tests |
| API accepts `enabled_mcp_ids` for all providers | One request shape; future Gemini wiring | No API break when ADK catches up | **Hide checkboxes for Gemini** — deferred UX polish |
| Registry on disk (provider-agnostic) | Configure once; attach per run per provider | Same WorkArea UI for all LLMs | **Gemini-specific connector format** — would fork registry |

---

### Q: Does ADK use `@mcp.tool()` in `mcp_evidence_server.py` like Cursor?

**A:** **No.** ADK never imports or runs `mcp_evidence_server.py`. Only the **Cursor** path does.

| | Cursor | ADK |
|--|--------|-----|
| File | `mcp_evidence_server.py` | `adk_evidence_tools.py` |
| Registration | `@mcp.tool()` + FastMCP | Pass callables to `Agent(tools=...)` |
| Invoked by | MCP client (Cursor SDK) over stdio | ADK in-process |
| Evidence service | Built from **env vars** in subprocess | Uses **`session.evidence`** in parent process |

**Same tool names and behavior**, duplicated thin wrappers — not shared `@mcp.tool` definitions.

**Why not reuse `@mcp.tool` for ADK?**

1. `@mcp.tool()` is **server-side** — wires into MCP transport, not ADK’s tool registry.
2. ADK expects **Python callables** — no MCP subprocess.
3. Re-spawning `mcp_evidence_server` from ADK would require an **MCP client** anyway (the unified future path).

---

### Q: When would ADK need an MCP client? Can it reuse `mcp_evidence_server`?

**A:** You need an **MCP client** only when the tool provider is a **separate MCP server** you don’t call as in-process Python — e.g. WorkArea GitHub Docker, HTTP connectors, or if you unify ADK on the same MCP servers as Cursor.

**In-process (no client):** `AdkEvidenceTools` → `SimagixEvidenceService` — what ADK uses today for core evidence.

**External MCP (now via native ADK):** GitHub MCP, HTTP WorkArea connectors — same specs Cursor spawns; ADK attaches them via **`McpToolset`** in `to_adk_mcp_toolsets()` (no custom client bridge).

If you build that client, you **replace** `adk_evidence_tools` for those tools by connecting to **`mcp_evidence_server`** (same `@mcp.tool` server Cursor uses), not by running `adk_evidence_tools` *through* MCP. One tool definition path; client vs direct-call is the adapter choice.

```text
registry.json + enabled_mcp_ids
            │
            ▼
     mcp/registry.py  (build_mcp_server_specs)
            │
     ┌──────┴──────┐
     ▼             ▼
to_cursor_sdk   to_adk_mcp_toolsets
_servers()           │
     │               ▼
     │         ADK Agent(tools=[McpToolset…])
     └───────┬───────┘
             ▼
    MCP servers (stdio / HTTP)
```

**Interview one-liner:** “MCP client ↔ MCP server when the server is external; direct Python when the logic is already in our app like `AdkEvidenceTools`. WorkArea connectors are external MCP — Cursor SDK is the client; ADK would need ours.”

---

## Mentor Q&A — Cursor SDK agent runtime

Captured from design walkthrough (2026-06-25). Verbatim user questions below; answers are the assistant replies from that session (lightly formatted for docs). Code pointers: `cursor_provider.py`, `session.py` (`mcp_server_env()`), `mcp_evidence_server.py`, `prompts.py` (`SCRATCH_RULES`), `run_workspace.py` (`get_run_workspace()`).

---

### Q: `agwhat is best assitabt text> and collect assistant text`

**A:** In `cursor_provider.py`, these two helpers solve one problem: **how to get the agent’s final text reply** from the Cursor SDK after a run.

When Phase 2 runs, `_run_agent_text` does this:

```python
assistant_chunks: list[str] = []
...
run = agent.send(user_message, SendOptions(mode="agent"))
for message in run.messages():
    trace.record_sdk_message(message, phase)
    self._collect_assistant_text(message, assistant_chunks)
result = run.wait()
...
return self._best_agent_text(result, assistant_chunks)
```

So there are **two sources** of text:

| Source | When it arrives | Variable |
|--------|-----------------|----------|
| **Streamed messages** | During the loop over `run.messages()` | `assistant_chunks` |
| **Final result** | After `run.wait()` | `result.result` |

#### `_collect_assistant_text` — collect streamed chunks

```python
def _collect_assistant_text(self, message: Any, chunks: list[str]) -> None:
    if getattr(message, "type", None) != "assistant":
        return
    content = getattr(getattr(message, "message", None), "content", ()) or ()
    for block in content:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                chunks.append(text)
```

- Runs on **every** SDK message as the agent works.
- Keeps only messages with `type == "assistant"`.
- Pulls out text blocks (`type == "text"`) and appends them to `assistant_chunks`.
- **Why:** While the agent runs (tool calls, thinking, etc.), it may emit assistant text in the stream. That text can include the full JSON we need for investigation / clarify / final RCA.

#### `_best_agent_text` — pick the better of the two

```python
@staticmethod
def _best_agent_text(result: Any, assistant_chunks: list[str]) -> str:
    streamed = "".join(assistant_chunks).strip()
    final = (getattr(result, "result", None) or "").strip()
    if len(streamed) > len(final):
        return streamed
    return final or streamed
```

- Joins all streamed chunks → `streamed`.
- Reads `result.result` from `run.wait()` → `final`.
- **Uses whichever string is longer.**
- If `final` is empty, falls back to `streamed`.
- **Why:** Sometimes `result.result` is a short summary and the full JSON only appears in the stream (or the other way around). Longer usually means more complete JSON, which matters for `parse_investigation_summary`, `parse_clarifying_questions`, and `parse_rca_report`.

**Where the chosen text goes:**

| Phase | Parsed into |
|-------|-------------|
| Investigation | `InvestigationSummary` |
| Clarify | `ClarifyingQuestionsBlock` |
| Final RCA | `RCAReportDraft` + stored as `raw_assistant_text` on `Phase2RunResult` |
| Chatbot | Returned as markdown in `ChatbotResult.content` |

This was added after a bug where truncated `result.result` broke JSON parsing — see CHANGELOG: *“prefer longer streamed assistant text in cursor_provider.py”*.

**Gemini equivalent:** Gemini ADK does something similar in `adk_runner.py` with `_extract_assistant_text(events)` — it walks ADK events and collects non-partial assistant text chunks, then joins them.

**One-line summary:** `_collect_assistant_text` gathers text from the live message stream; `_best_agent_text` compares stream vs final result and keeps the longer/more complete one for parsing.

---

### Q: `how is Agent being passed mcp servers and how is it calli9ng that`

**A:** **Your Python code never calls MCP tools directly.** You pass MCP server configs into `AgentOptions`; the **Cursor SDK** starts those servers as **subprocesses**, and the **cloud agent runtime** decides when to invoke them during `agent.send(...)`.

#### Step A — Build the server list (`_mcp_config`)

```python
def _mcp_config(self, session: Phase2Session) -> dict[str, StdioMcpServerConfig]:
    env = session.mcp_server_env()
    workspace_cwd = str(session.workspace_root)
    servers: dict[str, StdioMcpServerConfig] = {
        "simagix-evidence": StdioMcpServerConfig(
            command=sys.executable,
            args=["-m", "backend.app.simagix.llm.mcp_evidence_server"],
            env=env,
            cwd=workspace_cwd,
        )
    }
    # optional: graylog, hatchet-evidence
    return servers
```

Each entry tells the SDK: **spawn this Python module as a child process**, talk MCP over **stdio**.

| Key | Module | When |
|-----|--------|------|
| `simagix-evidence` | `mcp_evidence_server` | Always (when MCP enabled) |
| `graylog` | `graylog_mcp_server` | If `GRAYLOG_*` env set |
| `hatchet-evidence` | `hatchet_mcp_server` | If Hatchet summary exists for run |

#### Step B — Put them on `AgentOptions` (`_agent_options`)

```python
return AgentOptions(
    api_key=self.settings.cursor_api_key,
    model=self.settings.cursor_model,
    local=LocalAgentOptions(...),
    mcp_servers=self._mcp_config(session) if include_mcp else {},
)
```

- **`include_mcp=True`** → MCP servers attached (investigation, final RCA, chatbot).
- **`include_mcp=False`** → `mcp_servers={}` (Phase B clarify, chat summarize — text-only).

#### Step C — Create agent and run

```python
with Agent.create(self._agent_options(...)) as agent:
    run = agent.send(user_message, SendOptions(mode="agent"))
    for message in run.messages():
        trace.record_sdk_message(message, phase)
        self._collect_assistant_text(message, assistant_chunks)
    result = run.wait()
```

`Agent.create(...)` is where the SDK reads `mcp_servers` and starts the subprocesses.

#### What env the MCP subprocess gets

`Phase2Session.mcp_server_env()`:

```python
{
    "SIMAGIX_RUN_ID": self.run_id,
    "SIMAGIX_WORKSPACE_ROOT": workspace,
    "SIMAGIX_BUDGET_STATE_PATH": str(self.budget_state_path),
    "SIMAGIX_MAX_TOOL_CALLS": str(self.evidence.budget.max_tool_calls),
    "PYTHONPATH": pythonpath,
}
```

The MCP server uses those to know **which run**, **where files live**, and **tool-call budget** (`budget_state.json` on disk).

#### What the MCP server actually is

`mcp_evidence_server.py` is a **FastMCP** app:

```python
mcp = FastMCP("simagix-evidence")

@mcp.tool()
def get_metric_window(...) -> dict[str, Any]:
    return _evidence_service().get_metric_window(...)

def main() -> None:
    mcp.run(transport="stdio")
```

It listens on **stdin/stdout** using the MCP protocol — not HTTP. The Cursor SDK is the MCP **client**; this module is the MCP **server**.

#### How the agent “calls” MCP (runtime loop)

```text
FastAPI / service.py
    → CursorLLMProvider._run_agent_text()
        → AgentOptions.mcp_servers = { "simagix-evidence": StdioMcpServerConfig(...) }
        → Agent.create() / agent.send()

Cursor agent runtime (cloud)
    → model decides: call get_metric_window(metric=...)
    → SDK sends MCP request over stdio to subprocess
    → mcp_evidence_server runs tool → returns JSON
    → SDK feeds result back to model
    → repeat until model returns final text
```

You don’t write `get_metric_window(...)` calls in `cursor_provider.py`. The **model** chooses tools; the **SDK** executes them.

`ToolTraceCollector.record_sdk_message` watches SDK messages with `type == "tool_call"`. Cursor often wraps MCP as a generic `"mcp"` tool; `resolve_tool_identity` in `tool_trace.py` unwraps it to e.g. `simagix-evidence/get_metric_window`.

Cursor often wraps MCP as a generic `"mcp"` tool; `resolve_tool_identity` in `tool_trace.py` unwraps it to e.g. `simagix-evidence/get_metric_window`.

Saved to `phase2/llm/<llm>/tool_trace.json` for the UI.

#### MCP vs other tools (don’t mix them up)

| Mechanism | Configured via | Examples |
|-----------|----------------|----------|
| **MCP servers** | `AgentOptions.mcp_servers` | `get_metric_window`, Hatchet tools, Graylog |
| **SDK custom tools** | `LocalAgentOptions.custom_tools` | `web_fetch` (`build_cursor_sdk_web_tools`) |
| **SDK built-ins** | Cursor SDK local agent | `read`, `grep`, etc. (prompts say prefer MCP for evidence) |

MCP = separate Python subprocess over stdio. `web_fetch` = in-process SDK custom tool, not MCP.

**One-line summary:** `_mcp_config()` builds `StdioMcpServerConfig` entries → `_agent_options()` puts them on `AgentOptions.mcp_servers` → `Agent.create()` starts subprocess MCP servers → during `agent.send()`, the Cursor SDK routes model tool calls to those servers over stdio → your code only streams messages, logs them in `tool_trace`, and parses the final assistant text.

---

### Q: `explain this AgentOptions and LocalAgentOptions`

**A:** They come from the **Cursor SDK** (`cursor-sdk`). They are **configuration objects** — you build them in Python and pass them to `Agent.create(...)`. They do not run anything by themselves.

#### Mental model

```text
AgentOptions          ← “whole agent session” (cloud model + tools + MCP)
  ├── api_key, model  ← who to talk to (Cursor Cloud)
  ├── mcp_servers     ← external tool servers (your evidence MCP)
  └── local           ← LocalAgentOptions
        ├── cwd       ← filesystem root for SDK built-in tools
        ├── sandbox_options
        ├── custom_tools  ← your web_fetch
        └── setting_sources
```

- **`AgentOptions`** = everything needed to **create** an agent.
- **`LocalAgentOptions`** = settings for what runs **on your machine** alongside the cloud agent (cwd, sandbox, custom tools).

The cloud model reasons; the local side executes file/shell/custom/MCP tools.

#### `AgentOptions` — top-level agent config

| Field | Our usage | Meaning |
|-------|-----------|---------|
| `api_key` | `CURSOR_API_KEY` | Auth for Cursor Cloud |
| `model` | `CURSOR_MODEL` (e.g. `composer-2.5`) | Which model runs the agent |
| `local` | `LocalAgentOptions(...)` | Local execution settings |
| `mcp_servers` | `_mcp_config(session)` or `{}` | MCP subprocesses |
| `cloud`, `agents`, `agent_id`, … | not used | SDK extras / resume |

One fresh `AgentOptions` per phase run (investigation / clarify / final / chatbot).

#### `LocalAgentOptions` — local side of the agent

| Field | Our value | Meaning |
|-------|-----------|---------|
| `cwd` | `chatbot_scratch/` (MCP on) or bundle (MCP off) | Working directory for SDK **built-ins** |
| `setting_sources` | `[]` | Don’t load Cursor IDE settings from disk |
| `sandbox_options` | `SandboxOptions(enabled=True)` | Sandbox on — built-ins restricted by Cursor SDK |
| `auto_review` | `True` when MCP on | Smart Auto Review — headless SDK can approve MCP without interactive prompt |
| `custom_tools` | `web_fetch` via `build_cursor_sdk_web_tools(...)` | In-process SDK tools we define |

**One-line summary:** `AgentOptions` = “Create a Cursor agent with this model, these MCP servers, and these local settings.” `LocalAgentOptions` = “On this machine, use this working directory, sandbox policy, and custom tools when the agent needs local execution.” In Mongo Debugger, MCP carries evidence retrieval; `LocalAgentOptions` mainly sets cwd + `web_fetch`, while the cloud model drives the tool loop.

---

### Q: `what are built ins?`

**A:** **Built-ins** = the **default local tools that come with the Cursor SDK agent** — not tools you wrote, and not your MCP servers.

When you call `Agent.create(AgentOptions(local=LocalAgentOptions(...)))`, the SDK gives the cloud model a standard toolbox for working on files on your machine.

#### Three tool types in this project

| Type | Who provides it | Examples |
|------|-----------------|----------|
| **Built-ins** | Cursor SDK (automatic) | `read`, `grep`, `glob`, `list_dir`, `shell` |
| **Custom tools** | `LocalAgentOptions.custom_tools` | `web_fetch` |
| **MCP tools** | Subprocess MCP servers | `get_metric_window`, Hatchet tools, Graylog |

Prompts (`SCRATCH_RULES` in `prompts.py`):

```text
- You MAY use read, grep, and shell for analysis.
- read/grep: FTDC export bundle, workspace exports, session artifacts, chatbot_scratch/.
- shell: create and run scripts ONLY under chatbot_scratch/; print results to stdout.
```

For **evidence**, prompts steer the agent toward **MCP** (`simagix-evidence`), not built-ins.

#### What each built-in roughly does

| Built-in | Purpose |
|----------|---------|
| `read` | Read a file from disk |
| `grep` | Search file contents |
| `glob` / `list_dir` | Find/list files |
| `shell` | Run terminal commands |

They run **locally**, scoped by `LocalAgentOptions.cwd` (and optionally `SandboxOptions`). `tool_trace.py` classifies these as category `"local"`.

#### Built-ins vs MCP

**MCP tools** — your code controls them; enforce **retrieval budget** (`budget_state.json`); return structured evidence slices; **preferred for RCA proof**.

**Built-ins** — generic file/system access; **not counted** in MCP retrieval budget; useful for chatbot attachments, scratch notes; prompts limit **writes** to `chatbot_scratch/` only.

You don’t register built-ins in `AgentOptions` — they’re **included by the SDK** when local agent mode is enabled.

From DESIGN_NOTES:

> **Cursor SDK built-ins** (`read`, `grep`, `shell`, `web`) are **not** in `budget_state.json` — they appear in **Agent Tool Activity** (`tool_trace.json`). Prompts discourage local/shell in favor of MCP.

**One-line summary:** Built-ins = Cursor SDK’s built-in local tools (`read`, `grep`, `shell`, etc.) for filesystem/terminal work. Your app adds **MCP** for gated evidence and **`web_fetch`** as a custom tool; prompts tell the agent to use MCP for RCA evidence and use built-ins mainly for scratch files and chatbot attachments.

---

### Q: `okkkkkkk what if sandbox is on ?`

**A:** The Cursor SDK runs **built-in local tools** (`read`, `grep`, `shell`, etc.) inside a **restricted environment** — limited filesystem and network access.

**Right now the code has sandbox on:**

```python
sandbox = SandboxOptions(enabled=True)
```

#### What sandbox affects (and what it doesn’t)

| Affected | Not affected |
|----------|--------------|
| SDK **built-ins**: `read`, `grep`, `glob`, `shell` | **MCP servers** (separate subprocesses) |
| Where those tools can read/write on disk | Cloud model / API calls |
| Often local network from `shell` | **`web_fetch`** custom tool (runs in our Python process) |

Sandbox is mainly a **seatbelt on built-in** tools, not on MCP evidence retrieval.

#### Sandbox ON — behavior

```text
Model: "read /some/path/file.json"
  → SDK built-in read
  → cursorsandbox only allows paths inside allowed roots
  → paths outside jail → blocked or error
```

**Pros:** Agent can’t freely wander the whole machine; harder to edit `backend/`, git files, etc.

**Cons in this app:**

- `read`/`grep` on bundle paths may fail if sandbox jail ≠ where evidence files live.
- `shell` in `chatbot_scratch/` may be blocked or limited.
- Agent `cwd` is `chatbot_scratch/` for MCP phases — sandbox + narrow cwd can make **absolute-path reads** of `uploads/.../phase1/mongo-ftdc/` unreliable.

#### Sandbox ON vs OFF by phase (docs / history)

| Phase | MCP | Agent `cwd` | Docs / history suggest |
|-------|-----|-------------|------------------------|
| Investigation / Final / Chatbot | ON | `chatbot_scratch/` | **Sandbox ON** (current) |
| Clarify (Phase B) | OFF | export bundle | **Sandbox ON** was considered for clarify-only |

**Current code:** `SandboxOptions(enabled=True)` for **all** phases.

#### History

```text
2026-06-11: sandbox ON  → safety for built-ins (no MCP-only switch in SDK)
2026-06-14: sandbox OFF when MCP ON → MCP + cwd fixes; local reads needed across workspace paths
Today:     sandbox ON always in cursor_provider.py
```

**One-line summary:** Sandbox ON locks down **built-in** tools. Sandbox OFF = more freedom for local reads + MCP together. MCP evidence tools don’t depend on sandbox either way.

---

### Q: `so where is env / path where agent can work in sandbox defined`

**A:** There is **not** one single “sandbox path” knob in this repo. **Three separate scopes** are configured in different places — and `SandboxOptions` only has `enabled`, not a custom path list.

#### 1. Built-in tools (`read`, `grep`, `shell`) — `LocalAgentOptions`

Defined in `_agent_options()`:

```python
bundle_cwd = str(session.evidence.bundle_dir)
scratch_cwd = str(session.ensure_chatbot_scratch_dir())
if include_mcp:
    agent_cwd = scratch_cwd
else:
    agent_cwd = bundle_cwd
sandbox = SandboxOptions(enabled=True)
...
    local=LocalAgentOptions(
        cwd=agent_cwd,
        setting_sources=[],
        sandbox_options=sandbox,
        custom_tools=custom_tools or None,
    ),
```

| Setting | Where | What it does |
|---------|--------|----------------|
| **`cwd`** | `LocalAgentOptions.cwd` | Default working directory for SDK **built-ins** |
| **`sandbox_options`** | `SandboxOptions(enabled=True)` | Only on/off — **no path field** in our code or the SDK type |

**Actual paths on disk**

Root comes from **`DATA_ROOT`** (or repo root):

```python
# run_workspace.py — get_run_workspace()
root = settings.data_root if settings.data_root is not None else repo_root()
return RunWorkspace(root)
```

| Phase | `include_mcp` | Agent `cwd` (built-ins) |
|-------|---------------|-------------------------|
| Investigation / Final / Chatbot | `True` | `{DATA_ROOT}/simagix-workspace/uploads/{run_id}/phase2/llm/{cursor\|gemini\|mock}/chatbot_scratch/` |
| Clarify (Phase B) | `False` | `{DATA_ROOT}/simagix-workspace/uploads/{run_id}/phase1/mongo-ftdc/` (export bundle) |

**If sandbox were ON:** Cursor SDK would restrict built-ins internally (its `cursorsandbox` helper). This app does **not** pass extra sandbox roots — the SDK typically ties limits to `cwd` plus its own rules. We do not configure “allowed paths” in `cursor_provider.py`.

**Prompt policy** (not SDK config): `prompts.py` `SCRATCH_RULES` — reads allowed broadly; writes only under `chatbot_scratch/`.

#### 2. MCP servers — separate from sandbox

MCP is **not** controlled by `SandboxOptions`. It uses `StdioMcpServerConfig`:

```python
"simagix-evidence": StdioMcpServerConfig(
    command=sys.executable,
    args=["-m", "backend.app.simagix.llm.mcp_evidence_server"],
    env=env,
    cwd=workspace_cwd,
)
```

| Setting | Value | Purpose |
|---------|--------|---------|
| **`cwd`** | `session.workspace_root` | MCP subprocess starts here (repo root or `DATA_ROOT`) |
| **`env`** | `session.mcp_server_env()` | Run id, workspace, budget file, `PYTHONPATH` |

Env vars:

```python
{
    "SIMAGIX_RUN_ID": self.run_id,
    "SIMAGIX_WORKSPACE_ROOT": workspace,
    "SIMAGIX_BUDGET_STATE_PATH": str(self.budget_state_path),
    "SIMAGIX_MAX_TOOL_CALLS": str(self.evidence.budget.max_tool_calls),
    "PYTHONPATH": pythonpath,
}
```

MCP server reads evidence via `RunWorkspace` + `SIMAGIX_RUN_ID`, e.g. bundle under `uploads/{run_id}/phase1/mongo-ftdc/`.

**Budget file path:** `.../uploads/{run_id}/phase2/llm/{cursor|gemini|mock}/budget_state.json` (per LLM slot).

#### 3. Three “worlds” (diagram)

```text
┌─────────────────────────────────────────────────────────────┐
│ DATA_ROOT (or repo root)  ← get_run_workspace().root        │
└─────────────────────────────────────────────────────────────┘
         │
         ├── LocalAgentOptions.cwd  (built-ins)
         │     MCP on  → .../phase2/llm/{llm}/chatbot_scratch/
         │     MCP off → .../phase1/mongo-ftdc/
         │     + SandboxOptions(enabled=?)  ← only ON/OFF
         │
         ├── StdioMcpServerConfig.cwd = workspace_root
         │     + env: SIMAGIX_* , PYTHONPATH
         │     → python -m mcp_evidence_server
         │
         └── Prompt rules (SCRATCH_RULES)
               → where agent *should* read/write (soft policy)
```

#### Direct answer

| Concern | Defined in |
|---------|------------|
| **Env for MCP** | `Phase2Session.mcp_server_env()` + `StdioMcpServerConfig` in `_mcp_config()` |
| **Path for built-ins** | `LocalAgentOptions.cwd` in `_agent_options()` |
| **Sandbox boundary** | `SandboxOptions(enabled=True/False)` only — **no explicit path list** in this project. With sandbox on, limits come from Cursor SDK internals (likely centered on `cwd`), not from Mongo Debugger config. |
| **Global data root** | `DATA_ROOT` → `get_run_workspace().root` → all upload/phase1/phase2 paths |

**Summary:** We define `cwd` and MCP `env`/`cwd`. We do **not** define sandbox allowed paths — only whether sandbox is enabled.

---

### Q: `why does off has different cwd`

**A:** The different `cwd` is **not** because sandbox is on/off. In code, **`sandbox` is on** and **`cwd` switches on `include_mcp`**, not on `SandboxOptions`:

```python
if include_mcp:
    agent_cwd = scratch_cwd
else:
    agent_cwd = bundle_cwd
sandbox = SandboxOptions(enabled=True)
```

Two separate questions:

1. **Why different `cwd` for MCP-on vs MCP-off?** ← what the code actually does  
2. **Why did docs mention different sandbox + cwd together?** ← historical pairing from a bugfix

#### Why different `cwd` (MCP on vs off)

| Phase | `include_mcp` | `cwd` | Why |
|-------|---------------|-------|-----|
| Investigation, Final RCA, Chatbot | `True` | `chatbot_scratch/` | MCP supplies evidence; local tools are for scratch files, attachments, optional shell |
| Clarify (Phase B) | `False` | `phase1/mongo-ftdc/` (bundle) | No MCP — if the agent uses `read`/`grep`, it should sit in the export bundle |

**MCP on → `chatbot_scratch/`**

- Evidence is meant to come from **MCP** (`get_metric_window`, etc.), not by wandering the bundle with `read`.
- **`chatbot_scratch/`** is the safe write area (prompts: shell/write only there).
- Keeps the agent from treating the export bundle as its “home” and accidentally editing tiered JSON.

Path: `simagix-workspace/uploads/{run_id}/phase2/llm/{llm}/chatbot_scratch/`

**MCP off → export bundle**

- Phase B is **text-only JSON** (clarifying questions).
- No MCP servers attached (`mcp_servers={}`).
- If the model still uses built-in `read`/`grep`, `cwd` on the bundle is the natural place for export files.

Path: `simagix-workspace/uploads/{run_id}/phase1/mongo-ftdc/`

Prompts also say clarify should **not** re-fetch metrics — it uses the investigation summary already in the user message.

#### This is separate from sandbox

`SandboxOptions(enabled=False)` does **not** change `cwd`. It only controls whether Cursor **locks down** built-in tools (when `True`).

**Current code:** sandbox on; `cwd` still flips with `include_mcp`.

Docs/CHANGELOG sometimes mention both together because of an **older intended setup**:

> *“sandbox off when MCP on; bundle + sandbox on for clarify-only”* — CHANGELOG 2026-06-14

That was: narrow `cwd` for clarify **plus** turn sandbox on for extra safety when MCP is off. **Current code** kept the **cwd split**; sandbox stays off for all phases.

#### Why MCP-on uses scratch (bugfix context)

Earlier, agent `cwd` was the bundle only. That contributed to MCP subprocess problems (imports, budget path). The fix split responsibilities:

| Component | `cwd` / root |
|-----------|----------------|
| **MCP subprocess** | `workspace_root` (repo / `DATA_ROOT`) + `SIMAGIX_*` env |
| **Agent built-ins** | `chatbot_scratch/` when MCP on |

So: **MCP runs from project root; agent local tools default to scratch** — they do not share one directory.

**One-line summary:** Different `cwd` = different phase needs: MCP-on phases use `chatbot_scratch/` (MCP for evidence, scratch for writes); MCP-off clarify uses the export bundle as `cwd` if built-ins read files. **Sandbox off does not pick the path — `include_mcp` does.**

---

### Q: `very imp convo can you write it docs and tell me where are you wrting it` (user pasted full cwd/sandbox Q&A above)

**A (where to write — from Ask-mode reply, then applied in Agent mode):**

| Priority | File | Why |
|----------|------|-----|
| **1 — main home** | [`docs/PHASE2_LLM.md`](PHASE2_LLM.md) | Matrix row: *Phase 2 agent, MCP tools, prompts, budgets* — owns agent/MCP semantics |
| **2 — mentor Q&A** | [`docs/DESIGN_NOTES.md`](DESIGN_NOTES.md) §13 + §14 talking points | Low-level concept + why cwd split / sandbox off |
| **3 — fix stale text** | [`docs/DESIGN_NOTES.md`](DESIGN_NOTES.md) §13 Setup | Was wrong vs current code (`cwd=bundle_dir`, `SandboxOptions(enabled=True)`) |
| **4 — changelog** | [`docs/CHANGELOG.md`](CHANGELOG.md) | Docs-only entry: What / How / Why |

**Not** a new standalone file — expand existing docs under `docs/`.

**Applied:** This section (**Mentor Q&A — Cursor SDK agent runtime**) is the canonical capture. [`DESIGN_NOTES.md`](DESIGN_NOTES.md) §13 Setup bullets updated + link here. [`CHANGELOG.md`](CHANGELOG.md) dated entry added.

---

## MCP tools

**simagix-evidence:** `get_metric_window`, `get_normalized_series`, `get_raw_path`, `list_fallback_metrics`, `get_budget_status`

**Hatchet MCP tools (v2):** `get_hatchet_slow_ops`, `get_hatchet_log_examples`, `get_hatchet_audit`, `get_hatchet_connection_timeline` — registered when `phase1/hatchet/summary.json` and `hatchet.db` exist. Server id: `hatchet-evidence` (Cursor MCP) / ADK function tools (Gemini). Shares retrieval budget with simagix-evidence. v1 `summary.json` remains tier 1; these tools are tier 2.

## Hatchet Citation Types

When Hatchet evidence is present, final RCA citations should distinguish log evidence from FTDC metrics:

| Source type | Use |
|-------------|-----|
| `hatchet_summary` | General claim sourced from `summary.json` |
| `hatchet_slow_op` | Slow-op pattern from `top_slow_ops_by_avg_ms` or `top_slow_ops_by_total_ms` |
| `hatchet_log_example` | One of the capped slowest log examples |
| `hatchet_audit` | Exceptions, failed message families, namespace/app/IP/driver rollups |
| `hatchet_connection_timeline` | Capped connection timeline rollup |

**graylog** (optional): `query_logs_around_window` — uses Graylog Universal Search absolute API when `GRAYLOG_API_URL` + `GRAYLOG_API_TOKEN` are set.

## Graylog setup

Graylog stores **application/DB text logs** (separate from FTDC metrics). Configure:

```bash
export GRAYLOG_API_URL="https://graylog.example.com"
export GRAYLOG_API_TOKEN="your-api-token"
export GRAYLOG_AUTH_MODE="token"   # or "basic"
export GRAYLOG_DEFAULT_QUERY="source:mongod OR mongodb"
```

Without Graylog, the MCP returns `configured: false` and a mock sample for demos.

## Endpoints

```bash
# Phase A+B: investigation + clarifying questions
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/run" \
  -H 'Content-Type: application/json' -d '{"llm": "gemini"}'

# List configured providers
curl "http://localhost:8000/simagix/runs/phase2/llm-providers"

# List per-LLM slots for a run
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/llm"

# Phase C: final RCA
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/clarify?llm=mock" \
  -H 'Content-Type: application/json' \
  -d '{"answers": {"open_q_0": "No maintenance"}}'

# Session state (requires llm)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/status?llm=mock"

# SDK tool-call trace
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/tool-trace?llm=mock"

# Latest report
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/reports/latest?llm=mock&format=pretty"

# Post-report chatbot (requires latest_report.json)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/chatbot?llm=mock"
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/chatbot/messages?llm=mock" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Explain the root cause in plain language"}'
```

**Migration:** Delete legacy flat files at `phase2/*.json` (run root) and re-run RCA per LLM. No automatic migration.

## Persistence

```text
simagix-workspace/runs/<run_id>/phase2/
  llm_index.json                 # optional index of slots
  llm/
    mock/
      budget_state.json
      investigation.json
      iterative_state.json
      tool_trace.json
      latest_report.json
      session_metadata.json
      chatbot_chat.json
      chatbot_scratch/
    cursor/
      ...
    gemini/
      ...
```

FTDC bundle (`uploads/<run_id>/phase1/mongo-ftdc/`) is **not** duplicated per LLM.

## Tool trace (one schema, provider adapters)

Storage and UI are shared; **recording** differs per provider:

| Provider | Recording path | Notes |
|----------|----------------|-------|
| Cursor SDK | `cursor_provider.py` → `ToolTraceCollector.record_sdk_message()` | Parses streamed `tool_call` messages; `resolve_tool_identity()` unwraps `"mcp"` payloads |
| Gemini ADK | `adk_runner.py` → `after_tool_callback` + `record_grounding_metadata` | Evidence tools as MCP; `GoogleSearchTool` + grounding metadata as **web** (`google_search`) |
| Mock | `write_mock_tool_trace()` | Deterministic demo rows |

All paths write to the same `tool_trace.json` under the active LLM folder. The API and **Agent Tool Activity** panel only read the normalized entries — no separate trace viewer per provider.

## Agent Tool Activity (UI)

On `/runs/{run_id}`, the RCA section uses a two-column grid: **Root Cause Analysis** and **Agent Tool Activity**. The panel loads `GET /phase2/tool-trace?llm=...` (selected LLM from dropdown) and shows phase, category badge (MCP / Web / Local / Shell), tool name, status, and args/result summary.

Cursor SDK records MCP calls as tool name `"mcp"` with the real tool in args (`toolName`, `providerIdentifier`). `resolve_tool_identity()` in `tool_trace.py` normalizes these to readable names like `simagix-evidence/get_metric_window`. The API also reads `tool_trace.json` from disk after server restart (session store is in-memory).

Implementation: `backend/app/simagix/llm/tool_trace.py`, `frontend/static/js/rca.js`.

## Schemas

- `InvestigationSummary` — Phase A output (`web_insights: string[]` optional URLs + takeaways)
- `ClarifyingQuestionsBlock` — Phase B output (max 10 questions)
- `RCAReportDraft` — Phase C output (`reference_urls: string[]` bibliography; `EvidenceCitation.source_type` includes `web` and `operator`)

## Grounding alignment

`GroundingRules` (`backend/app/simagix/grounding.py`) whitelists `investigation_summary`, `log_insights`, `operator_clarifications`, `finding.suggestion`, and `web_search`. Phase-specific prompts use `build_tier1_evidence_block()` for tier-1 content; only Phase C appends the RCAReportDraft footer via `build_phase2_prompt()`.