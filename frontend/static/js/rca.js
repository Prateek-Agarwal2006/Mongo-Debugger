/* global RUN_ID */

function categoryBadgeClass(category) {
  switch (category) {
    case "web":
      return "badge badge-trace-web";
    case "mcp":
      return "badge badge-trace-mcp";
    case "local":
      return "badge badge-trace-local";
    case "shell":
      return "badge badge-trace-shell";
    default:
      return "badge text-bg-secondary";
  }
}

function phaseLabel(phase) {
  switch (phase) {
    case "investigation":
      return "A";
    case "clarify":
      return "B";
    case "final_rca":
      return "C";
    case "chatbot":
      return "Chat";
    default:
      return phase || "?";
  }
}

function isStitchToolTrace() {
  return document.getElementById("tool-trace-table")?.classList.contains("tool-trace-table--stitch");
}

function phaseBadgeHtml(phase) {
  const label = phaseLabel(phase);
  if (isStitchToolTrace()) {
    return `<span class="tool-trace-badge tool-trace-badge--phase">${label}</span>`;
  }
  return `<span class="badge text-bg-dark border border-secondary-subtle">${label}</span>`;
}

function categoryBadgeHtml(category) {
  if (isStitchToolTrace()) {
    const cat = category || "default";
    const cls = ["mcp", "web", "local", "shell"].includes(cat)
      ? `tool-trace-badge--cat-${cat}`
      : "tool-trace-badge--cat-default";
    return `<span class="tool-trace-badge ${cls}">${cat}</span>`;
  }
  return `<span class="${categoryBadgeClass(category)}">${category}</span>`;
}

function statusHtml(status) {
  const value = status || "";
  if (!isStitchToolTrace()) return value;
  const lower = value.toLowerCase();
  const cls =
    lower === "ok" || lower === "success" || lower === "succeeded"
      ? "trace-status--ok"
      : lower === "error" || lower === "failed"
        ? "trace-status--error"
        : "";
  return `<span class="trace-status ${cls}">${value}</span>`;
}

const TOOL_TRACE_CATEGORIES = ["mcp", "web", "local", "shell", "other"];

/** @type {{ entries: unknown[], summary: Record<string, unknown> } | null} */
let toolTracePayload = null;
let toolTraceCategoryFilter = null;
let toolTraceFiltersBound = false;

function renderToolTraceSummary(summaryEl, summary, activeFilter) {
  const byCat = summary.by_category || {};
  const total = summary.total || 0;
  if (isStitchToolTrace()) {
    const chips = TOOL_TRACE_CATEGORIES.map((cat) => {
      const label = cat.charAt(0).toUpperCase() + cat.slice(1);
      const count = byCat[cat] || 0;
      const active = activeFilter === cat ? " is-active" : "";
      return (
        `<button type="button" class="tool-trace-chip tool-trace-chip--filter tool-trace-chip--${cat}${active}" data-trace-filter="${cat}" aria-pressed="${activeFilter === cat ? "true" : "false"}">` +
        `${label} <strong>${count}</strong></button>`
      );
    }).join("");
    const totalActive = !activeFilter ? " is-active" : "";
    summaryEl.innerHTML = `
      <div class="tool-trace-summary-chips">
        <button type="button" class="tool-trace-chip tool-trace-chip--filter tool-trace-chip--total${totalActive}" data-trace-filter="" aria-pressed="${!activeFilter ? "true" : "false"}">
          Total <strong>${total}</strong>
        </button>
        ${chips}
      </div>`;
    bindToolTraceFilters(summaryEl);
    return;
  }
  summaryEl.textContent =
    `Total: ${total} | MCP: ${byCat.mcp || 0} | Web: ${byCat.web || 0} | ` +
    `Local: ${byCat.local || 0} | Shell: ${byCat.shell || 0}`;
}

function bindToolTraceFilters(summaryEl) {
  if (!isStitchToolTrace() || toolTraceFiltersBound) return;
  toolTraceFiltersBound = true;
  summaryEl.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-trace-filter]");
    if (!btn) return;
    const cat = btn.dataset.traceFilter;
    if (!cat) {
      toolTraceCategoryFilter = null;
    } else if (toolTraceCategoryFilter === cat) {
      toolTraceCategoryFilter = null;
    } else {
      toolTraceCategoryFilter = cat;
    }
    renderToolTraceView();
  });
}

