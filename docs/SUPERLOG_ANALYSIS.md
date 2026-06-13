# Superlog vs. Mongo Debugger — Approaches Worth Borrowing

A grounded read of the [superloglabs/superlog](https://github.com/superloglabs/superlog) codebase (worker pipeline, `packages/fingerprint`, grouping/digest/autorecovery agents) and what it suggests for **cost, accuracy, design, and optimization** in Mongo Debugger.

> TL;DR — Superlog solves a *different* problem (continuous, high-volume error/telemetry streams → grouped incidents → auto-fix PRs), so we should **not** copy its architecture. But it has earned, production-tested patterns around **cheap deterministic preprocessing before any AI**, **two-layer grouping (heuristic → LLM)**, **forced-commit tool discipline**, **structured terminal verdicts**, and a **post-AI verification + human-confirm loop**. Several map directly onto our FTDC RCA flow and would improve cost and trust without changing our core "one reasoning brain" bet.

---

## 1. The two systems are shaped differently

| | **Superlog** | **Mongo Debugger** |
|--|--------------|--------------------|
| Input | Continuous OTLP traces/logs/metrics, high volume, never stops | One FTDC upload per run, bounded |
| Core job | Dedup noise → group into incidents → investigate → propose/auto-fix code | Explain *one* MongoDB incident with cited evidence |
| AI shape | **Many small, narrow LLM calls** at pipeline stages | **One agentic investigation** (3-phase) per run |
| Determinism boundary | Fingerprint + heuristic grouping are deterministic; LLM only at decision edges | `mongo-ftdc` is deterministic; LLM does all reasoning |
| Output | Slack incident, PR, weekly digest | RCA report + Grafana charts |

The key realization: **Superlog spends most of its engineering effort *keeping the LLM out of the loop* — only invoking it when cheap deterministic logic can't decide.** That is the most transferable idea for us.

---

## 2. Superlog's pipeline (what actually happens to a signal)

```text
raw error/log
  → fingerprint()            deterministic hash (type + message bucket + top frames)
  → Issue (dedup by hash)    identical errors collapse, no AI
  → intake:
       heuristic match?      cheap, deterministic — same service/signature → join
       else LLM grouping     ONLY runtime errors, ONLY if heuristic missed
       else open incident
  → investigation agent      tool-driven RCA (Anthropic tool loop)
  → noise/resolution class.  LLM tags incident: real vs cosmetic/self-telemetry
  → autorecovery sweep       periodic LLM re-check "is this resolved?" → confidence-gated
  → human confirm in Slack   high-confidence proposals only; human clicks ✅/✖
  → weekly digest            LLM ranks top-N PRs to merge
```

Note how many **non-AI gates** sit before and after each LLM call. That's the design lesson.

---

## 3. Techniques, with code evidence, and how they map to us

### 3.1 Deterministic fingerprinting *before* any AI — the biggest takeaway

`packages/fingerprint/src/index.ts` normalizes an error into a stable hash **with zero LLM cost**:

- Strips per-occurrence noise via regex before hashing: URLs→`<url>`, UUIDs→`<uuid>`, timestamps→`<ts>`, IPs→`<ip>`, hex→`<hex>`, long ids→`<id>`, numbers→`<n>`.
- Collapses request paths (`/wp-admin`, `/.env`, …) to `<path>` so a bot scan doesn't explode into thousands of "distinct" issues.
- Keeps only the **top 5 user stack frames**, dropping `node_modules`/runtime frames, so cosmetically different stacks with the same root collapse together.
- Unwraps SDK error envelopes so a per-request `request_id` doesn't leak into the bucket.

The payoff is explicit in their comments: without path collapsing *"a single bot sweep explodes into tens of thousands of distinct issues and floods ingestion."*

**Map to Mongo Debugger:** We don't have a high-volume error stream, but the *principle* applies to **Graylog logs** (`backend/app/simagix/graylog_client.py`) and **profiler samples** (`get_profiler_samples`). Today these are passed fairly raw into the agent. A small deterministic normalizer that:
- buckets slow-query log lines by *normalized query shape* (strip literals, collapse `$in` arrays, replace values with placeholders), and
- counts occurrences per bucket,

would let us hand the agent **"this query shape appeared 4,212× with p95 380ms"** instead of 4,212 nearly-identical lines. That's a direct **cost (fewer tokens)** and **accuracy (the agent sees frequency, not a wall of duplicates)** win. → New helper, e.g. `backend/app/simagix/log_fingerprint.py`, called before building the Phase A prompt.

### 3.2 Two-layer grouping: heuristic first, LLM only on miss

`apps/worker/src/incidents/intake.ts` is layered exactly:

```text
1. findHeuristicIncidentMatch()   cheap, deterministic, every issue
2. LLM grouping                   ONLY for kind !== "alert", ONLY if (1) missed
3. open a fresh incident
```

Alerts skip the LLM entirely. The LLM is the *expensive last resort*, never the default.

**Map to us:** We already do the analogous thing well — `mongo-ftdc` produces deterministic findings and the LLM only explains. The borrowable refinement: **gate the LLM phases on whether tier-1 actually needs interpretation.** If tier-1 findings are empty *and* assessment shows no anomaly windows, a full 3-phase agentic run is wasted spend. A cheap pre-check could short-circuit to a templated "no significant anomalies detected" result and skip Phase A entirely — mirroring how Superlog skips the LLM when a heuristic already decided.

### 3.3 The grouping agent's tool discipline — accuracy lever

`apps/worker/src/grouping/tools.ts` + `agent.ts` show several prompt/orchestration patterns that raise accuracy and we partly already do:

- **Bias toward the safe default**: *"Default to 'standalone'. Return 'join' only when there is positive evidence… Surface-level similarity is NOT sufficient."* Hard negative examples are given inline (same HTTP status ≠ same root cause).
- **Forced commit before claiming a conclusion**: the dispatcher *rejects* a `join` decision unless the model first called `inspect_incident` on that target. The code comment: *"requiring an inspect makes it stop and commit to one candidate before claiming a shared root cause."*
- **Structured terminal tool, not free text**: the run ends with exactly one `decide_grouping` tool call (enum decision + ≥20 chars evidence), validated by a parser. *"Do not write a text reply."*
- **Orientation tools**: `list_incident_facets` / `list_incident_titles` let the model cheaply slice before paying to inspect details.

**Map to us:** Our Phase A already emits structured `InvestigationSummary` and Phase C an `RCAReportDraft`, which is good. Two concrete upgrades:
1. **A forced-evidence invariant** like theirs: don't accept an RCA conclusion claiming "metric X caused Y" unless the agent actually called `get_metric_window` for X. We can validate this in `service.py` by checking the tool-call log against claims, and reject/re-prompt if a citation is unbacked. This is the single highest-leverage **accuracy/trust** change — it turns "the model says it looked" into "the orchestrator verified it looked."
2. **Inline hard negatives** in `prompts.py`: explicit "these do NOT justify a root-cause claim" examples (e.g. "high disk latency coinciding with high CPU is correlation, not cause, unless …"). Superlog's negative examples measurably constrain over-eager joins.

### 3.4 Post-AI classification: noise vs. real, and resolution reasons

`incident-result-policy.ts` defines a **closed enum** the LLM must classify into:

- Noise reasons: `cosmetic_log_only`, `lifecycle_signal`, `self_telemetry`, `expected_third_party`, `confusing_log_no_impact`.
- Resolution reasons: `fixed_in_current_code`, `transient_condition_cleared`, `upstream_recovered`.

The free-text model output is **normalized and validated against the enum** (`normalizeNoiseReason` returns `null` if it's not a known value). This is a post-AI guardrail: the model can say anything, but only a recognized category is persisted.

**Map to us:** Add a small **closed taxonomy for the RCA verdict** — e.g. root-cause category (`resource_saturation`, `lock_contention`, `slow_query_plan`, `replication_lag`, `config_misuse`, `external_dependency`, `inconclusive`). Validate Phase C output against it. Benefits: (a) consistent, filterable reports; (b) a natural place to attach **category-specific Grafana panels** and **category-specific follow-up questions** in Phase B; (c) an "inconclusive" category is an honest exit instead of a hallucinated cause.

### 3.5 Autorecovery: the verification loop + human-in-the-loop confirm

This is the part we have *no* analog for and is worth studying. `autorecovery/` runs a periodic sweep that re-investigates open incidents and asks the LLM "does this look resolved?" with strong governance:

- **Confidence gating** (`domain.ts` `decideProposalOutcome`): a proposal is only surfaced if `looks_resolved && confidence ≥ medium`. Low-confidence verdicts are logged but **never bother a human**.
- **Human confirm, never auto-close** (`buildProposalSlackBlocks`): the agent *proposes*; a human clicks ✅ Confirm / ✖ Dismiss. The AI is advisory at the consequential step.
- **Structured terminal tool** again (`propose_resolution` with `looks_resolved`, `confidence`, `reason_code`, `reason_text`), parsed/validated by `parseProposalToolInput`.

**Map to us:** Our flow is single-shot per upload, so a periodic sweep isn't directly relevant. But the **confidence + human-confirm pattern is**. Phase C could emit an explicit `confidence: low|medium|high` on its root-cause claim, and the UI could render low-confidence RCAs as **"hypothesis — needs operator confirmation"** rather than a stated conclusion. This matches our existing "human for ops context only" philosophy and makes the product honest about uncertainty — a strong demo/interview talking point.

### 3.6 Cost-control mechanics worth copying wholesale

Superlog is full of small, cheap guards. The transferable ones:

| Mechanism | Where | Lesson for us |
|-----------|-------|---------------|
| **Short-circuit the LLM when trivial** | `digest/ranker.ts`: `if candidates ≤ TOP_N return trivialPicks` (no LLM call) | Skip Phase A when tier-1 has no anomalies (see 3.2) |
| **`temperature: 0` for decision tasks** | grouping & digest senders | Use temperature 0 for our structured Phase A/C, not just "low" |
| **Hard iteration caps** | `autorecovery` `maxAgentIterations: 6` | We already split budgets (`PHASE2_*_MAX_TOOL_CALLS`) — keep them tight; 6 is their proven number |
| **Cooldowns to prevent repeat spend** | `incident-cooldown.ts`: after a `fixed_in_current_code` verdict, suppress re-investigation 24h (real incident: *"9 agentRuns in 4 hours, every one concluding the same thing"*) | If the same FTDC file/run is re-uploaded, reuse the cached RCA instead of re-running the agent |
| **Graceful fallback on unparseable LLM output** | `ranker.ts` falls back to recency ordering when JSON won't parse | Phase C should have a deterministic fallback (return the investigation summary as-is) rather than failing the run |
| **Pluggable no-op usage sink** | `ai-usage.ts`: token accounting is a registerable sink, default no-op | Add lightweight token/cost logging per phase so cost is *measurable* — you can't optimize what you don't track |

The token accountant (`recordTokenUsage` with `inputTokens/outputTokens/cacheReadTokens/cacheCreationTokens`) is notable: they track **cache read vs. creation tokens separately**, i.e. they lean on **prompt caching**. Our tier-1 bundle is identical across all three phases of a run — it's a perfect candidate for prompt caching to cut input-token cost on Phases B and C.

### 3.7 Message/data shape: compact previews, structured JSON in, structured out

Throughout, Superlog feeds the model **compact previews** (`candidatePreview`, facet counts) and lets it *pull* detail via tools (`inspect_incident`) — never dumping everything up front. This is exactly our tier-1/tier-2 split, so we're aligned. Worth noting as validation that our "librarian serves slices" design matches what a mature system converged on independently.

---

## 4. What NOT to borrow

- **Incident grouping across signals** — we analyze one upload; we don't have a stream to deduplicate. Building fingerprint→issue→incident plumbing would be over-engineering.
- **Auto-fix PR generation / GitHub app** — out of scope for a diagnostic tool.
- **Periodic autorecovery sweep** — no continuous signal to re-check.
- **Many-small-LLM-calls architecture** — our "one reasoning brain" bet is deliberate and better for explainable RCA. Superlog's fan-out fits high-volume triage, not deep single-incident analysis.

---

## 5. Prioritized recommendations

| # | Change | Dimension | Effort | Where |
|---|--------|-----------|--------|-------|
| 1 | **Verify citations**: reject/re-prompt RCA claims not backed by an actual tool call | Accuracy / trust | Med | `llm/service.py` |
| 2 | **Prompt-cache the tier-1 bundle** across Phases A/B/C; log token usage per phase | Cost | Med | `llm/service.py`, `cursor_provider.py` |
| 3 | **Log fingerprinting**: normalize + bucket Graylog/profiler lines with counts before the prompt | Cost + Accuracy | Med | new `log_fingerprint.py` |
| 4 | **Short-circuit**: skip Phase A when tier-1 has no findings *and* no anomaly windows | Cost | Low | `llm/service.py` |
| 5 | **Closed RCA taxonomy** + validation; add `inconclusive`; confidence field on the verdict | Accuracy / design | Low | `prompts.py`, schema |
| 6 | **Confidence-gated UI**: render low-confidence RCAs as "hypothesis, confirm" | Trust / design | Low | `run_detail.html` |
| 7 | **Inline hard-negative examples** in prompts ("correlation ≠ cause" cases) | Accuracy | Low | `prompts.py` |
| 8 | **Deterministic fallback** for Phase C parse failure (emit investigation summary) | Robustness | Low | `llm/service.py` |
| 9 | **Re-upload cache / cooldown**: reuse RCA for an identical run instead of re-running | Cost | Low | pipeline / run store |
| 10 | `temperature: 0` for structured phases | Cost (determinism) | Trivial | provider call |

**Suggested first slice (highest value, contained):** #1 (citation verification) + #2 (prompt caching + token logging) + #5 (taxonomy + confidence). Together they improve trust, cut cost, and make cost measurable — the three things an interviewer/demo audience will probe.

---

## 6. One-line summary for the interview

> "Superlog taught me that the cheapest, most accurate AI system is the one that does as little AI as possible: deterministic fingerprinting and heuristic gates keep the model out of the loop until a decision genuinely needs judgment, every model call ends in a validated structured verdict, and nothing consequential happens without either a confidence gate or a human click. I'm adopting the parts that fit a single-incident RCA — citation verification, a closed root-cause taxonomy with confidence, prompt-cached tier-1, and log fingerprinting — without taking on their stream-grouping/auto-PR machinery that our problem doesn't need."
