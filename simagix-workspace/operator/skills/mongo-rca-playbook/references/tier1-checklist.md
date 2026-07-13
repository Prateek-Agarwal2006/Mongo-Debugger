# Tier-1 checklist (before asking the operator)

Confirm these from the evidence bundle before Phase B questions:

- [ ] **Assessment scores** — which dimensions are red/yellow (CPU, memory, disk, replication, etc.)
- [ ] **Anomaly windows** — start/end UTC for each flagged window
- [ ] **mongo-ftdc diagnoses** — named issues (e.g. cache pressure, slow disk, replication lag)
- [ ] **Export tier** — `tier1` vs richer export; do not assume full metric history is in bundle
- [ ] **Hatchet** — if `summary.json` exists, scan error spikes and slow-op patterns in the same windows

If tier-1 already answers a hypothesis, cite it in the report instead of asking the operator.
