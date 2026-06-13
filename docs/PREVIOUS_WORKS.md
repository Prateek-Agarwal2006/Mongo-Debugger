# Previous Works

## Purpose

This document studies prior MongoDB diagnostic work that is directly relevant to Mongo Debugger. It explains what Simagix and related tools already provide, what their benchmarks and adoption signals look like, how their AI-assisted workflow works, and what gaps remain for our product.

The goal is not to copy another tool. The goal is to understand the landscape well enough to make correct architecture decisions.

## Short Answer

Simagix has already built a strong **diagnostic toolchain**:

- `keyhole` collects cluster metadata, schema/index/storage stats, and historical diagnostic data.
- `maobi` converts Keyhole output into visual HTML reports.
- `hatchet` analyzes MongoDB logs, especially slow query and COLLSCAN patterns.
- `mongo-ftdc` decodes FTDC files, builds metric time series, scores health, runs diagnosis rules, and serves Grafana dashboards.
- NotebookLM is used as the external AI synthesis layer after reports are converted to PDFs.

They have **not** built the exact product we are building:

- not a single upload-based FastAPI web app;
- not an integrated LLM agent with metric tools;
- not a deterministic-plus-LLM RCA backend inside one application;
- not a product that asks for precise metric chunks and iteratively validates hypotheses;
- not a Mongo Debugger-specific report generator modeled after our RCA PDFs.

What they have built strongly validates our direction:

```text
structured diagnostic tools first
then AI reasoning on top
```

That is exactly the architecture Mongo Debugger should follow.

## Where The Whole Simagix Implementation Lives

There does not appear to be one single public monorepo that contains Keyhole, Maobi, Hatchet, and mongo-ftdc as one integrated product.

The Simagix implementation is a **toolset**, not one application:

```text
Simagix GitHub organization
  -> keyhole
  -> hatchet
  -> mongo-ftdc

Simagix Docker images
  -> simagix/keyhole
  -> simagix/hatchet
  -> simagix/ftdc
  -> simagix/grafana-ftdc
  -> simagix/maobi

AI layer
  -> NotebookLM, external to Simagix
```

### Source And Runtime Map

