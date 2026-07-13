/** Stitch uses Tailwind `class="hidden"`; classic uses the `hidden` attribute — toggle both. */
function setGrafanaElVisible(el, visible) {
  if (!el) return;
  el.hidden = !visible;
  el.classList.toggle('hidden', !visible);
  if (visible) {
    el.removeAttribute('disabled');
  }
}

window.FtdcGrafana = {
  _loadInFlight: null,
  _openLinksBound: false,

  _loadedRunKey(runId) {
    return `grafana-ftdc-loaded:${runId}`;
  },

  _markLoaded(runId) {
    try {
      sessionStorage.setItem(this._loadedRunKey(runId), String(Date.now()));
    } catch {
      /* private mode / disabled storage */
    }
  },

  _wasLoadedThisSession(runId) {
    try {
      return sessionStorage.getItem(this._loadedRunKey(runId)) != null;
    } catch {
      return false;
    }
  },

  _loadInProgress(runId) {
    try {
      const started = sessionStorage.getItem(`${this._loadedRunKey(runId)}:started`);
      if (!started) return false;
      return Date.now() - Number(started) < 5 * 60 * 1000;
    } catch {
      return false;
    }
  },

  _bindOpenLinks() {
    if (this._openLinksBound) return;
    this._openLinksBound = true;
    for (const id of ['grafana-open-anomaly', 'grafana-open-all']) {
      const linkEl = document.getElementById(id);
      if (!linkEl) continue;
      linkEl.addEventListener('click', (event) => {
        event.preventDefault();
        const url = linkEl.dataset.grafanaUrl || '';
        if (!url || url === '#') return;
        const now = Date.now();
        // Debounce rapid repeat clicks so a double/triple click opens one tab.
        if (linkEl._grafanaOpenMs && now - linkEl._grafanaOpenMs < 500) return;
        linkEl._grafanaOpenMs = now;
        window.open(url, '_blank', 'noopener');
      });
    }
  },

  _applyOpenLinks(anomalyUrl, allUrl) {
    const anomalyLink = document.getElementById('grafana-open-anomaly');
    const allLink = document.getElementById('grafana-open-all');
    if (!anomalyLink || !allLink) return;
    anomalyLink.dataset.grafanaUrl = anomalyUrl;
    allLink.dataset.grafanaUrl = allUrl;
    setGrafanaElVisible(anomalyLink, true);
    setGrafanaElVisible(allLink, true);
  },

  async init(runId) {
    const statusEl = document.getElementById('grafana-status');
    const loadBtn = document.getElementById('grafana-load-btn');
    this._bindOpenLinks();

    try {
      const status = await fetch('/simagix/runs/grafana/status').then((r) => r.json());
      if (status.grafana && status.ftdc_api) {
        statusEl.textContent =
          'Grafana stack is running. Open charts in a new tab, or reload FTDC data for this run.';
      } else if (this._loadInProgress(runId)) {
        statusEl.textContent =
          'FTDC decode in progress (~2 min) — stack is busy; dashboard links appear when ready.';
      } else {
        statusEl.textContent =
          'Grafana stack is not running (Docker/Colima may be stopped). ' +
          'Start Docker with: colima start --cpu 4 --memory 8 — then click Load FTDC for this run.';
      }
    } catch {
      statusEl.textContent = 'Could not reach Grafana status endpoint.';
    }

    if (loadBtn && !loadBtn.dataset.grafanaBound) {
      loadBtn.dataset.grafanaBound = '1';
      loadBtn.addEventListener('click', () => this.loadRun(runId));
    }
    this._tryShowUrls(runId);
  },

  async _tryShowUrls(runId) {
    const statusEl = document.getElementById('grafana-status');
    try {
      const resp = await fetch(`/simagix/runs/${runId}/grafana/urls`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.stack?.grafana && data.stack?.ftdc_api) {
        this._showLinksFromUrls(data);
        if (this._wasLoadedThisSession(runId)) {
          statusEl.textContent =
            'Grafana stack is running. FTDC already loaded this session — click Load FTDC to reload, or open a dashboard.';
        } else if (this._loadInProgress(runId)) {
          statusEl.textContent =
            "FTDC decode already in progress (~2 min) — dashboard links are ready; data appears when decode finishes.";
        } else {
          statusEl.textContent =
            "Grafana stack is running. Loading this run's FTDC data (~2 min)…";
          await this.loadRun(runId, { silent: true });
        }
      }
    } catch {
      /* optional prefetch */
    }
  },

  _showLinksFromUrls(data) {
    this._applyOpenLinks(data.anomaly_focus_url, data.all_metrics_url);

    const metrics = (data.anomaly_metrics || []).join(', ') || 'n/a';
    const meta = document.getElementById('grafana-meta');
    if (!meta) return;
    setGrafanaElVisible(meta, true);
    meta.textContent =
      `Anomaly window: ${data.anomaly_window?.from} → ${data.anomaly_window?.to} | Metrics: ${metrics}`;
  },

  async loadRun(runId, options = {}) {
    if (this._loadInFlight) {
      return this._loadInFlight;
    }
    const { silent = false } = options;
    const statusEl = document.getElementById('grafana-status');
    const loadBtn = document.getElementById('grafana-load-btn');
    loadBtn.disabled = true;
    if (!silent) {
      statusEl.textContent =
        'Loading FTDC into Grafana (large datasets can take ~2 minutes)…';
    }

    this._loadInFlight = (async () => {
    try {
      try {
        sessionStorage.setItem(`${this._loadedRunKey(runId)}:started`, String(Date.now()));
      } catch {
        /* ignore */
      }
      const resp = await fetch(`/simagix/runs/${runId}/grafana/load`, { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Load failed');
      if (data.load?.ok !== 1) {
        throw new Error(data.load?.err || 'FTDC API did not accept diagnostic.data');
      }

      statusEl.textContent =
        'Grafana ready — FTDC loaded for this run. Open a dashboard in a new tab.';
      this._markLoaded(runId);
      this._showLinks(data);
    } catch (err) {
      statusEl.textContent = `Failed: ${err.message}. Run: ./simagix-workspace/scripts/run-grafana-stack.sh`;
    } finally {
      loadBtn.disabled = false;
      this._loadInFlight = null;
    }
    })();
    return this._loadInFlight;
  },

  _showLinks(data) {
    this._applyOpenLinks(data.anomaly_focus_url, data.all_metrics_url);

    const metrics = (data.anomaly_metrics || []).join(', ') || 'n/a';
    const meta = document.getElementById('grafana-meta');
    if (!meta) return;
    setGrafanaElVisible(meta, true);
    meta.textContent =
      `Anomaly window: ${data.anomaly_window?.from} → ${data.anomaly_window?.to} | Metrics: ${metrics}`;
  },
};
