window.FtdcGrafana = {
  async init(runId) {
    const statusEl = document.getElementById('grafana-status');
    const loadBtn = document.getElementById('grafana-load-btn');

    try {
      const status = await fetch('/simagix/runs/grafana/status').then((r) => r.json());
      if (status.grafana && status.ftdc_api) {
        statusEl.textContent =
          'Grafana stack is running. Open charts in a new tab, or reload FTDC data for this run.';
      } else {
        statusEl.textContent =
          'Grafana stack is not running (Docker/Colima may be stopped). ' +
          'Start Docker with: colima start --cpu 4 --memory 8 — then click Load FTDC for this run.';
      }
    } catch {
      statusEl.textContent = 'Could not reach Grafana status endpoint.';
    }

    loadBtn?.addEventListener('click', () => this.loadRun(runId));
    this._tryShowUrls(runId);
  },

  async _tryShowUrls(runId) {
    const statusEl = document.getElementById('grafana-status');
    try {
      const resp = await fetch(`/simagix/runs/${runId}/grafana/urls`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.stack?.grafana && data.stack?.ftdc_api) {
        statusEl.textContent =
          'Grafana stack is running. Loading FTDC data for this run…';
        await this.loadRun(runId, { silent: true });
      }
    } catch {
      /* optional prefetch */
    }
  },

  async loadRun(runId, options = {}) {
    const { silent = false } = options;
    const statusEl = document.getElementById('grafana-status');
    const loadBtn = document.getElementById('grafana-load-btn');
    loadBtn.disabled = true;
    if (!silent) {
      statusEl.textContent =
        'Loading FTDC into Grafana (large datasets can take ~2 minutes)…';
    }

    try {
      const resp = await fetch(`/simagix/runs/${runId}/grafana/load`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Load failed');
      if (data.load?.ok !== 1) {
        throw new Error(data.load?.err || 'FTDC API did not accept diagnostic.data');
      }

      statusEl.textContent =
        'Grafana ready — FTDC loaded for this run. Open a dashboard in a new tab.';
      this._showLinks(data);
    } catch (err) {
      statusEl.textContent = `Failed: ${err.message}. Run: ./simagix-workspace/scripts/run-grafana-stack.sh`;
    } finally {
      loadBtn.disabled = false;
    }
  },

  _showLinks(data) {
    const anomalyLink = document.getElementById('grafana-open-anomaly');
    const allLink = document.getElementById('grafana-open-all');
    anomalyLink.href = data.anomaly_focus_url;
    allLink.href = data.all_metrics_url;
    anomalyLink.hidden = false;
    allLink.hidden = false;

    const metrics = (data.anomaly_metrics || []).join(', ') || 'n/a';
    const meta = document.getElementById('grafana-meta');
    meta.hidden = false;
    meta.textContent =
      `Anomaly window: ${data.anomaly_window?.from} → ${data.anomaly_window?.to} | Metrics: ${metrics}`;
  },
};
