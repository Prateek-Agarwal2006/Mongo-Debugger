/* global RUN_ID */

function categoryBadgeClass(category) {
  switch (category) {
    case "web":
      return "trace-badge trace-badge-web";
    case "mcp":
      return "trace-badge trace-badge-mcp";
    case "local":
      return "trace-badge trace-badge-local";
    case "shell":
      return "trace-badge trace-badge-shell";
    default:
      return "trace-badge";
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
      '<tr><td colspan="5" class="muted">No tool calls recorded yet — run RCA to populate.</td></tr>';
    return;
  }

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${phaseLabel(entry.phase)}</td>
      <td><span class="${categoryBadgeClass(entry.category)}">${entry.category}</span></td>
      <td>${entry.tool_name || ""}</td>
      <td>${entry.status || ""}</td>
      <td class="trace-args" title="${(entry.args_summary || "").replace(/"/g, "&quot;")}">
        ${entry.args_summary || entry.result_summary || ""}
      </td>`;
    tbody.appendChild(row);
  }
}

async function fetchToolTrace() {
  const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/tool-trace`);
  if (!resp.ok) return;
  const data = await resp.json();
  renderToolTrace(data);
}

function initRcaPanel() {
  const runBtn = document.getElementById("run-rca-btn");
  const mockToggle = document.getElementById("force-mock-toggle");
  const form = document.getElementById("clarify-form");
  const container = document.getElementById("questions-container");
  const result = document.getElementById("rca-result");
  const investigationEl = document.getElementById("investigation-summary");
  const statusEl = document.getElementById("rca-status");

  fetchToolTrace();

  runBtn?.addEventListener("click", async () => {
    runBtn.disabled = true;
    form.hidden = true;
    result.hidden = true;
    if (investigationEl) investigationEl.hidden = true;
    if (statusEl) statusEl.textContent = "Phase A: running tier-2 investigation (MCP tools)…";
    try {
      const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_mock: mockToggle?.checked ?? false }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to start RCA");
      if (data.investigation && investigationEl) {
        investigationEl.hidden = false;
        investigationEl.textContent = JSON.stringify(data.investigation, null, 2);
      }
      await fetchToolTrace();
      if (statusEl) statusEl.textContent = "Phase B: review questions below, then submit for final RCA.";
      const questions = data.clarifying_questions?.questions || [];
      if (!questions.length) {
        container.innerHTML = "<p class=\"muted\">No clarifying questions needed — submit to run final RCA.</p>";
      } else {
        container.innerHTML = questions.map((q) => `
          <label><strong>${q.question}</strong><br><span class="muted">${q.rationale}</span>
            <textarea name="${q.id}" rows="2" style="width:100%"></textarea>
          </label>`).join("");
      }
      form.hidden = false;
    } catch (err) {
      if (statusEl) statusEl.textContent = `Failed: ${err.message}`;
    } finally {
      runBtn.disabled = false;
    }
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (statusEl) statusEl.textContent = "Phase C: running final RCA with your answers…";
    const answers = {};
    new FormData(form).forEach((v, k) => { if (k !== "") answers[k] = v; });
    const forceMock = mockToggle?.checked ?? false;
    const resp = await fetch(`/simagix/runs/${RUN_ID}/phase2/clarify?force_mock=${forceMock}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (statusEl) statusEl.textContent = `RCA failed: ${data.detail || "unknown error"}`;
      return;
    }
    result.hidden = false;
    result.textContent = JSON.stringify(data.report || data, null, 2);
    if (statusEl) statusEl.textContent = "RCA complete.";
    await fetchToolTrace();
  });
}

window.FtdcRca = { init: initRcaPanel, fetchToolTrace, renderToolTrace };
