/** Read #mdb-page-data and fetch job records without brittle JSON-in-HTML parsing. */
(function () {
  function pageDataEl() {
    return (
      document.getElementById("mdb-page-data") ||
      window.parent?.document?.getElementById("mdb-page-data") ||
      null
    );
  }

  function readPageData() {
    const el = pageDataEl();
    if (!el?.textContent?.trim()) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      console.warn("mdb-page-data JSON.parse failed", err);
      return null;
    }
  }

  function readEmbeddedJobError() {
    const doc = window.parent?.document || document;
    const jsonEl = doc.getElementById("mdb-job-error-json");
    if (jsonEl?.textContent?.trim()) {
      try {
        const parsed = JSON.parse(jsonEl.textContent);
        if (typeof parsed === "string") return parsed;
        return JSON.stringify(parsed, null, 2);
      } catch (err) {
        console.warn("mdb-job-error-json parse failed", err);
      }
    }
    const tpl = doc.getElementById("mdb-job-error");
    if (!tpl) return null;
    if (tpl.content) {
      const text = tpl.content.textContent;
      return text ? text : null;
    }
    const text = tpl.textContent;
    return text ? text : null;
  }

  async function fetchJob(jobId) {
    const resp = await fetch("/simagix/uploads/jobs/" + encodeURIComponent(jobId));
    const text = await resp.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      const snippet = text.trim().slice(0, 4000);
      throw new Error(snippet || "Job request failed (" + resp.status + ", non-JSON body)");
    }
    if (!resp.ok) {
      const detail = window.MdbVerbatimError
        ? window.MdbVerbatimError.verbatimDetail(data)
        : text;
      throw new Error(detail || "Job request failed (" + resp.status + ")");
    }
    return data;
  }

  window.MdbPageData = { readPageData, readEmbeddedJobError, fetchJob };
})();
