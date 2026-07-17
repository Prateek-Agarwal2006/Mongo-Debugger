"""Standalone HTML export of the Phase 2 RCA report in the Stitch design.

Self-contained by design: inline CSS (Stitch palette), charts embedded as
base64 data URIs — the file renders identically when downloaded and opened
offline, no CDN or app server required.
"""
from __future__ import annotations

import base64
import html
from datetime import datetime, timezone
from typing import Any

from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.output_schema import RCAReportDraft


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _para_or_list(text: str) -> str:
    """Multi-line strings become bullet lists, matching the in-app viewer."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = [ln.lstrip("-*• ").strip() for ln in raw.split("\n") if ln.strip()]
    if len(lines) > 1:
        items = "".join(f"<li>{_esc(ln)}</li>" for ln in lines)
        return f'<ul class="list">{items}</ul>'
    return f"<p>{_esc(raw)}</p>"


def _labelled(label: str, text: str) -> str:
    if not str(text or "").strip():
        return ""
    return f'<div class="labelled"><span class="label">{_esc(label)}</span>{_para_or_list(text)}</div>'


def _chart_data_uris(report: RCAReportDraft, run_id: str) -> dict[str, str]:
    """chart_id → data URI for every chart referenced by the report."""
    uris: dict[str, str] = {}
    chart_ids = {c.chart_id for c in report.charts if c.chart_id}
    chart_ids.update(fa.chart_id for fa in report.finding_analyses if fa.chart_id)
    if not chart_ids:
        return uris
    try:
        from backend.app.simagix.evidence.chart_tools import load_chart_png
        for chart_id in chart_ids:
            png = load_chart_png(run_id, chart_id)
            if png:
                uris[chart_id] = "data:image/png;base64," + base64.b64encode(png).decode()
    except Exception:
        pass  # charts unavailable (no DB) — export text-only
    return uris


def _figure(uri: str, caption: str) -> str:
    cap = f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""
    return f'<figure class="chart"><img src="{uri}" alt="{_esc(caption or "Metric chart")}"/>{cap}</figure>'


def render_report_html(
    report: RCAReportDraft,
    *,
    run_id: str,
    agent_id: str | None = None,
    provider: str | None = None,
    tool_usage: dict[str, Any] | None = None,
    correlation: dict[str, Any] | None = None,
) -> str:
    pretty = format_rca_report_pretty(
        report,
        run_id=run_id,
        agent_id=agent_id,
        tool_usage=tool_usage,
    )
    chart_uris = _chart_data_uris(report, run_id)
    captions = {c.chart_id: c.caption for c in report.charts if c.chart_id}

    confidence_html = ""
    if report.confidence is not None:
        pct = max(0, min(100, round(report.confidence * 100)))
        circ = 2 * 3.14159 * 40
        offset = circ * (1 - pct / 100)
        confidence_html = f"""
        <div class="confidence">
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <circle cx="50" cy="50" r="40" fill="none" stroke="#EDEEE8" stroke-width="8"/>
            <circle cx="50" cy="50" r="40" fill="none" stroke="#c96442" stroke-width="8"
              stroke-dasharray="{circ:.1f}" stroke-dashoffset="{offset:.1f}" stroke-linecap="round"
              transform="rotate(-90 50 50)"/>
          </svg>
          <span class="confidence-value">{pct}%</span>
          <span class="confidence-label">Confidence</span>
        </div>"""

    meta_bits = [f"Run <code>{_esc(run_id)}</code>"]
    if provider:
        meta_bits.append(_esc(provider))
    if agent_id:
        meta_bits.append(f"<code>{_esc(agent_id)}</code>")
    if tool_usage and tool_usage.get("total_sdk_calls"):
        meta_bits.append(f"{tool_usage['total_sdk_calls']} tool calls")
    meta_bits.append(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"))

    timeline_html = ""
    for ev in report.incident_timeline:
        metrics = "".join(f'<span class="tag">{_esc(m)}</span>' for m in ev.metrics_involved)
        timeline_html += f"""
        <div class="timeline-item">
          <div class="timeline-dot"></div>
          <div class="timeline-time">{_esc(ev.time_window or "—")}</div>
          {_labelled("Observed", ev.observation)}
          {_labelled("Mechanism", ev.mechanism)}
          {f'<div class="tags">{metrics}</div>' if metrics else ""}
        </div>"""

    findings_html = ""
    for fa in report.finding_analyses:
        factors = ""
        if fa.contributing_factors:
            items = "".join(f"<li>{_esc(f)}</li>" for f in fa.contributing_factors)
            factors = f'<div class="labelled"><span class="label">Contributing factors</span><ul class="list">{items}</ul></div>'
        chart = ""
        if fa.chart_id and fa.chart_id in chart_uris:
            chart = _figure(chart_uris[fa.chart_id], captions.get(fa.chart_id, ""))
        related = ", ".join(fa.related_metrics) if fa.related_metrics else ""
        findings_html += f"""
        <div class="card">
          <h4>{_esc(fa.finding_name or "Finding")}</h4>
          {f'<p class="window">{_esc(fa.time_window)}</p>' if fa.time_window else ""}
          {_labelled("What was observed", fa.what_observed)}
          {_labelled("Why it happened", fa.why_it_happened)}
          {chart}
          {factors}
          {f'<p class="window"><span class="label">Metrics</span> {_esc(related)}</p>' if related else ""}
        </div>"""

    attached_ids = {fa.chart_id for fa in report.finding_analyses if fa.chart_id}
    standalone_charts_html = ""
    for c in report.charts:
        if c.chart_id and c.chart_id not in attached_ids and c.chart_id in chart_uris:
            head = f"<h4>{_esc(c.finding_name)}</h4>" if c.finding_name else ""
            window = f'<p class="window">{_esc(c.time_window)}</p>' if c.time_window else ""
            standalone_charts_html += f'<div class="card">{head}{window}{_figure(chart_uris[c.chart_id], c.caption)}</div>'

    chain_html = ""
    last = len(report.causal_chain) - 1
    for i, step in enumerate(report.causal_chain):
        head = "Observable impact" if i == last and last > 0 else f"Step {i + 1}"
        chain_html += f"""
        <div class="chain-step{' impact' if i == last and last > 0 else ''}">
          <div class="chain-num">{i + 1}</div>
          <div><h4>{head}</h4><p>{_esc(step)}</p></div>
        </div>"""

    evidence_html = ""
    for c in report.evidence_citations:
        values = ""
        if c.values:
            items = "".join(f"<li><strong>{_esc(k)}:</strong> {_esc(v)}</li>" for k, v in c.values.items())
            values = f'<ul class="list">{items}</ul>'
        evidence_html += f"""
        <div class="card">
          <h4><span class="tag">{_esc(c.source_type)}</span> {_esc(c.reference)}</h4>
          {_labelled("Summary", c.summary)}
          {values}
        </div>"""

    clusters_html = ""
    if correlation:
        for cluster in correlation.get("correlated_clusters", []):
            clusters_html += f"""
            <div class="card">
              <h4>{_esc(cluster.get("cluster_id"))} — {_esc(cluster.get("severity"))}</h4>
              <p class="window">{_esc(cluster.get("from"))} → {_esc(cluster.get("to"))}</p>
              {_labelled("Metrics", ", ".join(cluster.get("metrics", [])))}
              {_para_or_list(cluster.get("observation", ""))}
            </div>"""

    fixes_html = "".join(f"<li>{_esc(f)}</li>" for f in report.safe_fixes)
    ruled_html = "".join(f"<li>{_esc(r)}</li>" for r in report.ruled_out_hypotheses)
    refs_html = "".join(
        f'<li><a href="{_esc(u)}" target="_blank" rel="noopener">{_esc(u)}</a></li>'
        for u in report.reference_urls
    )

    def section(title: str, body: str, empty: str = "") -> str:
        if not body.strip():
            body = f'<p class="empty">{_esc(empty)}</p>' if empty else ""
            if not body:
                return ""
        return f'<section class="panel"><h3>{_esc(title)}</h3>{body}</section>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RCA Report — {_esc(run_id)}</title>
<style>
:root {{
  --primary: #C96442; --bg: #faf9f5; --on-surface: #1b1c1a;
  --on-surface-variant: #4e4542; --outline: #d2c3bf;
  --container: #EDEEE8; --container-low: #f4f4f0; --white: #ffffff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--on-surface);
  font-family: "Public Sans", -apple-system, "Segoe UI", Roboto, sans-serif;
  line-height: 1.65; font-size: 15px;
}}
main {{ max-width: 880px; margin: 0 auto; padding: 40px 20px 80px; }}
.panel {{
  background: rgba(255,255,255,0.85); border: 1px solid rgba(210,195,191,0.6);
  border-radius: 14px; padding: 26px 30px; margin-bottom: 22px;
  box-shadow: 0 10px 40px -10px rgba(0,0,0,0.06);
}}
.hero {{ display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; align-items: flex-start; }}
.kicker {{ text-transform: uppercase; letter-spacing: 0.12em; font-size: 11px; color: var(--primary); font-weight: 700; margin: 0 0 6px; }}
h1 {{ font-family: Lora, Georgia, serif; font-size: 26px; line-height: 1.35; margin: 0 0 10px; }}
.meta {{ font-size: 12px; color: var(--on-surface-variant); }}
.meta code {{ background: var(--container-low); padding: 1px 6px; border-radius: 5px; font-size: 11px; }}
h3 {{ font-family: Lora, Georgia, serif; font-size: 18px; margin: 0 0 14px; color: var(--on-surface); }}
h4 {{ font-size: 14px; margin: 0 0 6px; }}
p {{ margin: 0 0 10px; }}
.label {{ display: block; text-transform: uppercase; letter-spacing: 0.08em; font-size: 10.5px; font-weight: 700; color: var(--primary); margin-bottom: 2px; }}
.labelled {{ margin-bottom: 12px; }}
.list {{ margin: 0 0 10px; padding-left: 20px; }}
.list li {{ margin-bottom: 5px; }}
.empty {{ color: var(--on-surface-variant); font-size: 13px; }}
.window {{ font-size: 12px; color: var(--on-surface-variant); margin: 0 0 10px; }}
.card {{ background: var(--container-low); border: 1px solid rgba(210,195,191,0.45); border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }}
.tag {{ display: inline-block; background: var(--container); border-radius: 999px; padding: 2px 10px; font-size: 11px; margin: 0 4px 4px 0; }}
.tags {{ margin-top: 6px; }}
.chart {{ margin: 14px 0; }}
.chart img {{ width: 100%; border-radius: 12px; border: 1px solid rgba(0,0,0,0.08); background: #fff; }}
.chart figcaption {{ font-size: 12px; color: var(--on-surface-variant); margin-top: 6px; }}
.confidence {{ position: relative; width: 96px; text-align: center; flex-shrink: 0; }}
.confidence svg {{ width: 96px; height: 96px; }}
.confidence-value {{ position: absolute; top: 34px; left: 0; right: 0; font-weight: 700; font-size: 18px; }}
.confidence-label {{ display: block; font-size: 11px; color: var(--on-surface-variant); margin-top: 4px; }}
.timeline-item {{ position: relative; padding: 0 0 18px 26px; border-left: 2px solid var(--outline); margin-left: 8px; }}
.timeline-item:last-child {{ border-left-color: transparent; }}
.timeline-dot {{ position: absolute; left: -7px; top: 2px; width: 12px; height: 12px; border-radius: 50%; background: var(--primary); border: 2px solid var(--bg); }}
.timeline-time {{ font-weight: 700; font-size: 13px; margin-bottom: 6px; }}
.chain-step {{ display: flex; gap: 14px; margin-bottom: 16px; }}
.chain-step.impact .chain-num {{ background: var(--primary); color: #fff; }}
.chain-num {{ flex-shrink: 0; width: 30px; height: 30px; border-radius: 50%; background: var(--container); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }}
pre.raw {{ background: var(--container-low); border-radius: 12px; padding: 18px; overflow-x: auto; font-size: 12px; line-height: 1.5; white-space: pre-wrap; }}
a {{ color: var(--primary); }}
@media print {{ .panel {{ box-shadow: none; break-inside: avoid; }} }}
</style>
</head>
<body>
<main>
  <section class="panel hero-panel">
    <div class="hero">
      <div style="min-width:0;">
        <p class="kicker">Diagnostic report</p>
        <h1>{_esc(report.root_cause or "Root cause pending")}</h1>
        <p class="meta">{" • ".join(meta_bits)}</p>
      </div>
      {confidence_html}
    </div>
  </section>
  {section("Executive summary", _para_or_list(report.summary))}
  {section("Mechanism", _para_or_list(report.mechanism_summary))}
  {section("Incident timeline", timeline_html, "No timeline events.")}
  {section("Finding analyses", findings_html, "No per-finding analyses.")}
  {section("Metric charts", standalone_charts_html)}
  {section("Causal chain", chain_html, "No causal chain steps.")}
  {section("Correlated anomaly clusters", clusters_html)}
  {section("Evidence citations", evidence_html, "No citations.")}
  {section("Actionable fixes", f'<ol class="list">{fixes_html}</ol>' if fixes_html else "", "No fixes listed.")}
  {section("Ruled out hypotheses", f'<ul class="list">{ruled_html}</ul>' if ruled_html else "")}
  {section("References", f'<ul class="list">{refs_html}</ul>' if refs_html else "")}
  {section("Full text report", f'<pre class="raw">{_esc(pretty)}</pre>')}
</main>
</body>
</html>"""
