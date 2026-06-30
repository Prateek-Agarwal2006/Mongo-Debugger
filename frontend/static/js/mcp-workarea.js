/* global bootstrap */

let stdioTemplates = [];

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function transportFields() {
  const transport = document.getElementById("mcp-transport")?.value || "http";
  const httpFields = document.getElementById("mcp-http-fields");
  const stdioFields = document.getElementById("mcp-stdio-fields");
  if (httpFields) httpFields.hidden = transport !== "http";
  if (stdioFields) stdioFields.hidden = transport !== "stdio_template";
}

function isStitchMcpPage() {
  return Boolean(document.getElementById("btn-tab-configured"));
}

function renderEnvFields(template) {
  const container = document.getElementById("mcp-env-fields");
  const help = document.getElementById("mcp-template-help");
  if (!container || !help) return;
  container.innerHTML = "";
  if (!template) {
    help.textContent = "";
    return;
  }
  help.textContent = template.description || "";
  const stitch = isStitchMcpPage();
  for (const key of template.required_env || []) {
    const wrap = document.createElement("div");
    if (stitch) {
      wrap.innerHTML = `
      <label class="block text-sm font-medium mb-1" for="mcp-env-${key}">${escapeHtml(key)}</label>
      <input class="w-full text-sm font-mono border border-outline-variant rounded-lg px-3 py-2"
        id="mcp-env-${key}" name="env-${key}" type="password" autocomplete="off" required/>`;
    } else {
      wrap.className = "mb-2";
      wrap.innerHTML = `
      <label class="form-label" for="mcp-env-${key}">${escapeHtml(key)}</label>
      <input class="form-control font-monospace" id="mcp-env-${key}" name="env-${key}" type="password" autocomplete="off" required/>`;
    }
    container.appendChild(wrap);
  }
}

function populateTemplateSelect(templates) {
  const select = document.getElementById("mcp-template");
  if (!select) return;
  select.innerHTML = "";
  for (const item of templates) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label;
    select.appendChild(opt);
  }
  const first = templates[0];
  if (first) renderEnvFields(first);
}

