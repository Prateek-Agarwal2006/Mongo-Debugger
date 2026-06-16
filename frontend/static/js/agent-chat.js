/**
 * Post-report agentic chatbot — backend persistence via /phase2/chatbot API.
 * Assistant replies: GFM markdown + mermaid; copy-to-clipboard per message.
 */

let chatRunId = null;
let getLlmFn = () => "mock";
let chatLoading = false;
let cachedMessages = [];
let mermaidReady = false;

function escapeChat(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function ensureMermaid() {
  if (mermaidReady || typeof mermaid === "undefined") return;
  mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
  mermaidReady = true;
}

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
  }));
}

function loadingBubbleHtml() {
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
  return `<div class="agent-chat-bubble agent-chat-bubble--user">
        <span class="agent-chat-role">You</span>
        <div class="agent-chat-text">${escapeChat(m.text).replace(/\n/g, "<br>")}</div>
      </div>`;
}

async function renderMessages(messages, { generating = false } = {}) {
  const log = document.getElementById("agent-chat-log");
  if (!log) return;
  if (!messages.length && !generating) {
    log.innerHTML =
      '<p class="text-secondary small mb-0">Ask about the report, paste profiler JSON, or request deeper analysis.</p>';
    return;
  }
  const bubbles = messages
    .map((m, idx) => (m.role === "user" ? userBubbleHtml(m) : assistantBubbleHtml(m, idx)))
    .join("");
  log.innerHTML = bubbles + (generating ? loadingBubbleHtml() : "");
  await renderMermaidBlocks(log);
  log.scrollTop = log.scrollHeight;
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
  button.classList.add("agent-chat-copy-btn--copied");
  if (label) label.textContent = "Copied!";
  if (icon) {
    icon.classList.remove("bi-clipboard");
    icon.classList.add("bi-check2");
  }
  window.setTimeout(() => {
    button.classList.remove("agent-chat-copy-btn--copied");
    if (label) label.textContent = "Copy";
    if (icon) {
      icon.classList.add("bi-clipboard");
      icon.classList.remove("bi-check2");
    }
  }, 2000);
}

function setComposerBusy(busy) {
  chatLoading = busy;
  const input = document.getElementById("agent-chat-input");
  const btn = document.querySelector("#agent-chat-form button[type=submit]");
  if (input) input.disabled = busy;
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

async function tryProfilerUpload(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!Array.isArray(parsed)) return null;

  const resp = await fetch(`/simagix/runs/${chatRunId}/phase2/profiler`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parsed),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || "Profiler upload failed");
  }
  return `Profiler data saved (${data.sample_count ?? parsed.length} samples).`;
}

async function sendChatMessage(text) {
  const trimmed = text.trim();
  if (!trimmed || chatLoading) return;

  const llm = getLlmFn();
  const optimistic = [...cachedMessages, { role: "user", text: trimmed }];
  await renderMessages(optimistic, { generating: true });
  setComposerBusy(true);
  try {
    let content = trimmed;
    const profilerNote = await tryProfilerUpload(trimmed);
    if (profilerNote) {
      content = `${trimmed}\n\n[Profiler upload: ${profilerNote}]`;
    }
    const resp = await fetch(
      `/simagix/runs/${chatRunId}/phase2/chatbot/messages?llm=${encodeURIComponent(llm)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      }
    );
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || "Chatbot request failed");
    }
    await loadChatbot();
  } catch (err) {
    cachedMessages = [
      ...optimistic,
      { role: "assistant", text: `Error: ${err.message}` },
    ];
    await renderMessages(cachedMessages);
  } finally {
    setComposerBusy(false);
  }
}

function showChatPanel(show) {
  const panel = document.getElementById("agent-chat-panel");
  if (panel) panel.hidden = !show;
}

function initAgentChat(runId, getLlm, options = {}) {
  chatRunId = runId;
  if (typeof getLlm === "function") getLlmFn = getLlm;

  const form = document.getElementById("agent-chat-form");
  const input = document.getElementById("agent-chat-input");
  const log = document.getElementById("agent-chat-log");

  log?.addEventListener("click", (e) => {
    const btn = e.target.closest(".agent-chat-copy-btn");
    if (!btn) return;
    const idx = Number(btn.dataset.copyIndex);
    if (Number.isNaN(idx)) return;
    copyMessageText(idx, btn);
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!input) return;
    const text = input.value;
    input.value = "";
    await sendChatMessage(text);
    input.focus();
  });

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
  showChatPanel(true);
  loadChatbot();
}

function onRcaReset() {
  showChatPanel(false);
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
