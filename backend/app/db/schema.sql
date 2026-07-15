-- Production schema, phase 1 of the migration order in docs/PRODUCTION_ARCHITECTURE.md.
-- Applied idempotently by ensure_schema() at process startup when DATABASE_URL is set.
-- Later migration steps add: runs, job status, metrics, log_events, evidence JSONB,
-- phase2 state, raw_chunks.

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    job_type    TEXT NOT NULL,
    input_path  TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (state IN ('PENDING', 'PROCESSING')),
    claimed_by  TEXT,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at  TIMESTAMPTZ
);

-- claim_next scans PENDING in enqueue order; has_active_job_for_run filters by run.
CREATE INDEX IF NOT EXISTS jobs_state_enqueued_idx ON jobs (state, enqueued_at);
CREATE INDEX IF NOT EXISTS jobs_run_idx ON jobs (run_id);

-- Job lifecycle status shown to users (pending/running/succeeded/failed).
-- Distinct from `jobs`, which holds only the un-run queue tickets.
-- Timestamps are epoch floats to match JobStatus (time.time()) end to end.
CREATE TABLE IF NOT EXISTS job_status (
    job_id      TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    job_type    TEXT NOT NULL,
    state       TEXT NOT NULL
                CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    message     TEXT NOT NULL DEFAULT '',
    error       TEXT,
    input_path  TEXT,
    created_at  DOUBLE PRECISION NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS job_status_run_type_idx ON job_status (run_id, job_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS job_status_updated_idx ON job_status (updated_at DESC);

-- Decoded FTDC time series.  ts is milliseconds epoch (normalised on ingest).
-- Grafana /query reads this table; index covers (run, metric, window) lookups.
-- The composite PK's unique index already covers (run, metric, window) range scans;
-- no secondary index needed.
CREATE TABLE IF NOT EXISTS metrics (
    run_id  TEXT             NOT NULL,
    name    TEXT             NOT NULL,
    ts      DOUBLE PRECISION NOT NULL,
    value   DOUBLE PRECISION,
    PRIMARY KEY (run_id, name, ts)
);
DROP INDEX IF EXISTS idx_metrics_run_name_ts;

-- Analysis artefacts stored as JSONB keyed by (run_id, key).
-- Keys for ftdc pipeline run: manifest, executive_context, findings, anomaly_timeline,
--   activity_summary, assessment, formulas, bundle_index, validation, fallback_index.
-- Keys for hatchet run: hatchet_meta, hatchet_summary (single documents only;
--   row data lives in the typed hatchet_* tables below).
CREATE TABLE IF NOT EXISTS evidence (
    run_id  TEXT  NOT NULL,
    key     TEXT  NOT NULL,
    data    JSONB NOT NULL,
    PRIMARY KEY (run_id, key)
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence (run_id);

-- Phase 2 session state, one JSONB document per (run, llm, key).
-- Keys: report, investigation, iterative_state, budget, tool_trace, metadata,
--   chatbot, attachment:<stored_name>.  Replaces the phase2/llm/<llm>/ file tree.
-- updated_at is an epoch float to match time.time() end to end (like job_status).
CREATE TABLE IF NOT EXISTS phase2_state (
    run_id     TEXT NOT NULL,
    llm        TEXT NOT NULL,
    key        TEXT NOT NULL,
    data       JSONB NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, llm, key)
);
CREATE INDEX IF NOT EXISTS idx_phase2_state_run ON phase2_state (run_id);

-- Hatchet log analysis: full-fidelity copies of the hatchet.db SQLite tables,
-- one row per source row, every column preserved.  Filtering/sorting happens
-- at query time in SQL (same behaviour the tools had against SQLite).
-- Column names/types mirror simagix hatchet's schema exactly.

-- Every parsed MongoDB log line (source table: {name}).  Large: 1M+ rows per run.
CREATE TABLE IF NOT EXISTS hatchet_logs (
    run_id    TEXT NOT NULL,
    id        BIGINT,
    date      TEXT,
    severity  TEXT,
    component TEXT,
    context   TEXT,
    msg       TEXT,
    plan      TEXT,
    type      TEXT,
    ns        TEXT,
    message   TEXT,
    op        TEXT,
    filter    TEXT,
    _index    TEXT,
    milli     BIGINT,
    reslen    BIGINT,
    appname   TEXT,
    marker    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_hatchet_logs_run_milli ON hatchet_logs (run_id, milli DESC);
CREATE INDEX IF NOT EXISTS idx_hatchet_logs_run_severity ON hatchet_logs (run_id, severity);
CREATE INDEX IF NOT EXISTS idx_hatchet_logs_run_ns_op ON hatchet_logs (run_id, ns, op);

-- Aggregated slow-op stats (source table: {name}_ops).
CREATE TABLE IF NOT EXISTS hatchet_ops (
    run_id   TEXT NOT NULL,
    op       TEXT,
    count    BIGINT,
    avg_ms   DOUBLE PRECISION,
    max_ms   BIGINT,
    total_ms BIGINT,
    ns       TEXT,
    _index   TEXT,
    reslen   BIGINT,
    filter   TEXT,
    marker   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_hatchet_ops_run ON hatchet_ops (run_id);

-- Exception/failure counters (source table: {name}_audit).
CREATE TABLE IF NOT EXISTS hatchet_audit (
    run_id TEXT NOT NULL,
    type   TEXT,
    name   TEXT,
    value  BIGINT
);
CREATE INDEX IF NOT EXISTS idx_hatchet_audit_run_type_value ON hatchet_audit (run_id, type, value DESC);

-- Client connection rows (source table: {name}_clients).  Two source variants
-- exist (ip-based and date-based); both column sets are covered here.
CREATE TABLE IF NOT EXISTS hatchet_clients (
    run_id   TEXT NOT NULL,
    id       BIGINT,
    ip       TEXT,
    port     TEXT,
    date     TEXT,
    conns    BIGINT,
    accepted BIGINT,
    ended    BIGINT,
    context  TEXT,
    marker   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_hatchet_clients_run_ip ON hatchet_clients (run_id, ip);

-- Driver/version rows per client IP (source table: {name}_drivers).
CREATE TABLE IF NOT EXISTS hatchet_drivers (
    run_id  TEXT NOT NULL,
    id      BIGINT,
    ip      TEXT,
    driver  TEXT,
    version TEXT,
    marker  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_hatchet_drivers_run ON hatchet_drivers (run_id);

-- Operator-registered MCP connectors (http or stdio_template).
-- Replaces simagix-workspace/operator/mcp_connectors/registry.json.
CREATE TABLE IF NOT EXISTS mcp_connectors (
    id         TEXT PRIMARY KEY,
    data       JSONB NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

-- Operator-uploaded skills, stored as {relative_path: file_content} JSONB maps.
-- Replaces simagix-workspace/operator/skills/<slot>/ directories.
-- updated_at is epoch float.
CREATE TABLE IF NOT EXISTS skills (
    slot_name   TEXT PRIMARY KEY,
    files       JSONB NOT NULL,
    description TEXT,
    updated_at  DOUBLE PRECISION NOT NULL
);

-- Raw source bytes for FTDC + mongod log files, chunked into 8 MB BYTEA slices
-- so no single row is oversized. This is the durable source of truth for a run:
-- upload streams into raw_files first, worker pulls back onto ephemeral scratch,
-- retry re-materialises from PG. See docs/FTDC_DATA_FUNNEL.md §3.1.
CREATE TABLE IF NOT EXISTS raw_files (
    run_id    TEXT   NOT NULL,
    kind      TEXT   NOT NULL,       -- 'ftdc' | 'mongolog'
    filename  TEXT   NOT NULL,       -- e.g. metrics.2026-06-24T08-45-38Z-00000
    chunk_no  INT    NOT NULL,       -- 0-based slice index; ORDER BY to reassemble
    data      BYTEA  NOT NULL,       -- exactly one ~8 MB slice
    PRIMARY KEY (run_id, kind, filename, chunk_no)
);
CREATE INDEX IF NOT EXISTS idx_raw_files_run_kind ON raw_files (run_id, kind);

-- Per-file time window measured from decoded chunk headers at ingest.
-- Used by get_raw_window to pick the files that overlap an agent's window.
-- Timestamps are epoch seconds (float) to match simagix's ts convention.
CREATE TABLE IF NOT EXISTS raw_file_index (
    run_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    filename  TEXT NOT NULL,
    start_ts  DOUBLE PRECISION NOT NULL,
    end_ts    DOUBLE PRECISION NOT NULL,
    bytes     BIGINT NOT NULL,
    PRIMARY KEY (run_id, kind, filename)
);
CREATE INDEX IF NOT EXISTS idx_raw_file_index_window
    ON raw_file_index (run_id, kind, start_ts, end_ts);
