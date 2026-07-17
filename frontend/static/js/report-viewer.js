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

function isStitchReportViewer(container) {
  return container?.classList?.contains("report-viewer--stitch");
}

function buildStitchNav(sections) {
  return `<nav class="report-stitch-nav space-y-3" aria-label="Report sections">
    ${sections
      .map(
        (s, i) =>
          `<a href="#section-${s.id}" data-rv-link="${s.id}"${i === 0 ? " class=\"is-active\"" : ""}>` +
          `${i === 0 ? '<span class="report-stitch-nav-dot"></span>' : ""}${escapeHtml(s.label)}</a>`
      )
      .join("")}
  </nav>`;
}

function buildStitchConfidenceRing(pct) {
  const circumference = 2 * Math.PI * 40;
  const offset = circumference * (1 - pct / 100);
  return `
    <div class="report-stitch-confidence">
      <div class="report-stitch-confidence-ring" aria-label="Confidence ${pct}%">
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="40" fill="none" stroke="#EDEEE8" stroke-width="8"></circle>
          <circle cx="50" cy="50" r="40" fill="none" stroke="#c96442" stroke-width="8"
            stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round"></circle>
        </svg>
        <span class="report-stitch-confidence-value">${pct}%</span>
      </div>
      <span class="report-stitch-confidence-label">Confidence</span>
    </div>`;
}

function buildStitchParagraph(text) {
  const raw = String(text ?? "").trim();
  if (!raw) return "";
  return `<p class="report-stitch-p">${escapeHtml(raw)}</p>`;
}

/** Bullets only when the value is already split (newlines in JSON string). */
function buildStitchTextBlock(text) {
  const raw = String(text ?? "").trim();
  if (!raw) return "";
  const lines = raw
    .split(/\n+/)
    .map((s) => s.replace(/^[-*•]\s*/, "").trim())
    .filter(Boolean);
  if (lines.length > 1) {
    return `<ul class="report-stitch-list">${lines
      .map((line) => `<li>${escapeHtml(line)}</li>`)
      .join("")}</ul>`;
  }
  return buildStitchParagraph(raw);
}

function buildStitchLabelledBlock(label, text) {
  if (!String(text ?? "").trim()) return "";
  return `
    <div class="report-stitch-labelled-block">
      <span class="report-stitch-labelled-heading">${escapeHtml(label)}</span>
      ${buildStitchTextBlock(text)}
    </div>`;
}

function buildStitchSummary(text) {
  return buildStitchTextBlock(text);
}

function buildStitchCausalChain(steps) {
  if (!steps?.length) return '<p class="report-stitch-empty">No causal chain steps.</p>';
  const last = steps.length - 1;
  return `
    <div class="report-stitch-causal-box">
      <div class="report-stitch-causal-line" aria-hidden="true"></div>
      <div class="space-y-6">
        ${steps
          .map((step, i) => {
            const impact = i === last;
            return `
          <div class="report-stitch-causal-step${impact ? " is-impact" : ""}">
            <div class="report-stitch-causal-num">${i + 1}</div>
            <div>
              <h4>${impact ? "Observable impact" : `Step ${i + 1}`}</h4>
              ${buildStitchParagraph(step)}
            </div>
          </div>`;
          })
          .join("")}
      </div>
    </div>`;
}

function buildStitchTimeline(events) {
  if (!events?.length) return '<p class="report-stitch-empty">No timeline events.</p>';
  return `<div class="report-stitch-timeline">
    ${events
      .map((ev) => {
        const alert = /fail|error|timeout|critical/i.test(ev.observation || "");
        const metrics = ev.metrics_involved?.length
          ? `<div class="report-stitch-timeline-metrics">${ev.metrics_involved
              .map((m) => `<span class="report-stitch-metric-tag">${escapeHtml(m)}</span>`)
              .join("")}</div>`
          : "";
        return `
        <div class="report-stitch-timeline-item${alert ? " is-alert" : ""}">
          <div class="report-stitch-timeline-dot"></div>
          <div class="report-stitch-timeline-time">${escapeHtml(ev.time_window || "—")}</div>
          ${buildStitchLabelledBlock("Observed", ev.observation)}
          ${ev.mechanism ? buildStitchLabelledBlock("Mechanism", ev.mechanism) : ""}
          ${metrics}
        </div>`;
      })
      .join("")}
  </div>`;
}