| Tool | Public source / runtime | What it contains | Notes |
| --- | --- | --- | --- |
| Keyhole | [GitHub: `simagix/keyhole`](https://github.com/simagix/keyhole/) and Docker image `simagix/keyhole` | MongoDB cluster collector, performance analytics, `-allinfo`, index/storage/schema stats, older FTDC/log analytics workflows. | This is the main collector for live cluster metadata. |
| Hatchet | [GitHub: `simagix/hatchet`](https://github.com/simagix/hatchet) and Docker image `simagix/hatchet` | MongoDB JSON log parser, SQLite-backed analysis, REST API, web UI, slow query/COLLSCAN analysis. | This is the main slow-log analysis tool. |
| mongo-ftdc | [GitHub: `simagix/mongo-ftdc`](https://github.com/simagix/mongo-ftdc) and Docker image `simagix/ftdc` | FTDC decoder, assessment scoring, diagnosis rules, HTML report, Grafana API server. | This is the closest prior work to our FTDC backend. |
| Grafana dashboard | Docker image `simagix/grafana-ftdc` | Preconfigured Grafana dashboards for `mongo-ftdc`. | Visualization layer, not RCA layer. |
| Maobi | Docker image [`simagix/maobi`](https://hub.docker.com/r/simagix/maobi) | Keyhole HTML report writer / visualizer. | I found Docker distribution and article references; I did not find a separate public Maobi GitHub source repo. |
| NotebookLM | [NotebookLM](https://notebooklm.google/) | External AI synthesis over uploaded reports/PDFs. | Not part of Simagix code. |
| WeasyPrint | [WeasyPrint](https://weasyprint.org/) | Converts HTML reports to PDFs. | Used as an ingestion workaround for NotebookLM. |

### Important Interpretation

The 2026 Simagix AI article describes an **integrated workflow**, not an integrated codebase.

The integration is done by file handoff:

```text
Keyhole output -> Maobi report
Hatchet output -> HTML/PDF report
mongo-ftdc output -> HTML/Grafana/diagnosis report
All reports -> WeasyPrint PDF conversion
PDFs -> NotebookLM
NotebookLM -> AI-assisted RCA summary
```

So if we want a product experience, Mongo Debugger still has work to do:

```text
instead of several tools plus manual report upload,
we build one backend that orchestrates decoding, assessment, retrieval, and RCA.
```

## What `collectAnomalies` Means

In Simagix `mongo-ftdc`, `collectAnomalies` is part of the `Diagnosis` engine. It scans already-decoded time-series metrics and creates an **anomaly timeline**.

An anomaly timeline means:

```text
At this time, this metric crossed this threshold for this duration.
```

That is very important for RCA because root cause is rarely visible from one metric. You need timing:

```text
Did read latency rise before CPU?
Did disk I/O wait rise before WiredTiger tickets dropped?
Did replication lag appear after write throughput spiked?
Did slow queries in logs happen during the same window as cache pressure?
```

### Inputs To `collectAnomalies`

`collectAnomalies` uses normalized metric time series already built by Simagix. Each metric has data points like:

```text
[value, timestamp_ms]
```

Examples:

- `latency_read`
- `latency_write`
- `latency_command`
- `scan_keys`
- `scan_objects`
- `cpu_idle`
- `cpu_iowait`
- `mem_page_faults`
- `q_queued_read`
- `q_queued_write`
- `write_conflicts/s`
- disk utilization per device
- replication lag per host

### Threshold Rules

The function defines thresholds for common bad states:

| Metric | Bad condition | Meaning |
| --- | --- | --- |
| `latency_read` | `> 20 ms` | Reads are slower than expected. |
| `latency_write` | `> 20 ms` | Writes are slower than expected. |
| `latency_command` | `> 20 ms` | Commands are slower than expected. |
| `scan_keys` | `> 100K/s` | Large key scan pressure. |
| `scan_objects` | `> 100K/s` | Large document scan pressure. |
| `cpu_idle` | `< 30%` | CPU headroom is low. |
| `cpu_iowait` | `> 15%` | Threads are waiting on storage. |
| `mem_page_faults` | `> 20/s` | Working set may not fit memory. |
| `q_queued_read` | `> 10` | Read operations are queueing. |
| `q_queued_write` | `> 10` | Write operations are queueing. |
| `write_conflicts/s` | `> 10/s` | Write contention or transaction conflict. |
| disk utilization | `> 70%` | Disk busy window. |
| replication lag | `> 5s` | Secondary is behind primary. |

### How It Groups Events

The collector does not just record every bad point. It groups adjacent bad points into ranges.

For a high-threshold metric:

```text
if value > threshold:
    continue or start anomaly range
else:
    close anomaly range
```

For a low-threshold metric like `cpu_idle`:

```text
if value < threshold:
    continue or start anomaly range
else:
    close anomaly range
```

Each range stores:

- start time;
- end time;
- duration;
- metric name;
- peak value;
- threshold label;
- severity.

### Minimum Duration Filter

Simagix filters out tiny blips. Only events lasting at least about `10 seconds` are added to the anomaly list.

That matters because FTDC is sampled frequently, and a one-sample spike may not be operationally meaningful. For RCA, we care about sustained or repeated pressure windows.

### Why This Matters For Mongo Debugger

This is a major idea we should reuse.

Raw metric summary:

```text
p95 cpu_iowait = 18%
```

Anomaly timeline:

```text
cpu_iowait exceeded 15% from 10:31:05 to 10:36:42.
read latency exceeded 20ms from 10:31:20 to 10:37:10.
write tickets dropped near the same interval.
```

The second form is much more useful for root cause.

For our app, the LLM should receive anomaly timelines first, then ask metric tools for deeper chunks around those windows.

## Simagix AI Diagnostics Workflow

The 2026 Simagix article, [MongoDB Diagnostics with AI: The Simagix Toolset and NotebookLM](https://www.simagix.com/2026/01/mongodb-diagnostics-with-ai-simagix.html), describes a workflow that combines Simagix diagnostic tools with NotebookLM.

The core problem it addresses is **correlation time**.

Without AI:

```text
DBA reads FTDC charts
DBA reads slow logs
DBA reads schema/index report
DBA manually correlates everything
```

With the Simagix workflow:

```text
tools generate structured reports
reports are converted to PDF
NotebookLM reads all reports
user asks investigation prompts
NotebookLM synthesizes findings
```

### Their Claimed Workflow

```mermaid
flowchart TD
  MongoCluster["MongoDB cluster"] --> Keyhole["Keyhole: collect cluster stats"]
  Keyhole --> Maobi["Maobi: visual HTML reports"]
  MongoLogs["mongod logs"] --> Hatchet["Hatchet: slow query and COLLSCAN analysis"]
  FTDCFiles["diagnostic.data"] --> MongoFTDC["mongo-ftdc: FTDC metrics and assessment"]
  Maobi --> PDFReports["PDF reports via WeasyPrint"]
  Hatchet --> PDFReports
  MongoFTDC --> PDFReports
  PDFReports --> NotebookLM["NotebookLM: AI synthesis"]
  NotebookLM --> HumanRCA["Human-reviewed RCA"]
```

### What They Have Already Built

They have built:

- collection of MongoDB cluster data through `keyhole`;
- report generation through `maobi`;
- log parsing through `hatchet`;
- FTDC metric decoding and assessment through `mongo-ftdc`;
- an AI-ready workflow that turns HTML reports into PDFs for NotebookLM;
- example prompts for executive summaries, query/hardware correlation, and index/schema strategy.

### What They Have Not Built

They have not built a single integrated RCA product. The workflow still depends on:

- running multiple CLI/Docker tools;
- managing directories manually;
- converting HTML to PDF with WeasyPrint;
- uploading PDFs into NotebookLM;
- asking prompts manually;
- human validation of the final reasoning.

That is powerful, but it is closer to an expert workflow than a product.

Mongo Debugger can improve this by making the workflow native:

```text
upload FTDC
decode metrics
run assessment
parse available logs if provided
retrieve relevant docs
ask metric tools for chunks
generate RCA report
show evidence and charts
```

## Where To Get Each Required Input File

This section is the practical collection guide: what file each tool needs, where that file normally lives, and how to collect it.

### Quick Input Matrix

| Tool | Required input | Where it comes from | Typical path or command |
| --- | --- | --- | --- |
| `mongo-ftdc` | FTDC `diagnostic.data` directory containing `metrics.*` files | Local MongoDB host or Atlas diagnostics download | `storage.dbPath/diagnostic.data` for `mongod`; `mongos.diagnostic.data` near `systemLog.path` for `mongos`; Atlas UI download diagnostics. |
| `hatchet` | MongoDB log file, usually `mongod.log` or `mongod.log.gz` | Local MongoDB host, Atlas log download, S3, URL | `systemLog.path`, commonly `/var/log/mongodb/mongod.log` on Linux. |
| `keyhole` | MongoDB connection string, not a pre-existing file | Live MongoDB deployment | `MONGO_URI="mongodb+srv://..."` then `keyhole -allinfo "$MONGO_URI" -obfuscate`. |
| `maobi` | Keyhole output file | Generated by Keyhole | File produced in the working directory after `keyhole -allinfo`; pass it to `maobi`. |
| NotebookLM | PDF reports | Generated from Maobi/Hatchet/mongo-ftdc reports | Convert HTML reports to PDF using WeasyPrint. |

### First: Discover Paths From MongoDB Itself

For self-managed MongoDB, do not guess paths. Ask the running server:

```javascript
db.adminCommand({ getCmdLineOpts: 1 })
```

Look for:

```text
parsed.storage.dbPath
parsed.systemLog.path
```

Those two values tell you where the database files and logs are configured.

Example output shape:

```json
{
  "parsed": {
    "storage": {
      "dbPath": "/var/lib/mongodb"
    },
    "systemLog": {
      "path": "/var/log/mongodb/mongod.log"
    }
  }
}
```

Then:

```text
FTDC path = /var/lib/mongodb/diagnostic.data
Log path  = /var/log/mongodb/mongod.log
```

### FTDC Files For `mongo-ftdc`

FTDC files are the main input for `mongo-ftdc` and for our Mongo Debugger app.

MongoDB stores them as binary files named like:

```text
metrics.2026-01-01T10-00-00Z-00000
metrics.2026-01-01T10-00-00Z-00001
```

They live inside a folder named:

```text
diagnostic.data
```

#### Self-Managed `mongod`

For a `mongod` process, MongoDB stores FTDC under:

```text
<storage.dbPath>/diagnostic.data
```

Common examples:

```text
/var/lib/mongodb/diagnostic.data
/var/lib/mongo/diagnostic.data
/data/db/diagnostic.data
/usr/local/var/mongodb/diagnostic.data
/opt/homebrew/var/mongodb/diagnostic.data
```

The exact path depends on `storage.dbPath`.

#### Self-Managed `mongos`

For a `mongos` process, FTDC is relative to the log path.

If:

```text
systemLog.path = /var/log/mongodb/mongos.log
```

then FTDC is stored at:

```text
/var/log/mongodb/mongos.diagnostic.data
```

This matters in sharded clusters because `mongos` diagnostics are not under `storage.dbPath`.

#### MongoDB Atlas

For Atlas, you normally do not SSH into the host. Download diagnostics from the Atlas UI:

```text
Atlas UI -> Clusters -> target cluster -> ... menu -> Download Diagnostics
```

The downloaded archive should contain a `diagnostic.data` directory or `metrics.*` files.

#### Copying FTDC For Simagix

For Simagix `mongo-ftdc`, create or use a local folder:

```bash
mkdir -p ./diagnostic.data
cp /path/to/original/diagnostic.data/metrics.* ./diagnostic.data/
```

In our current project workspace, the real local sample is:

```text
tmp/diagnostic.data
```

Then run:

```bash
./dist/mftdc ./diagnostic.data/
```

or Docker:

```bash
docker run --rm -v "$(pwd)":/home/simagix simagix/ftdc /mftdc diagnostic.data/
```

#### Critical Timing Note

MongoDB rotates FTDC data. Capture the `diagnostic.data` directory as close to the incident as possible. If MongoDB purges old files, the incident window may be lost.

### MongoDB Logs For `hatchet`

Hatchet needs MongoDB JSON logs.

The best input is:

```text
mongod.log
mongod.log.gz
mongos.log
mongos.log.gz
```

#### Self-Managed Linux

Common path:

```text
/var/log/mongodb/mongod.log
```

But the exact path is:

```text
parsed.systemLog.path
```

from:

```javascript
db.adminCommand({ getCmdLineOpts: 1 })
```

#### macOS Homebrew

Common paths vary by Intel vs Apple Silicon and install method:

```text
/usr/local/var/log/mongodb/mongo.log
/usr/local/var/log/mongodb/mongod.log
/opt/homebrew/var/log/mongodb/mongo.log
/opt/homebrew/var/log/mongodb/mongod.log
```

Again, prefer `getCmdLineOpts` or the config file over guessing.

Common config files:

```text
/usr/local/etc/mongod.conf
/opt/homebrew/etc/mongod.conf
```

#### Windows

The log path is configured in `mongod.cfg`.

Common config file location:

```text
C:\Program Files\MongoDB\Server\<version>\bin\mongod.cfg
```

Common log examples:

```text
C:\Program Files\MongoDB\Server\<version>\log\mongod.log
C:\data\log\mongod.log
```

Use:

```javascript
db.adminCommand({ getCmdLineOpts: 1 })
```

to find the actual value.

#### MongoDB Atlas

For Atlas logs:

```text
Atlas UI -> Clusters -> target cluster -> Logs / Download Logs
```

Hatchet can also read Atlas logs by URL/API credentials according to its README, using digest authentication. The exact Atlas API URL depends on project, cluster, and host.

#### Running Hatchet

Local file:

```bash
./dist/hatchet -server /path/to/mongod.log.gz
```

Multiple files:

```bash
./dist/hatchet -server rs1/mongod.log rs2/mongod.log rs3/mongod.log
```

Merged analysis:

```bash
./dist/hatchet -server -merge rs1/mongod.log rs2/mongod.log rs3/mongod.log
```

Docker-style workflow:

```bash
mkdir -p ./mongodb
cp /path/to/mongod.log.gz ./mongodb/
docker run --rm -v "$(pwd)":/home/simagix simagix/hatchet /hatchet -report mongodb/
```

### Cluster Metadata For `keyhole`

Keyhole does not start from a local diagnostic file. It connects to a live MongoDB deployment.

The required input is:

```text
MongoDB connection string
```

Example:

```bash
export MONGO_URI="mongodb+srv://user:password@cluster.example.mongodb.net/"
```

Then:

```bash
docker run --rm -v "$(pwd)":/home/simagix simagix/keyhole \
  /keyhole -allinfo "$MONGO_URI" -obfuscate
```

or from a locally built Keyhole binary:

```bash
./dist/keyhole -allinfo "$MONGO_URI" -obfuscate
```

Keyhole generates an output file in the current working directory. Public examples show compressed JSON/BSON-style report artifacts, commonly with names like:

```text
<host>.json.gz
keyhole_stats.<timestamp>.gz
```

The exact name depends on the command and Keyhole version.

That generated file is the input for Maobi.

### Report Input For `maobi`

Maobi consumes the output from Keyhole.

Typical flow:

```text
Keyhole connects to MongoDB
Keyhole writes compressed report file
Maobi reads that report file
Maobi writes HTML report
```

Docker command pattern from the Simagix workflow:

```bash
docker run --rm -v "$(pwd)":/home/simagix simagix/maobi \
  /maobi {keyhole-output-filename}
```

Example:

```bash
docker run --rm -v "$(pwd)":/home/simagix simagix/maobi \
  /maobi host.example.mongodb.net.json.gz
```

The output is an HTML diagnostic report.

### PDF Inputs For NotebookLM

NotebookLM is not reading FTDC directly in the Simagix workflow. It reads generated reports.

Inputs:

```text
Maobi HTML report
Hatchet HTML report
mongo-ftdc HTML report
```

Convert HTML to PDF:

```bash
brew install weasyprint
cd html
for f in *.html; do
  weasyprint "$f" "${f%.html}.pdf"
done
cd ..
```

Then upload PDFs to NotebookLM.

### Recommended Local Folder Layout

Use this layout when collecting incident artifacts:

```text
incident-case/
  diagnostic.data/
    metrics.*
  mongodb/
    mongod.log
    mongod.log.gz
    mongos.log.gz
  keyhole/
    keyhole-output.json.gz
  maobi/
    maobi-report.html
  hatchet/
    hatchet-report.html
  mongo-ftdc/
    ftdc_diagnosis.html
  pdf/
    maobi-report.pdf
    hatchet-report.pdf
    ftdc_diagnosis.pdf
```

### Mapping Inputs To RCA Questions

| Artifact | Answers |
| --- | --- |
| `diagnostic.data/metrics.*` | What happened over time: CPU, disk, WT cache, tickets, queues, replication lag. |
| `mongod.log` / `mongos.log` | Which queries, clients, namespaces, and errors occurred during the incident. |
| Keyhole output | What the cluster/schema/index/storage configuration looked like. |
| Maobi report | Human-readable cluster and schema health summary. |
| Hatchet report | Slow query patterns, COLLSCANs, operation distribution, log evidence. |
| mongo-ftdc report | Metric assessment, anomaly timeline, suspected bottleneck categories. |

### Minimum Artifact Set For Mongo Debugger

For our first FTDC-only web app:

```text
required:
  diagnostic.data/

optional later:
  mongod.log or mongod.log.gz
  keyhole output
  maobi report
  hatchet report
```

For Claude/NotebookLM-style deep RCA:

```text
best:
  diagnostic.data/
  mongod.log.gz
  keyhole -allinfo output
  maobi report
  hatchet report
```

## Does Simagix Already Solve Our Goal?

Partially.

It solves:

- FTDC visualization;
- metric assessment;
- broad health scoring;
- some diagnosis rules;
- Grafana dashboards;
- report generation;
- log analysis when Hatchet is used;
- cluster/schema/index context when Keyhole and Maobi are used;
- AI synthesis through NotebookLM.

It does not fully solve:

- integrated upload-to-RCA web app;
- LLM tool-calling over metric chunks;
- structured hypothesis testing;
- deterministic evidence model inside the app;
- RCA-style report with explicit causal chain, ruled-out hypotheses, and safe fixes;
- direct API contract for our backend;
- long-term storage and queue-based processing;
- product-specific UX for MongoDB incidents.

Therefore, the conclusion is:

```text
Simagix proves the method.
Mongo Debugger should productize and specialize it.
```

## Benchmark Evidence For `mongo-ftdc`

### Public Release Claim

The strongest benchmark evidence found is the GitHub release note for [`mongo-ftdc` v1.2.1](https://github.com/simagix/mongo-ftdc/releases/tag/v1.2.1).

The release is titled:

```text
v1.2.1: 9x Faster Loading & MongoDB 7.0+ Metrics
```

The release body claims:

- `9x faster` file loading;
- `1.6s -> 0.17s per file`;
- `66% fewer` memory allocations;
- single-pass processing for all ServerStatus metrics;
- pre-cached disk keys;
- elimination of `250M+` string operations;
- fixed race condition in parallel file reading.

### What This Means Technically

The claim is plausible based on the source code changes we reviewed:

- files are loaded in parallel;
- compressed FTDC blocks are processed in parallel;
- final slices are pre-allocated;
- serverStatus metrics are processed in a single pass;
- disk keys are parsed once and cached;
- string path scans are reduced.

These are real performance optimizations.

### What Is Not Publicly Proven

The release note does not publish:

- hardware specs;
- data size;
- number of FTDC files;
- MongoDB version;
- benchmark command;
- before/after commit IDs;
- repeat count;
- variance;
- comparison against `pyftdc`;
- comparison against MongoDB's official `ftdc` tool.

So we should call it:

```text
a credible release benchmark claim
```

not:

```text
independently verified industry benchmark
```

### What We Should Do

We should benchmark it ourselves on our real sample:

```text
tmp/diagnostic.data
```

Minimum benchmark table:

| Decoder | Input size | Files | Runtime | Peak memory | Output metrics | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| current `pyftdc` path | TBD | TBD | previously about 39 minutes | TBD | selected metrics | Sequential and Python-heavy. |
| `mongo-ftdc` CLI | `tmp/diagnostic.data` | `25` | about `21s` load time in local Docker run | about `1.2-2.4 GiB` Go heap during load logs | assessment + HTML + normalized metrics | Local run used `-latest 0` to process all files. |
| MongoDB `ftdc dump` | TBD | TBD | to measure | TBD | raw JSON dump | Official ecosystem baseline. |

### Local Validation Result

On the provided `tmp/diagnostic.data` sample, the local Docker-based `mongo-ftdc` run loaded all `25` files when called with `-latest 0`.

Observed decoder log:

```text
25 files loaded, time spent: 20.605937814s
Stats from 2026-06-02T17:29:03Z to 2026-06-03T10:26:44Z
```

This validates that Simagix's Go loader is much more practical for our sample than the earlier Python-only path.

Important caveat:

```text
mongo-ftdc defaults to -latest 10.
```

That is why the first HTML report only loaded 10 files. It was not a data availability issue; it was the tool's default file-selection behavior. For Mongo Debugger evidence generation, use `-latest 0` unless the user explicitly asks for a recent-window-only analysis.

### Local Structured Export

The public Simagix workflow produces console, HTML, Grafana API, and optional PDF outputs. Those are useful, but they are not the ideal LLM input.

For Mongo Debugger, we added a local exporter in the cloned `mongo-ftdc` repo:

```text
simagix-workspace/repos/mongo-ftdc/cmd/llm-export
```

Run it through:

```bash
./simagix-workspace/scripts/run-llm-export.sh
```

It exports:

- raw decoder `DataPointsMap` values;
- normalized Simagix time-series data;
- serverStatus, systemMetrics, and replSetStatus decoded streams;
- disk and replication-lag derived series;
- assessment score tables and formula thresholds;
- diagnosis findings, activity summary, and anomaly timeline;
- small LLM entrypoint files for chunk retrieval.

This is not upstream Simagix behavior. It is our local bridge between Simagix prior art and Mongo Debugger's planned LLM RCA backend.

## Public Adoption Signals

Public adoption signals are mixed but useful.

### `mongo-ftdc`

From GitHub metadata:

- around `40` stars;
- around `19` forks;
- around `6` subscribers/watchers depending on API field;
- created in 2019;
- active updates through January 2026;
- Apache-2.0 license;
- Go implementation;
- used by or split out from Keyhole.

This is modest adoption, but meaningful for a specialized FTDC tool.

### `keyhole`

From GitHub metadata and MongoDB blog posts:

- around `392` stars;
- around `66` forks;
- around `18` subscribers;
- created in 2018;
- multiple contributors;
- MongoDB blog series exists for Keyhole usage;
- used as the older umbrella tool that included FTDC analytics.

This is a stronger adoption signal.

### `hatchet`

From GitHub metadata and README:

- around `245` stars;
- around `34` forks;
- around `12` subscribers;
- created in 2022;
- active updates through January 2026;
- provides REST API and web UI;
- supports local files, URLs, S3, and Atlas logs.

This is also a strong signal for a MongoDB log analysis niche tool.

### `maobi`

From Docker Hub search results:

- Docker image `simagix/maobi`;
- described as `simagix/keyhole HTML reports writer`;
- reported as `500K+` pulls in Docker Hub snippet;
- latest tags around version `1.9.x`;
- used as the report generator for Keyhole output.

Docker pull count is a stronger usage signal than stars, but it still does not prove active production use.

### Third-Party Mentions

Relevant public mentions:

- MongoDB company blog posts by Ken Chen explaining Keyhole, Maobi, FTDC charts, and scoring.
- [Mydbops article](https://www.mydbops.com/blog/mongodbs-ftdc-a-powerful-tool-for-performance-monitoring-and-troubleshooting) showing how to visualize FTDC data with `simagix/mongo-ftdc`.
- [Percona article](https://www.percona.com/blog/enhancing-keyhole-pulling-more-metrics-from-mongodbs-ftdc/) stating they had used Keyhole and then built additional FTDC metric extraction based on the same idea.

These are meaningful references, but they are not formal product reviews.

## Reviews And Reputation

There are no broad public review pages like a SaaS product would have.

What exists:

- GitHub stars and forks;
- Docker pulls for Maobi;
- author blog posts;
- MongoDB blog series;
- third-party tutorials;
- Percona acknowledgement of using Keyhole;
- public source code;
- open-source activity.

Interpretation:

```text
The Simagix ecosystem is credible and used by MongoDB practitioners,
but mongo-ftdc itself remains a specialized open-source utility with modest public footprint.
```

For our project, this is enough to treat Simagix as serious prior art, not enough to blindly rely on every threshold or diagnosis as absolute truth.

## Keyhole

### What Keyhole Is

[`keyhole`](https://github.com/simagix/keyhole/) is a MongoDB performance analytics and cluster exploration tool.

The MongoDB blog describes it as a way to quickly collect MongoDB cluster statistics and produce performance analytics summaries. It collects information about:

- MongoDB configuration;
- cluster statistics;
- database schema;
- collections;
- indexes;
- index usage;
- storage size;
- memory;
- CPU and disk signals through diagnostic data;
- slow operation information when logs are included.

### What Keyhole Can Do

Keyhole supports:

- installation validation;
- load tests;
- connection sanity checks;
- cluster health checks;
- collection of `buildInfo`, `getCmdLineOpts`, `hostInfo`, `replSetGetStatus`, `rolesInfo`, `serverStatus`, and users info;
- database and collection stats;
- index redundancy detection;
- index usage review;
- FTDC reading through diagnostic data;
- Grafana integration in earlier workflows;
- log summaries in earlier workflows.

### Why Keyhole Matters To Us

FTDC alone does not include everything. RCA often needs:

- schema shape;
- collection sizes;
- index sizes;
- index usage;
- duplicate indexes;
- unused indexes;
- sharding/replica information;
- database configuration.

Keyhole is relevant because it collects these non-FTDC facts.

For Mongo Debugger:

```text
FTDC explains what happened over time.
Keyhole-style metadata explains whether the cluster/schema/index design made that likely.
```

### Example RCA Use

If FTDC shows:

```text
high scan_objects
high CPU user
read latency spike
```

Keyhole/Maobi context can answer:

```text
which collections have large data/index size?
are indexes missing, duplicated, or unused?
does index size exceed RAM?
```

## Maobi

### What Maobi Is

`maobi` is the report visualizer for Keyhole output.

The Simagix AI article describes it as:

```text
The Visualizer
```

It transforms compressed BSON statistics from Keyhole into multi-dimensional diagnostic reports.

### What Maobi Reports

Based on the public docs and articles, Maobi provides:

- cluster configuration summaries;
- collection-level statistics;
- schema health indicators;
- storage fragmentation indicators;
- oversized document indicators;
- index-to-data ratio indicators;
- index duplication/usage context;
- HTML reports that can be shared or converted to PDF.

### How Maobi Fits The AI Workflow

Maobi produces structured HTML reports. The 2026 workflow converts those reports to PDF using WeasyPrint so NotebookLM can read them.

```text
Keyhole output -> Maobi HTML -> WeasyPrint PDF -> NotebookLM
```

### Why Maobi Matters To Us

Maobi teaches an important product lesson:

```text
LLMs reason better over structured reports than raw database dumps.
```

For Mongo Debugger, we can generate structured internal summaries instead of forcing the LLM to read raw decoded data.

## Hatchet

### What Hatchet Is

[`hatchet`](https://github.com/simagix/hatchet) is a MongoDB JSON log analyzer and viewer.

Its README describes it as a log processing, aggregation, storage, REST API, and web UI tool using embedded SQLite.

### What Hatchet Can Analyze

Hatchet can help with:

- slow query patterns;
- COLLSCAN operations;
- operation counts;
- average operation time;
- connection patterns;
- namespace-level activity;
- response sizes;
- client/IP distribution;
- audit data;
- log search;
- report download;
- REST API integration.

### Data Sources

Hatchet supports:

- local MongoDB log files;
- compressed logs;
- multiple log files;
- merged analysis;
- URLs;
- S3;
- MongoDB Atlas log download through API credentials.

### Why Hatchet Matters To RCA

FTDC tells you symptoms:

```text
read latency increased
CPU idle dropped
cache pressure rose
```

Logs tell you actors:

```text
this query shape was slow
this namespace had COLLSCAN
this command produced large responses
this client created many connections
```

A strong RCA needs both.

### Relation To Mongo Debugger

Mongo Debugger started FTDC-first, but long term it should optionally accept logs too.

Possible future upload types:

```text
diagnostic.data/
mongod.log
mongod.log.gz
keyhole report
hatchet report
maobi report
```

The LLM can then correlate:

```text
slow query windows from Hatchet
with FTDC pressure windows from mongo-ftdc
```

## mongo-ftdc

### What mongo-ftdc Is

[`mongo-ftdc`](https://github.com/simagix/mongo-ftdc) is the FTDC metric decoder, assessment engine, diagnosis tool, API server, and Grafana datasource from Simagix.

It supports:

- CLI diagnosis;
- HTML diagnosis report;
- Docker-based Grafana dashboards;
- HTTP API for Grafana;
- assessment scoring;
- diagnosis rules;
- obfuscation;
- MongoDB 7+ metrics such as queues/admission control, transactions, tcmalloc, and flow control.

### Why It Is Important

This is the closest prior work to Mongo Debugger's FTDC layer.

It already does several things we planned:

- decode FTDC;
- normalize important metrics;
- compute p5/median/p95;
- score metrics;
- identify issue categories;
- generate anomaly timeline;
- serve chart data;
- generate report output.

### Where It Stops

It does not deeply reason like a senior DBA.

It can say:

```text
Disk I/O bottleneck
```

But our desired report should say:

```text
Disk I/O wait rose first, then write tickets exhausted, then read latency rose.
The likely cause is checkpoint/writeback saturation rather than missing indexes,
because scan metrics stayed normal and write throughput spiked during the same window.
```

That second statement requires multi-metric reasoning and hypothesis checking.

## NotebookLM

### What NotebookLM Is In This Workflow

NotebookLM is the AI reading layer. Simagix uses it by uploading PDFs generated from structured diagnostic reports.

The article recommends prompts such as:

- act as a Senior MongoDB DBA;
- identify the single biggest bottleneck;
- cross-reference Hatchet slow queries with FTDC metrics;
- identify collections with fragmentation and suggest missing indexes.

### What NotebookLM Provides

NotebookLM provides:

- multi-document synthesis;
- natural-language querying;
- source-grounded summarization;
- correlation across reports;
- a lightweight AI analyst workflow.

### Why NotebookLM Is Not Our Backend

NotebookLM is not programmable enough for our app's backend needs:

- no direct metric tool loop;
- no local queue integration;
- no typed API contract;
- no native FTDC upload workflow;
- no deterministic storage/query layer;
- no custom RCA scoring model;
- no application-specific UI.

But the principle is very valuable:

```text
turn diagnostic outputs into structured documents
then let an LLM synthesize them
```

## WeasyPrint

### What WeasyPrint Does

[WeasyPrint](https://weasyprint.org/) converts HTML/CSS into PDF.

In the Simagix workflow, it is used because NotebookLM does not natively consume HTML reports as cleanly as PDFs.

Workflow:

```text
HTML reports -> WeasyPrint -> PDFs -> NotebookLM
```

### Why It Matters

This is a workaround for AI ingestion.

For Mongo Debugger, we may not need WeasyPrint internally because our app can pass structured JSON and summaries directly to the LLM.

However, we may still use PDF export for:

- user-facing RCA report download;
- sharing with teams;
- attaching to tickets;
- compliance/archive.

## Adjacent FTDC Prior Work

### MongoDB `ftdc-tools`

[`mongodb/ftdc-tools`](https://github.com/mongodb/ftdc-tools) is a pure Python FTDC library. Public docs describe it as beta and mainly used for Genny/Poplar client-side FTDC, not necessarily fully tested against MongoDB server FTDC.

Relevance:

- useful to know;
- not currently the strongest choice for our server FTDC use case;
- may be useful as a streaming design reference.

### `mongo-ftdc-v2`

[`mongo-ftdc-v2`](https://github.com/ajithkn716/mongo-ftdc-v2) decodes FTDC and sends metrics to InfluxDB/Grafana.

It emphasizes:

- decoding all available metrics;
- InfluxDB storage;
- Dockerized deployment;
- configurable parallel workers;
- Grafana dashboards.

Relevance:

- useful alternative architecture;
- focuses on visualization and metric storage;
- does not appear to provide the same Simagix assessment/diagnosis layer.

### Big-hole

`Big-hole` is another community project for FTDC metrics and Grafana/InfluxDB-style visualization.

Relevance:

- confirms repeated community need for FTDC visualization;
- not enough as RCA engine.

### Percona FTDC Extension Work

The [Percona article](https://www.percona.com/blog/enhancing-keyhole-pulling-more-metrics-from-mongodbs-ftdc/) says they had been using Keyhole and wrote a script based on the same idea to pull more FTDC metrics for customer investigations.

This is important because it is an independent practitioner signal:

```text
FTDC visualization is useful,
but real troubleshooting often needs more metrics and custom analysis.
```

That supports our decision to make metric extraction extensible.

## Comparison: Simagix Workflow vs Mongo Debugger

| Area | Simagix Workflow | Mongo Debugger Goal |
| --- | --- | --- |
| Input | Multiple tools and directories. | Single upload workflow first, optional logs later. |
| FTDC decode | `mongo-ftdc` Go decoder. | Swappable decoder backend. |
| Metric storage | In-memory/server response for Grafana. | DuckDB/local store now, scalable store later. |
| Assessment | Built-in scoring formulas. | Reuse/port scoring plus app-specific evidence model. |
| Diagnosis | Rule-based issue categories. | Candidate findings plus LLM RCA. |
| AI | NotebookLM over PDFs. | Integrated LLM agent with metric tools. |
| Charts | Grafana dashboards. | Optional chart UI, not required for RCA. |
| Logs | Hatchet separately. | Optional future upload and correlation. |
| Schema/index context | Keyhole/Maobi separately. | Optional future metadata report ingestion. |
| Report | Console/HTML/PDF then NotebookLM. | Final RCA report generated directly. |

## What We Should Reuse

### Reuse Directly Or Closely

- p5/median/p95 scoring model;
- metric health score table;
- anomaly timeline idea;
- query targeting ratios;
- replication lag derivation;
- CPU and disk delta formulas;
- dynamic disk metric extraction;
- Simagix diagnosis categories as initial playbooks;
- obfuscation ideas;
- optional Grafana advanced mode.

### Reuse As Inspiration

- Keyhole's cluster metadata collection;
- Maobi's structured report style;
- Hatchet's slow query pattern grouping;
- NotebookLM's multi-document synthesis workflow;
- WeasyPrint-style PDF export.

### Do Not Blindly Reuse

- thresholds without validation;
- generic remediation suggestions;
- any diagnosis as final RCA;
- Grafana as required UX;
- PDF upload as internal LLM interface.

## What Mongo Debugger Should Add

### Integrated Agent Loop

Mongo Debugger should make the LLM an active analyst:

```mermaid
flowchart TD
  Assessment["Assessment findings"] --> Agent["RCA agent"]
  Agent --> AskMetrics["Ask for focused metric chunks"]
  AskMetrics --> MetricStore["Metric store"]
  MetricStore --> Evidence["Evidence windows"]
  Evidence --> Agent
  Agent --> RetrieveDocs["Retrieve MongoDB and OS docs"]
  RetrieveDocs --> Agent
  Agent --> TestHypotheses["Test and rule out hypotheses"]
  TestHypotheses --> Report["Final RCA report"]
```

### Causal Chain

The report should explain sequence:

```text
first signal -> dependent signal -> user-visible impact
```

Example:

```text
Disk utilization plateaued first.
CPU iowait rose next.
Write tickets then exhausted.
Read and write latency increased after tickets were consumed.
```

### Ruled-Out Hypotheses

A professional RCA should include:

```text
Not likely missing indexes because query targeting stayed normal.
Not likely connection storm because conns_current and conns_created/s stayed flat.
Not likely CPU-only bottleneck because iowait dominated user CPU.
```

### Safe Fixes

Suggestions must be ranked:

1. safe immediate mitigation;
2. short-term validation;
3. long-term fix;
4. risky actions requiring maintenance window.

## Final Assessment Of Prior Work

The Simagix ecosystem is the most relevant prior work found.

It already proves:

- FTDC can be decoded locally;
- Grafana can visualize it well;
- p5/median/p95 scoring is useful;
- diagnosis rules can identify common MongoDB bottleneck categories;
- multiple diagnostic reports can be synthesized by AI.

It does not eliminate our project. It clarifies what our project should become:

```text
not just another FTDC decoder
not just another Grafana dashboard
not just raw LLM over PDFs

but a focused MongoDB RCA product with:
  deterministic evidence,
  fast metric retrieval,
  guided LLM reasoning,
  cited domain knowledge,
  and actionable reports.
```

## Recommended Next Steps

1. Benchmark `mongo-ftdc` on our `tmp/diagnostic.data`.
2. Save its console diagnosis and HTML report as comparison artifacts.
3. Compare its detected issues with our current RCA rules.
4. Decide whether to call `mongo-ftdc` as an external decoder/assessment service.
5. Add Simagix-style assessment scores to our backend.
6. Extend our LLM metric tools around anomaly windows.
7. Later, support optional log upload and Hatchet-style slow query correlation.

## Source Links

- [Simagix mongo-ftdc GitHub](https://github.com/simagix/mongo-ftdc)
- [mongo-ftdc v1.2.1 release note](https://github.com/simagix/mongo-ftdc/releases/tag/v1.2.1)
- [Simagix AI diagnostics article](https://www.simagix.com/2026/01/mongodb-diagnostics-with-ai-simagix.html)
- [Simagix Keyhole GitHub](https://github.com/simagix/keyhole/)
- [Simagix Hatchet GitHub](https://github.com/simagix/hatchet)
- [Simagix GitHub profile](https://github.com/simagix)
- [Simagix Maobi Docker image](https://hub.docker.com/r/simagix/maobi)
- [MongoDB Keyhole Part 1](https://www.mongodb.com/company/blog/peek-at-your-mongodb-clusters-like-a-pro-with-keyhole-part-1)
- [MongoDB Keyhole Part 2](https://www.mongodb.com/company/blog/peek-at-your-mongodb-clusters-like-a-pro-with-keyhole-part-2)
- [MongoDB Keyhole Part 3](https://www.mongodb.com/company/blog/peek-your-clusters-like-pro-with-keyhole-part-3)
- [MongoDB FTDC documentation](https://www.mongodb.com/docs/v8.2/administration/full-time-diagnostic-data-capture/)
- [MongoDB configuration options](https://www.mongodb.com/docs/manual/reference/configuration-options/)
- [Hatchet blog](https://www.simagix.com/2023/07/hatchet-empowering-smart-mongodb-log.html)
- [Survey Your Mongo Land with Keyhole and Maobi](https://www.simagix.com/2023/08/survey-your-mongo-land-with-keyhole-and.html)
- [Mydbops FTDC visualization article](https://www.mydbops.com/blog/mongodbs-ftdc-a-powerful-tool-for-performance-monitoring-and-troubleshooting)
- [Percona FTDC/Keyhole article](https://www.percona.com/blog/enhancing-keyhole-pulling-more-metrics-from-mongodbs-ftdc/)
- [mongodb/ftdc-tools](https://github.com/mongodb/ftdc-tools)
- [mongo-ftdc-v2](https://github.com/ajithkn716/mongo-ftdc-v2)
- [WeasyPrint](https://weasyprint.org/)
