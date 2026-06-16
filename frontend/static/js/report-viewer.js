/**
 * Interactive RCA report — scroll sections, causal chain SVG, section nav.
 * Consumes GET /simagix/runs/:id/phase2/reports/latest (JSON).
 */

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatConfidence(confidence) {
  if (confidence == null || Number.isNaN(Number(confidence))) return null;
  const pct = Math.round(Number(confidence) * 100);
  return Math.max(0, Math.min(100, pct));
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function sectionHtml(id, title, icon, bodyHtml, extraClass = "") {
  return `
    <article class="rv-section ${extraClass}" id="rv-${id}" data-rv-section data-rv-nav="${id}">
      <div class="rv-section-inner">
        <header class="rv-section-head">
          <span class="rv-section-icon" aria-hidden="true"><i class="bi bi-${icon}"></i></span>
          <h3 class="rv-section-title">${escapeHtml(title)}</h3>
        </header>
        <div class="rv-section-body">${bodyHtml}</div>
      </div>
    </article>`;
}

function buildMetaChips(data) {
  const chips = [];
  if (data.provider) chips.push(`<span class="rv-chip">${escapeHtml(data.provider)}</span>`);
  if (data.agent_id) chips.push(`<span class="rv-chip rv-chip--muted">${escapeHtml(data.agent_id)}</span>`);
  const usage = data.tool_usage;
  if (usage?.total_sdk_calls) {
    chips.push(`<span class="rv-chip rv-chip--tools">${usage.total_sdk_calls} tool calls</span>`);
  }
  return chips.length ? `<div class="rv-meta-chips">${chips.join("")}</div>` : "";
}

function buildTimeline(events) {
  if (!events?.length) return '<p class="text-secondary small mb-0">No timeline events.</p>';
  return `<div class="rv-timeline">
    ${events
      .map(
        (ev, i) => `
      <div class="rv-timeline-item" style="--rv-stagger:${i}">
        <div class="rv-timeline-dot"></div>
        <div class="rv-timeline-card">
          <div class="rv-timeline-window">${escapeHtml(ev.time_window || "—")}</div>
          <p class="rv-timeline-obs mb-1">${escapeHtml(ev.observation || "")}</p>
          <p class="rv-timeline-mech small text-secondary mb-0">${escapeHtml(ev.mechanism || "")}</p>
          ${
            ev.metrics_involved?.length
              ? `<div class="rv-timeline-metrics mt-2">${ev.metrics_involved
                  .map((m) => `<span class="rv-metric-tag">${escapeHtml(m)}</span>`)
                  .join("")}</div>`
              : ""
          }
        </div>
      </div>`
      )
      .join("")}
  </div>`;
}

function buildFindings(analyses) {
  if (!analyses?.length) return '<p class="text-secondary small mb-0">No finding analyses.</p>';
  return `<div class="rv-findings">
    ${analyses
      .map(
        (fa) => `
      <div class="rv-finding-card">
        <div class="rv-finding-name">${escapeHtml(fa.finding_name || "Finding")}</div>
        ${fa.time_window ? `<div class="rv-finding-window small text-secondary">${escapeHtml(fa.time_window)}</div>` : ""}
        <div class="rv-finding-row"><span class="rv-finding-label">What</span><p>${escapeHtml(fa.what_observed || "")}</p></div>
        <div class="rv-finding-row"><span class="rv-finding-label">Why</span><p>${escapeHtml(fa.why_it_happened || "")}</p></div>
      </div>`
      )
      .join("")}
  </div>`;
}

function buildCausalChain(steps) {
  if (!steps?.length) return '<p class="text-secondary small mb-0">No causal chain steps.</p>';
  const nodes = steps
    .map(
      (step, i) => `
    <div class="rv-chain-node" data-chain-index="${i}" style="--chain-i:${i}">
      <div class="rv-chain-marker" data-chain-marker>
        <span class="rv-chain-num">${i + 1}</span>
      </div>
      <div class="rv-chain-card">
        <p class="rv-chain-text mb-0">${escapeHtml(step)}</p>
      </div>
    </div>`
    )
    .join("");

  return `
    <div class="rv-chain" id="rv-causal-chain">
      <svg class="rv-chain-svg" aria-hidden="true">
        <defs>
          <linearGradient id="rv-chain-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#00ed64" stop-opacity="0.9"/>
            <stop offset="100%" stop-color="#13aa52" stop-opacity="0.35"/>
          </linearGradient>
        </defs>
        <path class="rv-chain-path" fill="none" stroke="url(#rv-chain-gradient)" stroke-width="2.5" stroke-linecap="round"/>
      </svg>
      <div class="rv-chain-nodes">${nodes}</div>
    </div>`;
}

function buildList(items) {
  if (!items?.length) return '<p class="text-secondary small mb-0">None listed.</p>';
  return `<ul class="rv-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function buildEvidence(citations) {
  if (!citations?.length) return '<p class="text-secondary small mb-0">No citations.</p>';
  return `<div class="rv-evidence">
    ${citations
      .map(
        (c) => `
      <div class="rv-evidence-card">
        <span class="rv-evidence-type">${escapeHtml(c.source_type || "source")}</span>
        <div class="rv-evidence-ref">${escapeHtml(c.reference || "")}</div>
        <p class="small mb-0 text-secondary">${escapeHtml(c.summary || "")}</p>
      </div>`
      )
      .join("")}
  </div>`;
}

function buildNav(sections) {
  return `<nav class="rv-nav rv-nav--side" aria-label="Report sections">
    <div class="rv-nav-label">Sections</div>
    <ol class="rv-nav-list">
      ${sections.map((s) => `<li><a href="#rv-${s.id}" data-rv-link="${s.id}">${escapeHtml(s.label)}</a></li>`).join("")}
    </ol>
  </nav>`;
}

function buildReportDom(data) {
  const report = data.report || {};
  const confidence = formatConfidence(report.confidence);
  const sections = [];
  const parts = [];

  parts.push(`
    <div class="rv-hero" id="rv-hero" data-rv-section data-rv-nav="hero">
      ${buildMetaChips(data)}
      <div class="rv-hero-grid">
        <div class="rv-hero-main">
          <span class="rv-hero-kicker">Root cause</span>
          <p class="rv-hero-rc">${escapeHtml(report.root_cause || "—")}</p>
        </div>
        ${
          confidence != null
            ? `<div class="rv-confidence" style="--rv-conf:${confidence}">
            <div class="rv-confidence-ring" aria-label="Confidence ${confidence}%">
              <span class="rv-confidence-value">${confidence}%</span>
            </div>
            <span class="rv-confidence-label">Confidence</span>
          </div>`
            : ""
        }
      </div>
    </div>`);
  sections.push({ id: "hero", label: "Root cause" });

  if (report.summary) {
    sections.push({ id: "summary", label: "Summary" });
    parts.push(sectionHtml("summary", "Summary", "card-text", `<p class="mb-0">${escapeHtml(report.summary)}</p>`));
  }

  if (report.mechanism_summary) {
    sections.push({ id: "mechanism", label: "Mechanism" });
    parts.push(
      sectionHtml(
        "mechanism",
        "Mechanism (why)",
        "gear-wide-connected",
        `<p class="mb-0">${escapeHtml(report.mechanism_summary)}</p>`,
        "rv-section--accent"
      )
    );
  }

  if (report.incident_timeline?.length) {
    sections.push({ id: "timeline", label: "Timeline" });
    parts.push(sectionHtml("timeline", "Incident timeline", "clock-history", buildTimeline(report.incident_timeline)));
  }

  if (report.finding_analyses?.length) {
    sections.push({ id: "findings", label: "Findings" });
    parts.push(
      sectionHtml("findings", "Finding analyses", "search", buildFindings(report.finding_analyses), "rv-section--wide")
    );
  }

  if (report.causal_chain?.length) {
    sections.push({ id: "chain", label: "Causal chain" });
    parts.push(
      sectionHtml("chain", "Causal chain", "diagram-3", buildCausalChain(report.causal_chain), "rv-section--chain")
    );
  }

  if (report.evidence_citations?.length) {
    sections.push({ id: "evidence", label: "Evidence" });
    parts.push(sectionHtml("evidence", "Evidence", "shield-check", buildEvidence(report.evidence_citations)));
  }

  if (report.safe_fixes?.length) {
    sections.push({ id: "fixes", label: "Fixes" });
    parts.push(sectionHtml("fixes", "Safe fixes", "wrench-adjustable", buildList(report.safe_fixes)));
  }

  if (report.ruled_out_hypotheses?.length) {
    sections.push({ id: "ruled-out", label: "Ruled out" });
    parts.push(
      sectionHtml("ruled-out", "Ruled out", "x-octagon", buildList(report.ruled_out_hypotheses), "rv-section--muted")
    );
  }

  return `<div class="rv-layout">
    ${buildNav(sections)}
    <div class="rv-stack">${parts.join("")}</div>
  </div>`;
}

function drawCausalChainPath() {
  const chain = document.getElementById("rv-causal-chain");
  if (!chain) return;

  const pathEl = chain.querySelector(".rv-chain-path");
  const markers = [...chain.querySelectorAll("[data-chain-marker]")];
  if (!pathEl || markers.length < 2) {
    if (pathEl) pathEl.setAttribute("d", "");
    return;
  }

  const chainRect = chain.getBoundingClientRect();
  const points = markers.map((marker) => {
    const r = marker.getBoundingClientRect();
    return {
      x: r.left + r.width / 2 - chainRect.left,
      y: r.top + r.height / 2 - chainRect.top,
    };
  });

  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1];
    const curr = points[i];
    const midY = (prev.y + curr.y) / 2;
    d += ` C ${prev.x} ${midY}, ${curr.x} ${midY}, ${curr.x} ${curr.y}`;
  }

  pathEl.setAttribute("d", d);
  const length = pathEl.getTotalLength();
  pathEl.style.strokeDasharray = `${length}`;
  pathEl.style.strokeDashoffset = `${length}`;
  requestAnimationFrame(() => {
    pathEl.classList.add("rv-chain-path--drawn");
    pathEl.style.strokeDashoffset = "0";
  });
}

let sectionObserver = null;
let navObserver = null;
let chainResizeObserver = null;
let lastReportData = null;

function initReportObservers(root) {
  if (sectionObserver) sectionObserver.disconnect();
  if (navObserver) navObserver.disconnect();
  if (chainResizeObserver) chainResizeObserver.disconnect();

  const prefersReduced = prefersReducedMotion();

  sectionObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("rv-in-view");
          if (entry.target.closest("#rv-causal-chain")) {
            requestAnimationFrame(drawCausalChainPath);
          }
        }
      }
    },
    { rootMargin: "-6% 0px -6% 0px", threshold: 0.1 }
  );

  root.querySelectorAll(".rv-section, .rv-hero, .rv-chain-node, .rv-timeline-item, .rv-finding-card, .rv-evidence-card").forEach(
    (el) => {
      if (prefersReduced) {
        el.classList.add("rv-in-view");
      } else {
        sectionObserver.observe(el);
      }
    }
  );

  const navLinks = root.querySelectorAll("[data-rv-link]");
  const navSections = root.querySelectorAll("[data-rv-section]");

  if (navLinks.length && navSections.length) {
    navObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        const id = visible.target.getAttribute("data-rv-nav");
        navLinks.forEach((link) => {
          link.classList.toggle("is-active", link.getAttribute("data-rv-link") === id);
        });
      },
      { rootMargin: "-18% 0px -55% 0px", threshold: [0, 0.25, 0.5] }
    );
    navSections.forEach((s) => navObserver.observe(s));
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const id = link.getAttribute("data-rv-link");
      const target = root.querySelector(`#rv-${id}`);
      if (target) window.FtdcMotion?.scrollTo(target);
    });
  });

  const chain = root.querySelector("#rv-causal-chain");
  if (chain && typeof ResizeObserver !== "undefined") {
    chainResizeObserver = new ResizeObserver(() => drawCausalChainPath());
    chainResizeObserver.observe(chain);
  }
  drawCausalChainPath();
}

function renderReportPayload(data, container) {
  if (!container) return;
  lastReportData = data;
  container.removeAttribute("hidden");
  container.classList.remove("report-viewer--3d");
  container.innerHTML = buildReportDom(data);
  initReportObservers(container);
  window.FtdcAgentChat?.setReportContext?.(data);

  const rawEl = document.getElementById("saved-report-raw");
  if (rawEl && data.report_text) {
    rawEl.textContent = data.report_text;
  }
}

async function loadAndRender(runId, llm, container) {
  if (!container || !runId) return false;
  const url = `/simagix/runs/${runId}/phase2/reports/latest?llm=${encodeURIComponent(llm)}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    container.innerHTML = "";
    container.setAttribute("hidden", "");
    return false;
  }
  const data = await resp.json();
  renderReportPayload(data, container);
  return true;
}

function clearReport(container) {
  if (!container) return;
  lastReportData = null;
  container.innerHTML = "";
  container.setAttribute("hidden", "");
  container.classList.remove("report-viewer--3d");
}

function getLastReportData() {
  return lastReportData;
}

window.FtdcReportViewer = {
  render: renderReportPayload,
  load: loadAndRender,
  clear: clearReport,
  getLastReportData,
};