function chartImgHtml(runId, chartId, caption) {
  if (!runId || !chartId) return "";
  const src = `/simagix/runs/${encodeURIComponent(runId)}/phase2/charts/${encodeURIComponent(chartId)}`;
  return `
    <figure class="report-stitch-chart">
      <img src="${src}" alt="${escapeHtml(caption || "Metric chart")}" loading="lazy"
        style="width:100%;border-radius:12px;border:1px solid rgba(0,0,0,0.08);background:#fff;"/>
      ${caption ? `<figcaption class="report-stitch-finding-window" style="margin-top:6px;">${escapeHtml(caption)}</figcaption>` : ""}
    </figure>`;
}

function buildStitchFindings(analyses, runId, charts) {
  if (!analyses?.length) return '<p class="report-stitch-empty">No finding analyses.</p>';
  const captionByChartId = {};
  (charts || []).forEach((c) => {
    if (c?.chart_id) captionByChartId[c.chart_id] = c.caption || "";
  });
  return analyses
    .map((fa) => {
      const factors = fa.contributing_factors?.length
        ? `<div class="report-stitch-labelled-block">
            <span class="report-stitch-labelled-heading">Contributing factors</span>
            <ul class="report-stitch-list">${fa.contributing_factors
              .map((f) => `<li>${escapeHtml(f)}</li>`)
              .join("")}</ul>
          </div>`
        : "";
      const metrics = fa.related_metrics?.length
        ? `<p class="report-stitch-finding-metrics"><span class="report-stitch-labelled-heading">Metrics</span> ${fa.related_metrics
            .map((m) => escapeHtml(m))
            .join(", ")}</p>`
        : "";
      const chart = fa.chart_id
        ? chartImgHtml(runId, fa.chart_id, captionByChartId[fa.chart_id])
        : "";
      return `
    <div class="report-stitch-finding-card">
      <h4>${escapeHtml(fa.finding_name || "Finding")}</h4>
      ${fa.time_window ? `<p class="report-stitch-finding-window">${escapeHtml(fa.time_window)}</p>` : ""}
      ${buildStitchLabelledBlock("What was observed", fa.what_observed)}
      ${buildStitchLabelledBlock("Why it happened", fa.why_it_happened)}
      ${chart}
      ${factors}
      ${metrics}
    </div>`;
    })
    .join("");
}

function buildStitchCharts(charts, runId, findingChartIds) {
  const attached = new Set(findingChartIds || []);
  const standalone = (charts || []).filter((c) => c?.chart_id && !attached.has(c.chart_id));
  if (!standalone.length) return "";
  return standalone
    .map(
      (c) => `
    <div class="report-stitch-finding-card">
      ${c.finding_name ? `<h4>${escapeHtml(c.finding_name)}</h4>` : ""}
      ${c.time_window ? `<p class="report-stitch-finding-window">${escapeHtml(c.time_window)}</p>` : ""}
      ${chartImgHtml(runId, c.chart_id, c.caption)}
    </div>`
    )
    .join("");
}

