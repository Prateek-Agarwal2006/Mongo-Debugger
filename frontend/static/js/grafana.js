/** Open Grafana anomaly-focus + all-metrics dashboards (Postgres SimpleJSON). */

window.FtdcGrafana = {
  async init(runId) {
    const statusEl = document.getElementById("grafana-status");
    const anomalyBtn = document.getElementById("grafana-open-anomaly");
    const allBtn = document.getElementById("grafana-open-all");
    // Legacy single-button id still works if present.
    const legacyBtn = document.getElementById("grafana-open-btn");
    if (!runId) {
      if (statusEl) statusEl.textContent = "No run selected.";
      return;
    }

    let base = "http://localhost:3030";
    let anomaly = { uid: "simagix-grafana-anomaly", slug: "mongodb-ftdc-e28094-anomaly-focus" };
    let allMetrics = { uid: "simagix-grafana", slug: "mongodb-ftdc-analytics" };
    try {
      const cfg = await fetch("/grafana/simple/config").then((r) => r.json());
      if (cfg.url) base = String(cfg.url).replace(/\/$/, "");
      if (cfg.anomaly && cfg.anomaly.uid) anomaly = cfg.anomaly;
      if (cfg.all_metrics && cfg.all_metrics.uid) allMetrics = cfg.all_metrics;
    } catch {
      /* use defaults */
    }

    let fromMs = null;
    let toMs = null;
    let anomalyFrom = null;
    let anomalyTo = null;
    let hasAnomalies = false;
    try {
      const range = await fetch(
        `/grafana/simple/runs/${encodeURIComponent(runId)}/range`,
      ).then((r) => r.json());
      if (range.from != null && range.to != null) {
        fromMs = range.from;
        toMs = range.to;
      }
      if (range.anomaly_from != null && range.anomaly_to != null) {
        anomalyFrom = range.anomaly_from;
        anomalyTo = range.anomaly_to;
      }
      hasAnomalies = Boolean(range.has_anomalies);
    } catch {
      /* open without absolute range */
    }

    const buildUrl = (dash, fromVal, toVal) => {
      let url =
        `${base}/d/${encodeURIComponent(dash.uid)}/${encodeURIComponent(dash.slug)}` +
        `?orgId=1&var-run_id=${encodeURIComponent(runId)}`;
      if (fromVal != null && toVal != null) {
        url +=
          `&from=${encodeURIComponent(String(fromVal))}` +
          `&to=${encodeURIComponent(String(toVal))}`;
      }
      return url;
    };

    const anomalyUrl = buildUrl(
      anomaly,
      anomalyFrom != null ? anomalyFrom : fromMs,
      anomalyTo != null ? anomalyTo : toMs,
    );
    const allUrl = buildUrl(allMetrics, fromMs, toMs);

    if (statusEl) {
      if (fromMs == null) {
        statusEl.textContent =
          "No metrics ingested for this run yet — Grafana panels may be empty.";
      } else if (hasAnomalies) {
        statusEl.textContent =
          "Anomaly View zooms to scored windows; All Metrics shows the full capture.";
      } else {
        statusEl.textContent =
          "Charts read Postgres metrics. Both views open on this run's capture window.";
      }
    }

    const wire = (btn, url) => {
      if (!btn) return;
      btn.hidden = false;
      btn.classList.remove("hidden");
      btn.removeAttribute("disabled");
      btn.onclick = (event) => {
        event.preventDefault();
        window.open(url, "_blank", "noopener");
      };
    };

    wire(anomalyBtn, anomalyUrl);
    wire(allBtn, allUrl);
    wire(legacyBtn, allUrl);
  },
};