function renderToolTraceRows(tbody, entries, activeFilter, totalUnfiltered) {
  tbody.innerHTML = "";
  if (!entries.length) {
    let emptyMsg = "No tool calls recorded yet — run RCA to populate.";
    if (isStitchToolTrace() && activeFilter && totalUnfiltered > 0) {
      emptyMsg = `No ${activeFilter} tool calls in this trace.`;
    }
    if (isStitchToolTrace()) {
      tbody.innerHTML = `<tr class="tool-trace-empty"><td colspan="5">${emptyMsg}</td></tr>`;
    } else {
      tbody.innerHTML =
        `<tr><td colspan="5" class="text-secondary small">${emptyMsg}</td></tr>`;
    }
    return;
  }

  for (const entry of entries) {
    const row = document.createElement("tr");
    if (isStitchToolTrace()) row.className = "tool-trace-row";
    const argsText = entry.args_summary || entry.result_summary || "";
    const safeTitle = argsText.replace(/"/g, "&quot;");
    row.innerHTML = `
      <td>${phaseBadgeHtml(entry.phase)}</td>
      <td>${categoryBadgeHtml(entry.category)}</td>
      <td class="trace-tool-name">${entry.tool_name || ""}</td>
      <td>${statusHtml(entry.status)}</td>
      <td class="trace-args" title="${safeTitle}">${argsText}</td>`;
    tbody.appendChild(row);
  }
}

function initToolTraceDragScroll() {
  const el = document.getElementById("tool-trace-scroll");
  if (!el || el.dataset.dragBound || !isStitchToolTrace()) return;
  el.dataset.dragBound = "1";

  let dragging = false;
  let startX = 0;
  let startScrollLeft = 0;

  el.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || e.target.closest("button, a, input, label")) return;
    dragging = true;
    startX = e.pageX;
    startScrollLeft = el.scrollLeft;
    el.classList.add("tool-trace-scroll--dragging");
  });

  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    e.preventDefault();
    el.scrollLeft = startScrollLeft - (e.pageX - startX);
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("tool-trace-scroll--dragging");
  });
}

function renderToolTraceView() {
  const panel = document.getElementById("tool-trace-panel");
  const summaryEl = document.getElementById("tool-trace-summary");
  const tbody = document.querySelector("#tool-trace-table tbody");
  if (!panel || !summaryEl || !tbody || !toolTracePayload) return;

  initToolTraceDragScroll();

  const entries = toolTracePayload.entries || [];
  const summary = toolTracePayload.summary || {};
  renderToolTraceSummary(summaryEl, summary, toolTraceCategoryFilter);

  const filtered = toolTraceCategoryFilter
    ? entries.filter((entry) => entry.category === toolTraceCategoryFilter)
    : entries;
  renderToolTraceRows(tbody, filtered, toolTraceCategoryFilter, entries.length);
}

function renderToolTrace(payload) {
  toolTracePayload = payload;
  renderToolTraceView();
}

