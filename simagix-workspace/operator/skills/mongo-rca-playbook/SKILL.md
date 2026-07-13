---
name: mongo-rca-playbook
description: Playbook for Mongo Debugger RCA — tier-1 findings, evidence tiers, Hatchet logs, and operator clarifications for FTDC incidents.
---

# Mongo RCA Playbook

Use during **Phase A (investigate)**, **Phase C (final RCA)**, and **post-report chatbot** for Mongo Debugger runs.

## Golden rule

**Deterministic tools find the health issues; you only explain and correlate them.**

- Treat **tier-1 findings** from the evidence bundle as authoritative — do not re-derive diagnoses from raw metrics.
- Fetch **tier-2 metric slices** via MCP evidence tools when you need numbers to support a tier-1 claim.
- Never invent metric values or log lines. Cite evidence paths or tool results.

## Workflow checklist

1. **Read tier-1** — assessment scores, anomaly windows, mongo-ftdc diagnoses from the bundle.
2. **Correlate** — overlap anomaly windows with Hatchet `summary.json` when logs were uploaded.
3. **Pull tier-2 on demand** — one metric family or window at a time via MCP; avoid broad dumps.
4. **Phase B questions** — ask only what tier-1 + tier-2 cannot answer (deploy change, maintenance window, replica role, app traffic pattern).
5. **Final report** — causal chain from evidence → mechanism → impact → fixes; separate **ruled out** hypotheses.

## Language (use in reports)

| Term | Meaning |
|------|---------|
| Run | One upload + derived artifacts (`run_id`) |
| diagnostic.data | Raw FTDC capture — source of truth for metrics |
| Evidence bundle | Tiered JSON from mongo-ftdc — only structured input for reasoning |
| Tier-1 findings | Authoritative deterministic conclusions |
| Tier-2 slices | On-demand metric detail via MCP |

See `references/tier1-checklist.md` and `references/evidence-tools.md` in this skill package.

## Clarifying questions (Phase B)

Good questions:

- Was there a deployment, index build, or backup job during the anomaly window?
- Did the incident affect primaries, secondaries, or specific shards?
- Was WiredTiger cache pressure seen in ops dashboards outside FTDC?

Bad questions:

- Anything already stated in tier-1 findings
- “What does CPU look like?” without checking tier-2 first

## Report quality bar

- **Executive summary** — one paragraph, operator-facing, no jargon wall.
- **Mechanism** — what subsystem failed and why (locks, cache, disk, replication).
- **Evidence** — bullet each claim with bundle section or MCP tool name.
- **Fixes** — ordered: immediate → durable → prevention.
