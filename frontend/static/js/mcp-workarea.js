/* global bootstrap */

let stdioTemplates = [];

function transportFields() {
  const transport = document.getElementById("mcp-transport")?.value || "http";
  const httpFields = document.getElementById("mcp-http-fields");
  const stdioFields = document.getElementById("mcp-stdio-fields");
  if (httpFields) httpFields.hidden = transport !== "http";
  if (stdioFields) stdioFields.hidden = transport !== "stdio_template";
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
  for (const key of template.required_env || []) {
    const wrap = document.createElement("div");
    wrap.className = "mb-2";
    wrap.innerHTML = `
      <label class="form-label" for="mcp-env-${key}">${key}</label>
      <input class="form-control font-monospace" id="mcp-env-${key}" name="env-${key}" type="password" autocomplete="off" required/>`;
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
      <div class="fw-semibold">${connector.name} <code class="small">${connector.id}</code></div>
      <div class="small text-secondary">${transportLabel} — ${detail}</div>
      ${connector.description ? `<div class="small mt-1">${connector.description}</div>` : ""}
    </div>
    <button type="button" class="btn btn-outline-danger btn-sm" data-delete-id="${connector.id}">
      <i class="bi bi-trash me-1"></i>Delete
    </button>`;
  card.querySelector("[data-delete-id]")?.addEventListener("click", async () => {
    if (!confirm(`Delete connector "${connector.id}"?`)) return;
    const resp = await fetch(`/simagix/mcp-connectors/${encodeURIComponent(connector.id)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      alert(body.detail || "Delete failed");
      return;
    }
    await loadConnectors();
  });
  return card;
}

async function loadConnectors() {
  const list = document.getElementById("mcp-configured-list");
  const empty = document.getElementById("mcp-configured-empty");
  if (!list) return;
  const resp = await fetch("/simagix/mcp-connectors");
  if (!resp.ok) {
    list.innerHTML = '<p class="text-danger small mb-0">Could not load connectors.</p>';
    return;
  }
  const data = await resp.json();
  stdioTemplates = data.stdio_templates || [];
  populateTemplateSelect(stdioTemplates);
  list.innerHTML = "";
  const connectors = data.connectors || [];
  if (!connectors.length) {
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  for (const connector of connectors) {
    list.appendChild(connectorCard(connector));
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
  const statusEl = document.getElementById("mcp-form-status");

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
      const tab = document.getElementById("tab-configured");
      if (tab && window.bootstrap?.Tab) {
        bootstrap.Tab.getOrCreateInstance(tab).show();
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || "Save failed";
    }
  });

  transportFields();
  loadConnectors();
}

document.addEventListener("DOMContentLoaded", initMcpWorkarea);