function buildStitchEvidence(citations) {
  if (!citations?.length) return '<p class="report-stitch-empty">No citations.</p>';
  return citations
    .map((c) => {
      const ref = c.reference || "";
      const summary = c.summary || "";
      const isLog = /log|mongod/i.test(c.source_type || "") || /\.log/i.test(ref);
      const values =
        c.values && Object.keys(c.values).length
          ? `<ul class="report-stitch-list report-stitch-evidence-values">${Object.entries(c.values)
              .map(([k, v]) => `<li><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</li>`)
              .join("")}</ul>`
          : "";
      if (isLog && ref.length > 20) {
        return `
        <div class="report-stitch-evidence-card">
          <div class="report-stitch-evidence-block">
            <div class="report-stitch-evidence-header">${escapeHtml(c.source_type || "log excerpt")}</div>
            <div class="report-stitch-evidence-body">${escapeHtml(ref)}</div>
          </div>
          ${summary ? buildStitchLabelledBlock("Summary", summary) : ""}
          ${values}
        </div>`;
      }
      return `
      <div class="report-stitch-finding-card">
        <h4>${escapeHtml(c.source_type || "source")} — ${escapeHtml(ref)}</h4>
        ${summary ? buildStitchLabelledBlock("Summary", summary) : ""}
        ${values}
      </div>`;
    })
    .join("");
}

function buildStitchList(items, ordered = false) {
  if (!items?.length) return '<p class="report-stitch-empty">None listed.</p>';
  const tag = ordered ? "ol" : "ul";
  const listClass = ordered ? "report-stitch-list report-stitch-list--ordered" : "report-stitch-list";
  return `<${tag} class="${listClass}">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</${tag}>`;
}

function buildStitchRuledOut(items) {
  if (!items?.length) return '<p class="report-stitch-empty">None listed.</p>';
  return `<ul class="report-stitch-list report-stitch-ruled-list">${items
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("")}</ul>`;
}

function stitchSection(id, title, bodyHtml) {
  return `
    <section class="report-section report-stitch-section" id="section-${id}" data-rv-section data-rv-nav="${id}">
      <h3 class="report-stitch-section-title">${escapeHtml(title)}</h3>
      ${bodyHtml}
    </section>`;
}

