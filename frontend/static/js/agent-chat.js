/**
 * Post-report agentic chatbot — backend persistence via /phase2/chatbot API.
 * Assistant replies: GFM markdown + mermaid; copy-to-clipboard per message.
 * Attachments: upload to chatbot_scratch/attachments, agent reads via tools.
 */

let chatRunId = null;
let getLlmFn = () => "mock";
let chatLoading = false;
let cachedMessages = [];
let pendingFiles = [];
let mermaidReady = false;
let composerBound = false;

const ACCEPTED_EXTENSIONS = [".json", ".txt", ".log", ".md", ".csv", ".yaml", ".yml"];

function escapeChat(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function mermaidThemeForApp() {
  return typeof window.getAppTheme === "function" && window.getAppTheme() === "modern"
    ? "default"
    : "dark";
}

function ensureMermaid(force = false) {
  if (typeof mermaid === "undefined") return;
  if (mermaidReady && !force) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: mermaidThemeForApp(),
    securityLevel: "strict",
  });
  mermaidReady = true;
}

document.addEventListener("app-theme-change", () => {
  mermaidReady = false;
  ensureMermaid(true);
});

function renderMarkdown(text) {
  const raw = String(text ?? "");
  if (typeof marked !== "undefined") {
    return marked.parse(raw, { async: false, gfm: true, breaks: false });
  }
  return escapeChat(raw).replace(/\n/g, "<br>");
}

function wrapTables(html) {
  return html.replace(
    /<table>/g,
    '<div class="agent-chat-table-wrap"><table class="agent-chat-table">'
  ).replace(/<\/table>/g, "</table></div>");
}

async function renderMermaidBlocks(root) {
  if (!root || typeof mermaid === "undefined") return;
  ensureMermaid();
  const blocks = root.querySelectorAll("pre code.language-mermaid");
  const nodes = [];
  blocks.forEach((codeEl) => {
    const pre = codeEl.parentElement;
    if (!pre) return;
    const div = document.createElement("div");
    div.className = "mermaid agent-chat-mermaid";
    div.textContent = codeEl.textContent || "";
    pre.replaceWith(div);
    nodes.push(div);
  });
  if (nodes.length) {
    try {
      await mermaid.run({ nodes });
    } catch {
      /* keep source if diagram fails */
    }
  }
}

function normalizeMessages(payload) {
  const messages = payload?.messages || [];
  return messages.map((m) => ({
    role: m.role === "user" ? "user" : "assistant",
    text: m.content || m.text || "",
    at: m.created_at || m.at,
    attachments: Array.isArray(m.attachments) ? m.attachments : [],
  }));
}

function isStitchAvatarChat() {
  return Boolean(document.querySelector(".agent-chat-stitch--rca"));
}

function attachmentsHtml(attachments) {
  if (!attachments?.length) return "";
  const icon = isStitchAvatarChat()
    ? '<span class="material-symbols-outlined agent-chat-attachment-icon" aria-hidden="true">attach_file</span>'
    : '<i class="bi bi-paperclip me-1" aria-hidden="true"></i>';
  const pills = attachments
    .map(
      (a) =>
        `<span class="agent-chat-attachment-pill" title="${escapeChat(a.path || "")}">${icon}${escapeChat(a.name || "file")}</span>`
    )
    .join("");
  return `<div class="agent-chat-attachments">${pills}</div>`;
}

function loadingBubbleHtml() {
  if (isStitchAvatarChat()) {
    return `<div class="agent-chat-row agent-chat-row--assistant agent-chat-bubble--loading" aria-live="polite" aria-busy="true">
        <div class="agent-chat-row__avatar agent-chat-row__avatar--bot">
          <span class="material-symbols-outlined text-sm">smart_toy</span>
        </div>
        <div class="agent-chat-row__bubble agent-chat-row__bubble--assistant">
          <div class="agent-chat-generating">
            <span class="material-symbols-outlined text-sm agent-chat-generating__spin">sync</span>
            <span>Generating…</span>
          </div>
          <div class="agent-chat-generating__dots" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>`;
  }
  return `<div class="agent-chat-bubble agent-chat-bubble--assistant agent-chat-bubble--loading" aria-live="polite" aria-busy="true">
        <span class="agent-chat-role">Assistant</span>
        <div class="agent-chat-generating">
          <span class="agent-chat-spinner" aria-hidden="true"></span>
          <span>Generating…</span>
        </div>
      </div>`;
}