async function deleteConnector(id) {
  if (!confirm(`Delete connector "${id}"?`)) return;
  const resp = await fetch(`/simagix/mcp-connectors/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert(body.detail || "Delete failed");
    return;
  }
  await loadConnectors();
}

function connectorCard(connector) {
  const card = document.createElement("div");
  card.className = "border border-secondary-subtle rounded-3 p-3 d-flex flex-wrap align-items-start gap-2";
  const transportLabel = connector.transport === "http" ? "HTTP" : "Stdio template";
  const detail =
    connector.transport === "http"
      ? connector.url || ""
      : `template: ${connector.template_id || "?"}`;
  card.innerHTML = `
    <div class="flex-grow-1">
      <div class="fw-semibold">${escapeHtml(connector.name)} <code class="small">${escapeHtml(connector.id)}</code></div>
      <div class="small text-secondary">${transportLabel} — ${escapeHtml(detail)}</div>
      ${connector.description ? `<div class="small mt-1">${escapeHtml(connector.description)}</div>` : ""}
    </div>
    <button type="button" class="btn btn-outline-danger btn-sm" data-delete-id="${escapeHtml(connector.id)}">
      <i class="bi bi-trash me-1"></i>Delete
    </button>`;
  card.querySelector("[data-delete-id]")?.addEventListener("click", () => deleteConnector(connector.id));
  return card;
}

function connectorTableRow(connector) {
  const transportLabel =
    connector.transport === "http" ? "HTTP" : "Stdio";
  const row = document.createElement("tr");
  row.className = "hover:bg-surface-container-low/50 transition-colors";
  row.innerHTML = `
    <td class="px-6 py-4 text-sm font-semibold text-on-surface">${escapeHtml(connector.name)}</td>
    <td class="px-6 py-4 font-mono text-sm text-on-surface-variant">${escapeHtml(connector.id)}</td>
    <td class="px-6 py-4 text-sm text-on-surface-variant">${transportLabel}</td>
    <td class="px-6 py-4 text-right">
      <button type="button" class="text-primary hover:text-tertiary transition-colors" data-delete-id="${escapeHtml(connector.id)}" aria-label="Delete connector">
        <span class="material-symbols-outlined">delete</span>
      </button>
    </td>`;
  row.querySelector("[data-delete-id]")?.addEventListener("click", () => deleteConnector(connector.id));
  return row;
}

function showMcpTab(which) {
  const configured = which === "configured";
  const paneConfigured = document.getElementById("pane-configured");
  const paneNew = document.getElementById("pane-new");
  const btnConfigured = document.getElementById("btn-tab-configured");
  const btnNew = document.getElementById("btn-tab-new");

  if (paneConfigured) paneConfigured.classList.toggle("hidden", !configured);
  if (paneNew) paneNew.classList.toggle("hidden", configured);

  if (btnConfigured) {
    btnConfigured.classList.toggle("text-tertiary", configured);
    btnConfigured.classList.toggle("border-tertiary", configured);
    btnConfigured.classList.toggle("border-b-2", configured);
    btnConfigured.classList.toggle("text-on-surface-variant", !configured);
    btnConfigured.setAttribute("aria-selected", configured ? "true" : "false");
  }
  if (btnNew) {
    btnNew.classList.toggle("text-tertiary", !configured);
    btnNew.classList.toggle("border-tertiary", !configured);
    btnNew.classList.toggle("border-b-2", !configured);
    btnNew.classList.toggle("text-on-surface-variant", configured);
    btnNew.setAttribute("aria-selected", !configured ? "true" : "false");
  }
}

function showConfiguredTab() {
  const legacyTab = document.getElementById("tab-configured");
  if (legacyTab && window.bootstrap?.Tab) {
    bootstrap.Tab.getOrCreateInstance(legacyTab).show();
    return;
  }
  showMcpTab("configured");
}

async function loadConnectors() {
  const list = document.getElementById("mcp-configured-list");
  const tableBody = document.querySelector("#mcp-configured-table tbody");
  const empty = document.getElementById("mcp-configured-empty");
  const table = document.getElementById("mcp-configured-table");
  if (!list && !tableBody) return;

  const resp = await fetch("/simagix/mcp-connectors");
  if (!resp.ok) {
    if (list) list.innerHTML = '<p class="text-danger small mb-0">Could not load connectors.</p>';
    return;
  }
  const data = await resp.json();
  stdioTemplates = data.stdio_templates || [];
  populateTemplateSelect(stdioTemplates);

  const connectors = data.connectors || [];
  if (!connectors.length) {
    if (empty) empty.classList.remove("hidden");
    if (table) table.classList.add("hidden");
    if (list) list.innerHTML = "";
    if (tableBody) tableBody.innerHTML = "";
    return;
  }

  if (empty) empty.classList.add("hidden");
  if (table) table.classList.remove("hidden");

  if (tableBody) {
    tableBody.innerHTML = "";
    for (const connector of connectors) {
      tableBody.appendChild(connectorTableRow(connector));
    }
  }

  if (list) {
    list.innerHTML = "";
    for (const connector of connectors) {
      list.appendChild(connectorCard(connector));
    }
  }
}

function collectFormPayload(form) {
  const transport = form.transport.value;
  const payload = {
    id: form.id.value.trim(),
    name: form.name.value.trim(),
    transport,
    description: form.description.value.trim(),
  };
  if (transport === "http") {
    payload.url = form.url.value.trim();
    const headersRaw = form.headers.value.trim();
    payload.headers = headersRaw ? JSON.parse(headersRaw) : {};
  } else {
    payload.template_id = form.template_id.value;
    const template = stdioTemplates.find((item) => item.id === payload.template_id);
    payload.env = {};
    for (const key of template?.required_env || []) {
      const input = document.getElementById(`mcp-env-${key}`);
      if (input) payload.env[key] = input.value;
    }
  }
  return payload;
}

function initMcpWorkarea() {
  const form = document.getElementById("mcp-create-form");
  const transport = document.getElementById("mcp-transport");
  const templateSelect = document.getElementById("mcp-template");
  const refreshBtn = document.getElementById("mcp-refresh-btn");
  const addBtn = document.getElementById("mcp-add-btn");
  const statusEl = document.getElementById("mcp-form-status");

  document.getElementById("btn-tab-configured")?.addEventListener("click", () => showMcpTab("configured"));
  document.getElementById("btn-tab-new")?.addEventListener("click", () => showMcpTab("new"));
  addBtn?.addEventListener("click", () => showMcpTab("new"));

  transport?.addEventListener("change", transportFields);
  templateSelect?.addEventListener("change", () => {
    const template = stdioTemplates.find((item) => item.id === templateSelect.value);
    renderEnvFields(template);
  });
  refreshBtn?.addEventListener("click", () => loadConnectors());

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (statusEl) statusEl.textContent = "Saving…";
    try {
      const payload = collectFormPayload(form);
      const resp = await fetch("/simagix/mcp-connectors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Save failed");
      if (statusEl) statusEl.textContent = `Saved ${data.connector?.id || payload.id}.`;
      form.reset();
      transportFields();
      await loadConnectors();
      showConfiguredTab();
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || "Save failed";
    }
  });

  transportFields();
  if (isStitchMcpPage()) {
    showMcpTab("configured");
  }
  loadConnectors();
}

document.addEventListener("DOMContentLoaded", initMcpWorkarea);