function buildReportDomStitch(data) {
  const report = data.report || {};
  const confidence = formatConfidence(report.confidence);
  const sections = [];
  const parts = [];

  const heroMeta = [];
  if (data.provider) heroMeta.push(`<span><span class="material-symbols-outlined text-sm">robot_2</span> ${escapeHtml(data.provider)}</span>`);
  if (data.agent_id) heroMeta.push(`<span>${escapeHtml(data.agent_id)}</span>`);

  parts.push(`
    <section class="report-section report-stitch-hero" id="section-hero" data-rv-section data-rv-nav="hero">
      <div class="flex justify-between items-start gap-4 flex-wrap w-full">
        <div class="min-w-0">
          ${buildMetaChips(data).replace(/rv-meta-chips/g, "report-stitch-chips").replace(/rv-chip/g, "report-stitch-chip")}
          <p class="report-stitch-kicker">Diagnostic report</p>
          <h1 class="report-stitch-title">${escapeHtml(report.root_cause || "Root cause pending")}</h1>
          ${heroMeta.length ? `<div class="report-stitch-meta">${heroMeta.join('<span>•</span>')}</div>` : ""}
        </div>
        ${confidence != null ? buildStitchConfidenceRing(confidence) : ""}
      </div>
    </section>`);
  sections.push({ id: "hero", label: "Overview" });

  if (report.summary) {
    sections.push({ id: "summary", label: "Executive summary" });
    parts.push(stitchSection("summary", "Executive summary", buildStitchSummary(report.summary)));
  }

  if (report.mechanism_summary) {
    sections.push({ id: "mechanism", label: "Mechanism" });
    parts.push(
      stitchSection("mechanism", "Mechanism", buildStitchTextBlock(report.mechanism_summary))
    );
  }

  if (report.incident_timeline?.length) {
    sections.push({ id: "timeline", label: "Timeline" });
    parts.push(stitchSection("timeline", "Incident timeline", buildStitchTimeline(report.incident_timeline)));
  }

  if (report.finding_analyses?.length) {
    sections.push({ id: "findings", label: "Findings" });
    parts.push(
      stitchSection(
        "findings",
        "Finding analyses",
        buildStitchFindings(report.finding_analyses, data.run_id, report.charts)
      )
    );
  }

  const findingChartIds = (report.finding_analyses || []).map((fa) => fa.chart_id).filter(Boolean);
  const standaloneCharts = buildStitchCharts(report.charts, data.run_id, findingChartIds);
  if (standaloneCharts) {
    sections.push({ id: "charts", label: "Charts" });
    parts.push(stitchSection("charts", "Metric charts", standaloneCharts));
  }

  if (report.causal_chain?.length) {
    sections.push({ id: "causal", label: "Causal chain" });
    parts.push(stitchSection("causal", "Causal chain", buildStitchCausalChain(report.causal_chain)));
  }

  if (report.evidence_citations?.length) {
    sections.push({ id: "evidence", label: "Evidence" });
    parts.push(stitchSection("evidence", "Evidence citations", buildStitchEvidence(report.evidence_citations)));
  }

  if (report.safe_fixes?.length) {
    sections.push({ id: "fixes", label: "Safe fixes" });
    parts.push(
      stitchSection("fixes", "Actionable fixes", `<div class="report-stitch-fixes">${buildStitchList(report.safe_fixes, true)}</div>`)
    );
  }

  if (report.ruled_out_hypotheses?.length) {
    sections.push({ id: "ruled-out", label: "Ruled out" });
    parts.push(
      stitchSection("ruled-out", "Ruled out hypotheses", buildStitchRuledOut(report.ruled_out_hypotheses))
    );
  }

  if (report.reference_urls?.length) {
    sections.push({ id: "references", label: "References" });
    parts.push(
      stitchSection(
        "references",
        "References",
        `<ul class="report-stitch-list">${report.reference_urls
          .map(
            (url) =>
              `<li><a class="report-stitch-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a></li>`
          )
          .join("")}</ul>`
      )
    );
  }

  return `
    <div class="report-stitch-layout">
      <div class="hidden lg:block">
        ${buildStitchNav(sections)}
      </div>
      <div class="report-stitch-document">
        ${parts.join("")}
      </div>
    </div>`;
}

function animateStitchReportSections(root) {
  root.querySelectorAll(".report-section").forEach((el, index) => {
    if (prefersReducedMotion()) {
      el.classList.add("is-visible");
      return;
    }
    window.setTimeout(() => el.classList.add("is-visible"), index * 80);
  });
}

function initReportObserversStitch(root) {
  if (sectionObserver) sectionObserver.disconnect();
  if (navObserver) navObserver.disconnect();
  if (chainResizeObserver) chainResizeObserver.disconnect();

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
      { rootMargin: "-15% 0px -55% 0px", threshold: [0, 0.25, 0.5] }
    );
    navSections.forEach((s) => navObserver.observe(s));
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const id = link.getAttribute("data-rv-link");
      const target = root.querySelector(`#section-${id}`);
      if (target) {
        target.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      }
    });
  });

  animateStitchReportSections(root);
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
  container.classList.remove("hidden", "report-viewer--3d");
  if (isStitchReportViewer(container)) {
    container.innerHTML = buildReportDomStitch(data);
    initReportObserversStitch(container);
  } else {
    container.innerHTML = buildReportDom(data);
    initReportObservers(container);
  }
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
  container.classList.add("hidden");
  container.classList.remove("report-viewer--3d");
}

function getLastReportData() {
  return lastReportData;
}

function reanimateStitchReport(container) {
  if (!container || !isStitchReportViewer(container)) return;
  container.querySelectorAll(".report-section").forEach((el) => el.classList.remove("is-visible"));
  animateStitchReportSections(container);
}

window.FtdcReportViewer = {
  render: renderReportPayload,
  load: loadAndRender,
  clear: clearReport,
  getLastReportData,
  reanimateStitch: reanimateStitchReport,
};
