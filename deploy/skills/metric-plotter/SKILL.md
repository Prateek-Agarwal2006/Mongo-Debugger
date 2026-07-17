---
name: metric-plotter
description: Chart-generation playbook with the matplotlib code template to run via execute_plot_script — which metrics to plot, over what window, and where charts attach in the RCA report
---

# Metric Plotter — sandboxed chart code for RCA reports

This playbook is binding whenever the `execute_plot_script` tool is attached.
Every finding you report must be visually evidenced. You write the plotting
code; it executes in an isolated sandbox (never on the server). The server
gives your script `data.csv`; your script must produce `chart.png`.

## Required workflow (per finding)

1. Identify the 1–3 raw FTDC paths that best evidence the finding.
   Use `list_raw_paths(pattern)` to get exact path names — never guess paths.
2. Determine the plot window: the finding's anomaly window **±30 minutes** of
   padding (clamp to the run's full time range).
3. Adapt the code template below (title, anomaly shading, axis labels) and call
   `execute_plot_script(paths, start_ts, end_ts, script, finding_name)`.
   - It is budget-exempt — never skip it to save tool calls.
   - If it returns an error with `output_tail`, fix your script and call again.
4. Take the returned `chart_id` and:
   - set it on that finding's `finding_analyses[].chart_id` field, and
   - append `{chart_id, metric_paths, time_window, caption, finding_name}`
     to the report's `charts` array. The caption must say what the reader
     should see in the chart, in one sentence.

## Script contract

- Read `data.csv` from the working directory. Columns: `ts` (epoch seconds)
  plus one column per metric path. Cells may be empty (NaN after read_csv).
- Save the figure to `chart.png` in the working directory.
- matplotlib and pandas are preinstalled. No network, no database — only
  `data.csv` exists.

## Code template (adapt, don't rewrite from scratch)

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

LINE_COLORS = ("#2563eb", "#dc2626", "#059669", "#d97706")
TITLE = "Cache pressure during write stall 08:45-09:30Z"  # short, states what the chart proves
ANOMALY_START = None  # epoch seconds — set to shade the anomaly window
ANOMALY_END = None

df = pd.read_csv("data.csv")
df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)

fig, ax = plt.subplots(figsize=(9, 4.2), dpi=120)
for idx, col in enumerate(c for c in df.columns if c not in ("ts", "dt")):
    label = col.split("/")[-1]
    ax.plot(df["dt"], df[col], label=label, linewidth=1.4,
            color=LINE_COLORS[idx % len(LINE_COLORS)])

if ANOMALY_START and ANOMALY_END:
    ax.axvspan(pd.to_datetime(ANOMALY_START, unit="s", utc=True),
               pd.to_datetime(ANOMALY_END, unit="s", utc=True),
               alpha=0.12, color="#dc2626", label="anomaly window")

ax.set_title(TITLE, fontsize=11)
ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig("chart.png")
```

Customize per finding: shade the anomaly window with `axvspan`, use a second
y-axis (`ax.twinx()`) when plotting cause and effect on different scales
(e.g. write throughput vs replication lag seconds), and annotate the peak
with `ax.annotate` when a single spike is the evidence.

## Metric-family conventions

- **Cache / eviction findings**: plot `wiredTiger/cache` bytes-in-cache together
  with the eviction counters on one chart.
- **Ticket exhaustion**: plot read and write ticket availability on one chart.
- **Replication lag**: plot lag with the write throughput (opcounters) that
  drove it — two paths, one chart, twin axes.
- **CPU / IO findings**: plot the systemMetrics path with the affected latency
  or throughput metric so cause and effect are visible together.
- Maximum 4 series per chart; if more are relevant, render two charts.

## Rules

- No finding without a chart unless `execute_plot_script` returned an error
  after one retry — in that case record the error string in the finding's
  contributing_factors.
- Never fabricate a `chart_id`; only use ids returned by the tool.
- Do not chart metrics you have not verified exist via `list_raw_paths`.
- Do not attempt file, network, or subprocess operations in the script beyond
  reading data.csv and writing chart.png — the sandbox blocks them and the
  chart will fail.
