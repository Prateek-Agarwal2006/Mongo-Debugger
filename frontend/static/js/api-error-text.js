/** Show API / job errors verbatim — no detail.msg parsing or summarizing. */
(function () {
  async function readResponseBody(resp) {
    const text = await resp.text();
    if (!text.trim()) return { data: null, text: "" };
    try {
      return { data: JSON.parse(text), text };
    } catch {
      return { data: null, text };
    }
  }

  function verbatimDetail(payload) {
    if (payload == null) return "";
    if (typeof payload === "string") return payload;
    if (payload instanceof Error) return payload.message || String(payload);
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail !== undefined && payload.detail !== null) {
      return typeof payload.detail === "object"
        ? JSON.stringify(payload.detail, null, 2)
        : String(payload.detail);
    }
    if (typeof payload.error === "string") return payload.error;
    return JSON.stringify(payload, null, 2);
  }

  function showInPre(preId, text) {
    const el = document.getElementById(preId);
    if (!el || !text) return;
    el.textContent = text;
    el.hidden = false;
    el.classList.remove("hidden");
  }

  function errorFromBody(resp, data, text, fallback) {
    const detail = verbatimDetail(data ?? text);
    if (detail) return detail;
    if (fallback) return fallback;
    return "Request failed (" + resp.status + ")";
  }

  window.MdbVerbatimError = { verbatimDetail, showInPre, readResponseBody, errorFromBody };
})();