function assistantBubbleHtml(m, idx) {
  const body = wrapTables(renderMarkdown(m.text));
  if (isStitchAvatarChat()) {
    return `<div class="agent-chat-row agent-chat-row--assistant">
        <div class="agent-chat-row__avatar agent-chat-row__avatar--bot">
          <span class="material-symbols-outlined text-sm">smart_toy</span>
        </div>
        <div class="agent-chat-row__bubble agent-chat-row__bubble--assistant">
          <div class="agent-chat-bubble-actions">
            <button type="button" class="agent-chat-copy-btn" data-copy-index="${idx}" aria-label="Copy response">
              <span class="material-symbols-outlined text-sm">content_copy</span>
              <span class="agent-chat-copy-label">Copy</span>
            </button>
          </div>
          <div class="agent-chat-md">${body}</div>
        </div>
      </div>`;
  }
  return `<div class="agent-chat-bubble agent-chat-bubble--assistant">
        <div class="agent-chat-bubble-actions">
          <span class="agent-chat-role">Assistant</span>
          <button type="button" class="agent-chat-copy-btn" data-copy-index="${idx}" aria-label="Copy response">
            <i class="bi bi-clipboard" aria-hidden="true"></i><span class="agent-chat-copy-label">Copy</span>
          </button>
        </div>
        <div class="agent-chat-md">${body}</div>
      </div>`;
}

function userBubbleHtml(m) {
  const textBlock = m.text
    ? `<div class="agent-chat-text">${escapeChat(m.text).replace(/\n/g, "<br>")}</div>`
    : "";
  if (isStitchAvatarChat()) {
    return `<div class="agent-chat-row agent-chat-row--user">
        <div class="agent-chat-row__bubble agent-chat-row__bubble--user">
          ${textBlock}
          ${attachmentsHtml(m.attachments)}
        </div>
        <div class="agent-chat-row__avatar agent-chat-row__avatar--user">
          <span class="material-symbols-outlined text-sm">person</span>
        </div>
      </div>`;
  }
  return `<div class="agent-chat-bubble agent-chat-bubble--user">
        <span class="agent-chat-role">You</span>
        ${textBlock}
        ${attachmentsHtml(m.attachments)}
      </div>`;
}

async function renderMessages(messages, { generating = false } = {}) {
  const log = document.getElementById("agent-chat-log");
  if (!log) return;
  if (!messages.length && !generating) {
    log.innerHTML = isStitchAvatarChat()
      ? '<p class="agent-chat-empty">Ask about the report or attach a file.</p>'
      : '<p class="text-secondary small mb-0">Ask about the report or attach a file.</p>';
    return;
  }
  const bubbles = messages
    .map((m, idx) => (m.role === "user" ? userBubbleHtml(m) : assistantBubbleHtml(m, idx)))
    .join("");
  log.innerHTML = bubbles + (generating ? loadingBubbleHtml() : "");
  await renderMermaidBlocks(log);
  log.scrollTop = log.scrollHeight;
}

function showFileError(message) {
  const el = document.getElementById("agent-chat-file-error");
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = message;
}

function renderPendingFiles() {
  const wrap = document.getElementById("agent-chat-pending-files");
  if (!wrap) return;
  if (!pendingFiles.length) {
    wrap.hidden = true;
    wrap.innerHTML = "";
    return;
  }
  wrap.hidden = false;
  wrap.innerHTML = pendingFiles
    .map(
      (f, idx) =>
        `<span class="agent-chat-file-chip"><i class="bi bi-file-earmark" aria-hidden="true"></i>${escapeChat(f.name)}<button type="button" data-remove-file="${idx}" aria-label="Remove ${escapeChat(f.name)}">&times;</button></span>`
    )
    .join("");
  showFileError("");
}

