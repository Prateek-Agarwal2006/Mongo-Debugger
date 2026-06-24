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

function renderToolTrace(payload) {
  const panel = document.getElementById("tool-trace-panel");
  const summaryEl = document.getElementById("tool-trace-summary");
  const tbody = document.querySelector("#tool-trace-table tbody");
  if (!panel || !summaryEl || !tbody) return;

  const entries = payload?.entries || [];
  const summary = payload?.summary || {};
  const byCat = summary.by_category || {};
  summaryEl.textContent =
    `Total: ${summary.total || 0} | MCP: ${byCat.mcp || 0} | Web: ${byCat.web || 0} | ` +
    `Local: ${byCat.local || 0} | Shell: ${byCat.shell || 0}`;

  tbody.innerHTML = "";
  if (!entries.length) {
    tbody.innerHTML =
      '<tr><td colspan="5" class="text-secondary small">No tool calls recorded yet — run RCA to populate.</td></tr>';
    return;
  }

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="badge text-bg-dark border border-secondary-subtle">${phaseLabel(entry.phase)}</span></td>
      <td><span class="${categoryBadgeClass(entry.category)}">${entry.category}</span></td>
      <td>${entry.tool_name || ""}</td>
      <td>${entry.status || ""}</td>
      <td class="trace-args" title="${(entry.args_summary || "").replace(/"/g, "&quot;")}">
        ${entry.args_summary || entry.result_summary || ""}
      </td>`;
    tbody.appendChild(row);
  }
}

function selectedLlm() {
  const select = document.getElementById("llm-context-select");
  return select?.value || "mock";
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
    renderToolTrace({ entries: [], summary: { total: 0, by_category: {} } });
    return;
  }
  const data = await resp.json();
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
  const section = document.getElementById("report-section");
  if (!section) return;
  if (window.FtdcMotion?.scrollTo) {
    window.FtdcMotion.scrollTo(section);
  } else {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
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
    if (noMsg) noMsg.hidden = false;
    if (rawDetails) rawDetails.hidden = true;
    return;
  }
  if (!reportResp.ok) {
    return;
  }
  const data = await reportResp.json();
  if (viewer && window.FtdcReportViewer) {
    window.FtdcReportViewer.render(data, viewer);
  }
  if (noMsg) noMsg.hidden = true;
  if (rawDetails) rawDetails.hidden = false;
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
        "RCA complete — report below. Use the chat panel for follow-up questions or profiler data.";
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
        body: JSON.stringify({ llm }),
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
        body: JSON.stringify({ answers }),
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
