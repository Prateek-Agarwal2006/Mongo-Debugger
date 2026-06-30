/* global bootstrap */

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isStitchSkillPage() {
  return Boolean(document.getElementById("skill-configured-table"));
}

function showSkillTab(which) {
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
  showSkillTab("configured");
}

async function deleteSkill(slotName) {
  if (!confirm(`Delete skill "${slotName}"?`)) return;
  const resp = await fetch(`/simagix/skills/${encodeURIComponent(slotName)}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert(body.detail || "Delete failed");
    return;
  }
  await loadSkills();
}

function skillCard(skill) {
  const card = document.createElement("div");
  card.className = "border border-secondary-subtle rounded-3 p-3 d-flex flex-wrap align-items-start gap-2";
  card.innerHTML = `
    <div class="flex-grow-1">
      <div class="fw-semibold"><code>${escapeHtml(skill.slot_name)}</code></div>
      ${skill.description ? `<div class="small text-secondary mt-1">${escapeHtml(skill.description)}</div>` : ""}
    </div>
    <button type="button" class="btn btn-outline-danger btn-sm" data-delete-name="${escapeHtml(skill.slot_name)}">
      <i class="bi bi-trash me-1"></i>Delete
    </button>`;
  card.querySelector("[data-delete-name]")?.addEventListener("click", () => deleteSkill(skill.slot_name));
  return card;
}

function skillTableRow(skill) {
  const row = document.createElement("tr");
  row.className = "hover:bg-surface-container-low/50 transition-colors";
  row.innerHTML = `
    <td class="px-6 py-4 font-mono text-sm font-semibold text-on-surface">${escapeHtml(skill.slot_name)}</td>
    <td class="px-6 py-4 text-sm text-on-surface-variant">${escapeHtml(skill.description || "—")}</td>
    <td class="px-6 py-4 text-right">
      <button type="button" class="text-primary hover:text-tertiary transition-colors" data-delete-name="${escapeHtml(skill.slot_name)}" aria-label="Delete skill">
        <span class="material-symbols-outlined">delete</span>
      </button>
    </td>`;
  row.querySelector("[data-delete-name]")?.addEventListener("click", () => deleteSkill(skill.slot_name));
  return row;
}

async function loadSkills() {
  const list = document.getElementById("skill-configured-list");
  const tableBody = document.querySelector("#skill-configured-table tbody");
  const empty = document.getElementById("skill-configured-empty");
  const table = document.getElementById("skill-configured-table");
  if (!list && !tableBody) return;

  const resp = await fetch("/simagix/skills");
  if (!resp.ok) {
    if (list) list.innerHTML = '<p class="text-danger small mb-0">Could not load skills.</p>';
    return;
  }
  const data = await resp.json();
  const skills = data.skills || [];

  if (!skills.length) {
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
    for (const skill of skills) {
      tableBody.appendChild(skillTableRow(skill));
    }
  }

  if (list) {
    list.innerHTML = "";
    for (const skill of skills) {
      list.appendChild(skillCard(skill));
    }
  }
}

function initSkillWorkarea() {
  const form = document.getElementById("skill-upload-form");
  const refreshBtn = document.getElementById("skill-refresh-btn");
  const addBtn = document.getElementById("skill-add-btn");
  const statusEl = document.getElementById("skill-form-status");

  document.getElementById("btn-tab-configured")?.addEventListener("click", () => showSkillTab("configured"));
  document.getElementById("btn-tab-new")?.addEventListener("click", () => showSkillTab("new"));
  addBtn?.addEventListener("click", () => showSkillTab("new"));

  refreshBtn?.addEventListener("click", () => loadSkills());

  const fileInput = document.getElementById("skill-archive");
  const fileNameEl = document.getElementById("skill-file-name");
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (fileNameEl) {
      fileNameEl.textContent = file ? `Selected: ${file.name}` : "";
    }
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (statusEl) statusEl.textContent = "Uploading…";
    try {
      const formData = new FormData(form);
      const resp = await fetch("/simagix/skills", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Upload failed");
      if (statusEl) statusEl.textContent = `Uploaded ${data.skill?.slot_name || "skill"}.`;
      form.reset();
      if (fileNameEl) fileNameEl.textContent = "";
      await loadSkills();
      showConfiguredTab();
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || "Upload failed";
    }
  });

  if (isStitchSkillPage()) {
    showSkillTab("configured");
  }
  loadSkills();
}

document.addEventListener("DOMContentLoaded", initSkillWorkarea);