function isAcceptedFile(file) {
  const name = (file.name || "").toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function addPendingFiles(fileList) {
  const errors = [];
  for (const file of fileList) {
    if (!isAcceptedFile(file)) {
      errors.push(`${file.name}: use .json, .txt, .log, .md, .csv, .yaml, or .yml`);
      continue;
    }
    if (pendingFiles.some((p) => p.name === file.name && p.size === file.size)) {
      continue;
    }
    pendingFiles.push(file);
  }
  renderPendingFiles();
  if (errors.length) {
    showFileError(errors.join(" "));
  }
  return errors;
}

async function copyMessageText(index, button) {
  const text = cachedMessages[index]?.text;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
  const label = button.querySelector(".agent-chat-copy-label");
  const icon = button.querySelector(".bi");
  const materialIcon = button.querySelector(".material-symbols-outlined");
  button.classList.add("agent-chat-copy-btn--copied");
  if (label) label.textContent = "Copied!";
  if (icon) {
    icon.classList.remove("bi-clipboard");
    icon.classList.add("bi-check2");
  }
  if (materialIcon) materialIcon.textContent = "check";
  window.setTimeout(() => {
    button.classList.remove("agent-chat-copy-btn--copied");
    if (label) label.textContent = "Copy";
    if (icon) {
      icon.classList.add("bi-clipboard");
      icon.classList.remove("bi-check2");
    }
    if (materialIcon) materialIcon.textContent = "content_copy";
  }, 2000);
}

function setAttachEnabled(enabled) {
  const label = document.getElementById("agent-chat-attach-label");
  if (!label) return;
  if (enabled) {
    label.setAttribute("for", "agent-chat-file");
    label.classList.remove("disabled");
    label.removeAttribute("aria-disabled");
  } else {
    label.removeAttribute("for");
    label.classList.add("disabled");
    label.setAttribute("aria-disabled", "true");
  }
}

function setComposerBusy(busy) {
  chatLoading = busy;
  const input = document.getElementById("agent-chat-input");
  const btn = document.querySelector("#agent-chat-form button[type=submit]");
  if (input) input.disabled = busy;
  setAttachEnabled(!busy);
  if (btn) {
    btn.disabled = busy;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
  }
}

async function loadChatbot() {
  if (!chatRunId) return;
  const llm = getLlmFn();
  try {
    const resp = await fetch(
      `/simagix/runs/${chatRunId}/phase2/chatbot?llm=${encodeURIComponent(llm)}`
    );
    if (resp.status === 404) {
      cachedMessages = [];
      await renderMessages([]);
      return;
    }
    if (!resp.ok) return;
    const data = await resp.json();
    cachedMessages = normalizeMessages(data);
    await renderMessages(cachedMessages);
  } catch {
    /* offline */
  }
}

async function uploadChatAttachment(file) {
  const llm = getLlmFn();
  const form = new FormData();
  form.append("file", file, file.name);
  const resp = await fetch(
    `/simagix/runs/${chatRunId}/phase2/chatbot/attachments?llm=${encodeURIComponent(llm)}`,
    { method: "POST", body: form }
  );
  const { data, text } = window.MdbVerbatimError
    ? await window.MdbVerbatimError.readResponseBody(resp)
    : { data: await resp.json().catch(() => null), text: "" };
  if (!resp.ok) {
    throw new Error(
      window.MdbVerbatimError
        ? window.MdbVerbatimError.errorFromBody(resp, data, text, `Failed to upload ${file.name}`)
        : data?.detail || text || `Failed to upload ${file.name}`
    );
  }
  return { name: data.name, path: data.path, size: data.size };
}

async function sendChatMessage(text, files = []) {
  const trimmed = text.trim();
  if ((!trimmed && !files.length) || chatLoading) return;

  const llm = getLlmFn();
  const optimisticAttachments = files.map((f) => ({ name: f.name, path: "", size: f.size }));
  const optimistic = [
    ...cachedMessages,
    { role: "user", text: trimmed, attachments: optimisticAttachments },
  ];
  await renderMessages(optimistic, { generating: true });
  setComposerBusy(true);

  try {
    let content = trimmed;
    const uploaded = [];
    for (const file of files) {
      uploaded.push(await uploadChatAttachment(file));
    }

    const enabledMcpIds =
      window.FtdcRca && typeof window.FtdcRca.selectedChatbotMcpIds === "function"
        ? window.FtdcRca.selectedChatbotMcpIds()
        : [];
    const resp = await fetch(
      `/simagix/runs/${chatRunId}/phase2/chatbot/messages?llm=${encodeURIComponent(llm)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content,
          attachments: uploaded,
          enabled_mcp_ids: enabledMcpIds,
        }),
      }
    );
    const { data, text } = window.MdbVerbatimError
      ? await window.MdbVerbatimError.readResponseBody(resp)
      : { data: await resp.json().catch(() => null), text: "" };
    if (!resp.ok) {
      throw new Error(
        window.MdbVerbatimError
          ? window.MdbVerbatimError.errorFromBody(resp, data, text, "Chatbot request failed")
          : data?.detail || text || "Chatbot request failed"
      );
    }

    pendingFiles = [];
    renderPendingFiles();
    await loadChatbot();
  } catch (err) {
    cachedMessages = [
      ...optimistic,
      { role: "assistant", text: `Error: ${err.message}`, attachments: [] },
    ];
    await renderMessages(cachedMessages);
  } finally {
    setComposerBusy(false);
  }
}

function showChatPanel(show) {
  const panel = document.getElementById("agent-chat-panel");
  if (panel) panel.hidden = !show;
  if (!show) setChatbotMcpPickerOpen(false);
}

function isStitchChatPage() {
  return Boolean(document.getElementById("btn-chatbot"));
}

function setChatbotMcpPickerOpen(open) {
  const inline = document.getElementById("chatbot-mcp-panel");
  const modal = document.getElementById("chatbot-mcp-modal");
  const btn = document.getElementById("agent-chat-mcp-btn");
  const target = inline || modal;
  if (!target) return;

  target.hidden = !open;
  target.setAttribute("aria-hidden", open ? "false" : "true");
  if (inline) {
    inline.classList.toggle("hidden", !open);
  } else if (isStitchChatPage()) {
    modal.classList.toggle("hidden", !open);
    document.body.classList.toggle("chatbot-mcp-modal-open", open);
  } else {
    document.body.classList.toggle("chatbot-mcp-modal-open", open);
  }
  btn?.setAttribute("aria-expanded", open ? "true" : "false");
  btn?.classList.toggle("is-active", open);
}

function bindChatbotMcpPicker() {
  const mcpBtn = document.getElementById("agent-chat-mcp-btn");
  const mcpClose = document.getElementById("chatbot-mcp-close");
  const mcpBackdrop = document.getElementById("chatbot-mcp-backdrop");
  const inline = document.getElementById("chatbot-mcp-panel");
  const modal = document.getElementById("chatbot-mcp-modal");
  const target = inline || modal;
  if (!mcpBtn || !target || mcpBtn.dataset.mcpBound === "1") return;
  mcpBtn.dataset.mcpBound = "1";

  mcpBtn.addEventListener("click", (e) => {
    e.preventDefault();
    setChatbotMcpPickerOpen(Boolean(target.hidden));
  });
  mcpClose?.addEventListener("click", (e) => {
    e.preventDefault();
    setChatbotMcpPickerOpen(false);
  });
  mcpBackdrop?.addEventListener("click", () => setChatbotMcpPickerOpen(false));
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || target.hidden) return;
    setChatbotMcpPickerOpen(false);
  });
}

function bindAgentChatComposer() {
  if (composerBound) return;
  const form = document.getElementById("agent-chat-form");
  const input = document.getElementById("agent-chat-input");
  const log = document.getElementById("agent-chat-log");
  const fileInput = document.getElementById("agent-chat-file");
  const attachLabel = document.getElementById("agent-chat-attach-label");
  const pendingWrap = document.getElementById("agent-chat-pending-files");
  if (!form || !fileInput) return;

  composerBound = true;
  bindChatbotMcpPicker();

  log?.addEventListener("click", (e) => {
    const btn = e.target.closest(".agent-chat-copy-btn");
    if (!btn) return;
    const idx = Number(btn.dataset.copyIndex);
    if (Number.isNaN(idx)) return;
    copyMessageText(idx, btn);
  });

  pendingWrap?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-file]");
    if (!btn) return;
    const idx = Number(btn.dataset.removeFile);
    if (Number.isNaN(idx)) return;
    pendingFiles.splice(idx, 1);
    renderPendingFiles();
  });

  attachLabel?.addEventListener("click", (e) => {
    if (chatLoading) {
      e.preventDefault();
      e.stopPropagation();
    }
  });

  attachLabel?.addEventListener("keydown", (e) => {
    if (chatLoading) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    if (!fileInput.files?.length) return;
    addPendingFiles(fileInput.files);
    fileInput.value = "";
  });

  input?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    if (chatLoading || input.disabled) return;
    form.requestSubmit();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!input) return;
    const text = input.value;
    const files = [...pendingFiles];
    input.value = "";
    await sendChatMessage(text, files);
    input.focus();
  });
}

function initAgentChat(runId, getLlm, options = {}) {
  chatRunId = runId;
  if (typeof getLlm === "function") getLlmFn = getLlm;

  bindAgentChatComposer();

  if (options.hasReport) {
    showChatPanel(true);
    loadChatbot();
  }
}

function setReportContext(data) {
  if (data?.run_id) chatRunId = data.run_id;
}

function onRcaCompleted(getLlm) {
  if (typeof getLlm === "function") getLlmFn = getLlm;
  bindAgentChatComposer();
  showChatPanel(true);
  loadChatbot();
}

function onRcaReset() {
  showChatPanel(false);
  setChatbotMcpPickerOpen(false);
  pendingFiles = [];
  renderPendingFiles();
  showFileError("");
}

function refreshChatForLlm() {
  if (!document.getElementById("agent-chat-panel")?.hidden) {
    loadChatbot();
  }
}

window.FtdcAgentChat = {
  init: initAgentChat,
  setReportContext,
  onCompleted: onRcaCompleted,
  onReset: onRcaReset,
  refresh: refreshChatForLlm,
  load: loadChatbot,
};