function selectedLlm() {
  const select = document.getElementById("llm-context-select");
  return select?.value || "mock";
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isStitchRunPage() {
  return Boolean(document.getElementById("btn-investigation"));
}

function mcpTransportChip(connector) {
  if (connector.transport === "http") {
    return `<span class="mcp-run-panel__chip mcp-run-panel__chip--http">HTTP</span>`;
  }
  if (connector.transport === "stdio_template") {
    return `<span class="mcp-run-panel__chip mcp-run-panel__chip--stdio">Stdio</span>`;
  }
  return "";
}

function renderMcpRequiredRow(container) {
  const row = document.createElement("label");
  row.className = "mcp-run-panel__row mcp-run-panel__row--required";
  row.innerHTML = `
    <input type="checkbox" value="simagix-evidence" checked disabled aria-label="Simagix evidence (required)"/>
    <span class="mcp-run-panel__row-body">
      <span class="mcp-run-panel__row-name">Simagix evidence</span>
      <span class="mcp-run-panel__row-meta">
        <span class="mcp-run-panel__chip mcp-run-panel__chip--required">Required</span>
        <span class="mcp-run-panel__id">simagix-evidence</span>
      </span>
    </span>`;
  container.appendChild(row);
}

function renderMcpConnectorRow(connector) {
  const row = document.createElement("label");
  row.className = "mcp-run-panel__row";
  row.dataset.connectorId = connector.id;
  row.innerHTML = `
    <input class="mcp-run-toggle" type="checkbox" value="${escapeHtml(connector.id)}" aria-label="${escapeHtml(connector.name)}"/>
    <span class="mcp-run-panel__row-body">
      <span class="mcp-run-panel__row-name">${escapeHtml(connector.name)}</span>
      <span class="mcp-run-panel__row-meta">
        ${mcpTransportChip(connector)}
        <span class="mcp-run-panel__id">${escapeHtml(connector.id)}</span>
      </span>
    </span>`;
  const input = row.querySelector("input");
  input?.addEventListener("change", () => syncMcpBulkActions());
  return row;
}

function mcpOptionalToggles() {
  return Array.from(document.querySelectorAll(".mcp-run-toggle"));
}

function syncMcpRowStyles() {
  document.querySelectorAll(".mcp-run-panel__row:not(.mcp-run-panel__row--required)").forEach((row) => {
    const input = row.querySelector(".mcp-run-toggle");
    row.classList.toggle("is-checked", Boolean(input?.checked));
  });
}

function syncMcpBulkActions() {
  const toggles = mcpOptionalToggles();
  const selectAllBtn = document.getElementById("mcp-select-all");
  const clearAllBtn = document.getElementById("mcp-clear-all");
  const hasOptional = toggles.length > 0;
  const checkedCount = toggles.filter((input) => input.checked).length;

  if (selectAllBtn) {
    selectAllBtn.hidden = !hasOptional;
    if (isStitchRunPage()) selectAllBtn.classList.toggle("hidden", !hasOptional);
    selectAllBtn.disabled = hasOptional && checkedCount === toggles.length;
  }
  if (clearAllBtn) {
    clearAllBtn.hidden = !hasOptional;
    if (isStitchRunPage()) clearAllBtn.classList.toggle("hidden", !hasOptional);
    clearAllBtn.disabled = checkedCount === 0;
  }
  syncMcpRowStyles();
}

function selectedMcpIds() {
  const panel = document.getElementById("mcp-run-checkboxes");
  if (!panel) return [];
  return Array.from(panel.querySelectorAll('input[type="checkbox"]:checked:not([disabled])'))
    .map((input) => input.value)
    .filter(Boolean);
}

async function loadRunMcpConnectors() {
  const container = document.getElementById("mcp-run-checkboxes");
  const emptyMsg = document.getElementById("mcp-run-empty");
  if (!container) return;

  container.innerHTML = "";
  renderMcpRequiredRow(container);

  const resp = await fetch("/simagix/mcp-connectors");
  if (!resp.ok) {
    if (emptyMsg) {
      emptyMsg.hidden = false;
      emptyMsg.textContent = "Could not load MCP connectors.";
      if (isStitchRunPage()) emptyMsg.classList.remove("hidden");
    }
    syncMcpBulkActions();
    return;
  }
  const data = await resp.json();
  const connectors = data.connectors || [];
  if (!connectors.length) {
    if (emptyMsg) {
      emptyMsg.hidden = false;
      if (isStitchRunPage()) emptyMsg.classList.remove("hidden");
    }
    syncMcpBulkActions();
    return;
  }
  if (emptyMsg) {
    emptyMsg.hidden = true;
    if (isStitchRunPage()) emptyMsg.classList.add("hidden");
  }

  for (const connector of connectors) {
    container.appendChild(renderMcpConnectorRow(connector));
  }
  syncMcpBulkActions();
}

function initRunMcpPanel() {
  const selectAllBtn = document.getElementById("mcp-select-all");
  const clearAllBtn = document.getElementById("mcp-clear-all");
  selectAllBtn?.addEventListener("click", () => {
    mcpOptionalToggles().forEach((input) => {
      input.checked = true;
    });
    syncMcpBulkActions();
  });
  clearAllBtn?.addEventListener("click", () => {
    mcpOptionalToggles().forEach((input) => {
      input.checked = false;
    });
    syncMcpBulkActions();
  });
  loadRunMcpConnectors();
}

function llmQuery() {
  return `?llm=${encodeURIComponent(selectedLlm())}`;
}

function updateReportLinks() {
  const llm = selectedLlm();
  const htmlLink = document.getElementById("html-report-link");
  const plainLink = document.getElementById("plain-report-link");
  if (htmlLink) {
    htmlLink.href = `/simagix/runs/${RUN_ID}/phase2/reports/latest/view?llm=${encodeURIComponent(llm)}`;
  }
  if (plainLink) {
    plainLink.href =
      `/simagix/runs/${RUN_ID}/phase2/reports/latest?format=pretty&llm=${encodeURIComponent(llm)}`;
  }
  const label = document.getElementById("report-llm-label");
  if (label) label.textContent = `LLM: ${llm}`;
}

async function fetchToolTrace() {
  const summaryEl = document.getElementById("tool-trace-summary");
  const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/tool-trace${llmQuery()}`);
  if (!resp.ok) {
    if (summaryEl) summaryEl.textContent = "Could not load tool trace.";
    toolTraceCategoryFilter = null;
    renderToolTrace({ entries: [], summary: { total: 0, by_category: {} } });
    return;
  }
  const data = await resp.json();
  toolTraceCategoryFilter = null;
  renderToolTrace(data);
}

function hideClarifyUi() {
  window.FtdcClarifyWizard?.hide();
  const investigationEl = document.getElementById("investigation-summary");
  const result = document.getElementById("rca-result");
  if (investigationEl) investigationEl.hidden = true;
  if (result) result.hidden = true;
  window.FtdcAgentChat?.onReset?.();
}

function showClarifyForm(questions, existingAnswers = {}) {
  window.FtdcClarifyWizard?.show(questions, existingAnswers);
}

function syncPhaseRail(active, running = false) {
  window.FtdcPhaseRail?.setPhase(active, { running });
}

function scrollToReportSection() {
  const viewer = document.getElementById("report-viewer");
  const section = document.getElementById("report-section") || viewer;
  if (!section) return;
  if (window.FtdcMotion?.scrollTo) {
    window.FtdcMotion.scrollTo(section);
  } else {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setPanelVisible(el, visible) {
  if (!el) return;
  el.hidden = !visible;
  el.classList.toggle("hidden", !visible);
}

async function loadSavedReport() {
  const viewer = document.getElementById("report-viewer");
  const noMsg = document.getElementById("no-report-msg");
  const rawDetails = document.getElementById("report-raw-details");
  const llmLabel = document.getElementById("report-llm-label");
  if (llmLabel) llmLabel.textContent = `LLM: ${selectedLlm()}`;

  const url = `/simagix/runs/${RUN_ID}/phase2/reports/latest?llm=${encodeURIComponent(selectedLlm())}`;
  const reportResp = await fetch(url);
  if (reportResp.status === 404) {
    window.FtdcReportViewer?.clear(viewer);
    setPanelVisible(noMsg, true);
    setPanelVisible(rawDetails, false);
    return;
  }
  if (!reportResp.ok) {
    return;
  }
  const data = await reportResp.json();
  if (viewer && window.FtdcReportViewer) {
    window.FtdcReportViewer.render(data, viewer);
  }
  setPanelVisible(noMsg, false);
  setPanelVisible(rawDetails, true);
}

async function loadLlmContext() {
  const statusEl = document.getElementById("rca-status");
  hideClarifyUi();
  updateReportLinks();
  await fetchToolTrace();
  await loadSavedReport();
  window.FtdcAgentChat?.refresh?.();

  const statusResp = await fetch(`/simagix/runs/${RUN_ID}/phase2/status${llmQuery()}`);
  if (!statusResp.ok) return;
  const statusData = await statusResp.json();
  const investigationEl = document.getElementById("investigation-summary");

  window.FtdcPhaseRail?.setFromApiStatus(statusData.status);
  window.FtdcPhaseRail?.showShell?.();

  if (statusData.status === "awaiting_clarifications") {
    if (statusEl) {
      statusEl.textContent = "Phase B: answer one question at a time, then submit for final RCA.";
    }
    if (statusData.investigation && investigationEl) {
      investigationEl.hidden = false;
      investigationEl.textContent = JSON.stringify(statusData.investigation, null, 2);
    }
    const questions = statusData.questions?.questions || [];
    showClarifyForm(questions, statusData.answers || {});
  } else if (statusData.status === "running_rca") {
    if (statusEl) {
      statusEl.textContent = "Phase C: running final RCA with your answers…";
    }
  } else if (statusData.status === "completed") {
    if (statusEl) {
      statusEl.textContent =
        "RCA complete — report below. Use the chat panel for follow-up questions.";
    }
    window.FtdcAgentChat?.onCompleted?.(selectedLlm);
  } else if (statusData.status === "not_started") {
    if (statusEl) {
      statusEl.textContent =
        "Phase A: tier-2 investigation (MCP tools) → Phase B: questions → Phase C: final RCA.";
    }
  }
}

function initRcaPanel(initialLlm) {
  const runBtn = document.getElementById("run-rca-btn");
  const llmSelect = document.getElementById("llm-context-select");
  const form = document.getElementById("clarify-form");
  const investigationEl = document.getElementById("investigation-summary");
  const statusEl = document.getElementById("rca-status");

  if (llmSelect && initialLlm) {
    llmSelect.value = initialLlm;
  }
  initRunMcpPanel();
  loadLlmContext();
  window.FtdcAgentChat?.init?.(RUN_ID, selectedLlm, { hasReport: HAS_REPORT });

  llmSelect?.addEventListener("change", () => {
    loadLlmContext();
  });

  runBtn?.addEventListener("click", async () => {
    if (typeof PHASE2_HATCHET_BLOCKED !== "undefined" && PHASE2_HATCHET_BLOCKED) {
      alert("Upload logs are present but Hatchet summary.json is not ready yet. Wait for Hatchet or retry log analysis.");
      return;
    }
    runBtn.disabled = true;
    hideClarifyUi();
    window.FtdcPhaseRail?.reset?.();
    syncPhaseRail("A", true);
    if (statusEl) statusEl.textContent = "Phase A: running tier-2 investigation (MCP tools)…";
    try {
      const llm = selectedLlm();
      const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ llm, enabled_mcp_ids: selectedMcpIds() }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to start RCA");
      if (data.investigation && investigationEl) {
        investigationEl.hidden = false;
        investigationEl.textContent = JSON.stringify(data.investigation, null, 2);
      }
      await fetchToolTrace();
      window.FtdcPhaseRail?.applyState?.({
        active: "B",
        running: false,
        completed: { A: true, B: false, C: false },
      });
      if (statusEl) statusEl.textContent = "Phase B: answer one question at a time, then submit for final RCA.";
      const questions = data.clarifying_questions?.questions || [];
      showClarifyForm(questions);
    } catch (err) {
      window.FtdcPhaseRail?.reset?.();
      if (statusEl) statusEl.textContent = `Failed: ${err.message}`;
    } finally {
      runBtn.disabled = false;
    }
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    window.FtdcClarifyWizard?.setSubmitting?.(true);
    window.FtdcPhaseRail?.applyState?.({
      active: "C",
      running: true,
      completed: { A: true, B: true, C: false },
    });
    if (statusEl) statusEl.textContent = "Phase C: running final RCA with your answers…";
    const answers = window.FtdcClarifyWizard?.collectAnswers?.() || {};
    try {
      const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/clarify${llmQuery()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers, enabled_mcp_ids: selectedMcpIds() }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        window.FtdcClarifyWizard?.setSubmitting?.(false);
        window.FtdcPhaseRail?.applyState?.({
          active: "B",
          running: false,
          completed: { A: true, B: false, C: false },
        });
        if (statusEl) statusEl.textContent = `RCA failed: ${data.detail || "unknown error"}`;
        return;
      }
      const result = document.getElementById("rca-result");
      if (result) {
        result.hidden = false;
        result.textContent = JSON.stringify(data.report || data, null, 2);
      }
      window.FtdcClarifyWizard?.hide?.();
      syncPhaseRail("done");
      if (statusEl) {
        statusEl.textContent =
          "RCA complete — full report is in the RCA Report section below.";
      }
      await fetchToolTrace();
      await loadSavedReport();
      window.FtdcAgentChat?.onCompleted?.(selectedLlm);
      scrollToReportSection();
    } catch (err) {
      window.FtdcClarifyWizard?.setSubmitting?.(false);
      window.FtdcPhaseRail?.applyState?.({
        active: "B",
        running: false,
        completed: { A: true, B: false, C: false },
      });
      if (statusEl) statusEl.textContent = `RCA failed: ${err.message}`;
    }
  });
}

window.FtdcRca = { init: initRcaPanel, fetchToolTrace, renderToolTrace, loadLlmContext };
