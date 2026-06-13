# Simagix Workspace

Local workspace for running the Simagix diagnostic toolchain and producing tiered evidence bundles for the Mongo Debugger RCA backend.

**Commands and troubleshooting:** [Operations](OPERATIONS.md)  
**Tool roles and Docker scripts:** [Simagix Toolchain](SIMAGIX_TOOLCHAIN.md)  
**Bundle schema:** [Export Contract](export_contract.md)

## Current status

| Component | Status |
|-----------|--------|
| mongo-ftdc Docker pipeline | Ready |
| Unified pipeline (`run_id` linking) | Ready |
| Tiered LLM export (`cmd/llm-export`) | Ready |
| RCA backend integration | Ready |
| Hatchet | Blocked — needs MongoDB logs |
| Keyhole / Maobi | Blocked — needs `MONGO_URI` and Keyhole output |

Latest validated export: `phase1test20260609T133314Z`. Full scorecard: [Project Status](PROJECT_STATUS.md).

The setup is hybrid: local repo clones for source review, Docker scripts for repeatable runs, generated data kept separate from source repos.

**Note:** upstream `mongo-ftdc` defaults to `-latest 10`. Our scripts default `MONGO_FTDC_LATEST=0` (all files).

## Cloned reference versions

| Repo | Remote | Commit |
|------|--------|--------|
| `mongo-ftdc` | `https://github.com/simagix/mongo-ftdc.git` | `66212fd` |
| `keyhole` | `https://github.com/simagix/keyhole.git` | `7d3a156` |
| `hatchet` | `https://github.com/simagix/hatchet.git` | `c109eed` |

## Folder layout

```text
simagix-workspace/
  repos/                    mongo-ftdc, keyhole, hatchet (source clones)
  data/
    diagnostic.data         symlink → ../../tmp/diagnostic.data
    mongodb-logs/           Hatchet input (when available)
    keyhole-output/         Keyhole output → Maobi input
    uploads/<run_id>/       Web upload staging
  exports/mongo-ftdc/       Tiered evidence bundles per run_id
  reports/mongo-ftdc/       Human HTML + console reports
  runs/<run_id>/            run_manifest.json, phase2 RCA state
  scripts/                  Docker wrappers (pipeline, Grafana, etc.)
```

## Why Docker is preferred

- Matches the Simagix documented workflow
- Avoids local Go build and Grafana dependency issues
- Repeatable report generation; same commands the backend upload job uses

Local clones remain useful for inspecting decode/assessment/diagnosis code and pinning exact versions.

## Input artifacts

### FTDC for mongo-ftdc

Default sample path (symlink, not a copy):

```text
simagix-workspace/data/diagnostic.data  →  tmp/diagnostic.data
```

Web uploads land under `simagix-workspace/data/uploads/<run_id>/diagnostic.data/`.

### Logs for Hatchet (blocked until provided)

```text
simagix-workspace/data/mongodb-logs/
```

Accepted: `mongod.log`, `mongod.log.gz`, `mongos.log`, `mongos.log.gz`. For self-managed MongoDB, discover path via `db.adminCommand({ getCmdLineOpts: 1 })` → `parsed.systemLog.path`. For Atlas, download logs from the Atlas UI.

### Cluster metadata for Keyhole (blocked until configured)

```bash
export MONGO_URI="mongodb+srv://user:password@cluster.example.mongodb.net/"
```

Output: `simagix-workspace/data/keyhole-output/` (input for Maobi).

## Pipeline scripts

| Script | Purpose |
|--------|---------|
| `run-mongo-ftdc.sh` | Human HTML + console report |
| `run-llm-export.sh` | Tiered evidence bundle |
| `run-mongo-ftdc-pipeline.sh` | Both with shared `run_id` |
| `run-grafana-stack.sh` | Grafana `:3030` + FTDC API `:5408` |

All require Docker. On Mac: `colima start --cpu 4 --memory 8` before running. See [Operations](OPERATIONS.md) for full command examples.

## Related source

| Path | Description |
|------|-------------|
| `repos/mongo-ftdc/cmd/llm-export/` | Go tiered exporter |
| `repos/mongo-ftdc/diagnosis.go` | Diagnosis engine (`DetectedAt` fix) |
| `backend/app/simagix/` | Python bundle loader and fallback tools |
