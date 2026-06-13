from __future__ import annotations

from typing import Any

from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.output_schema import RCAReportDraft


def render_report_html(
    report: RCAReportDraft,
    *,
    run_id: str,
    agent_id: str | None = None,
    tool_usage: dict[str, Any] | None = None,
    correlation: dict[str, Any] | None = None,
) -> str:
    pretty = format_rca_report_pretty(
        report,
        run_id=run_id,
        agent_id=agent_id,
        tool_usage=tool_usage,
    )

    clusters_html = ""
    if correlation:
        for cluster in correlation.get("correlated_clusters", []):
            clusters_html += f"""
            <div class="card">
              <h3>{cluster.get('cluster_id')} — {cluster.get('severity')}</h3>
              <p><strong>Window:</strong> {cluster.get('from')} → {cluster.get('to')}</p>
              <p><strong>Metrics:</strong> {', '.join(cluster.get('metrics', []))}</p>
              <p>{cluster.get('observation')}</p>
            </div>
            """

    citations_html = ""
    for citation in report.evidence_citations:
        citations_html += f"""
        <li><strong>[{citation.source_type}]</strong> {citation.reference}<br/>
        <span class="muted">{citation.summary}</span></li>
        """

    fixes_html = "".join(f"<li>{fix}</li>" for fix in report.safe_fixes)
    refs_html = "".join(
        f'<li><a href="{url}" target="_blank" rel="noopener">{url}</a></li>'
        for url in report.reference_urls
    )
    chain_html = "".join(f"<li>{step}</li>" for step in report.causal_chain)

    mechanism_html = f"<p>{report.mechanism_summary}</p>" if report.mechanism_summary else '<p class="muted">No mechanism summary.</p>'

    timeline_html = ""
    for event in report.incident_timeline:
        metrics = ", ".join(event.metrics_involved) if event.metrics_involved else "n/a"
        timeline_html += f"""
        <div class="timeline-event">
          <p><strong>{event.time_window}</strong></p>
          <p><em>Observed:</em> {event.observation}</p>
          <p><em>Why:</em> {event.mechanism}</p>
          <p class="muted">Metrics: {metrics}</p>
        </div>"""

    analyses_html = ""
    for analysis in report.finding_analyses:
        factors = "".join(f"<li>{f}</li>" for f in analysis.contributing_factors)
        metrics = ", ".join(analysis.related_metrics) if analysis.related_metrics else "n/a"
        analyses_html += f"""
        <div class="finding-analysis">
          <h3>{analysis.finding_name}</h3>
          <p><strong>What:</strong> {analysis.what_observed}</p>
          <p><strong>Why:</strong> {analysis.why_it_happened}</p>
          <ul>{factors}</ul>
          <p class="muted">Related metrics: {metrics}</p>
        </div>"""

    confidence = f"{report.confidence * 100:.0f}%" if report.confidence is not None else "N/A"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>RCA Report — {run_id}</title>
  <link rel="stylesheet" href="/static/css/app.css"/>
</head>
<body>
  <header class="hero">
    <h1>FTDC Root Cause Analysis</h1>
    <p class="meta">Run: {run_id} | Confidence: {confidence}</p>
    <p class="muted">Interactive charts: open the run page Grafana section for this run.</p>
  </header>
  <main class="container">
    <section class="card">
      <h2>Summary</h2>
      <p>{report.summary}</p>
    </section>
    <section class="card">
      <h2>Root Cause</h2>
      <p>{report.root_cause}</p>
    </section>
    <section class="card">
      <h2>Mechanism — Why It Happened</h2>
      {mechanism_html}
    </section>
    <section class="card">
      <h2>Incident Timeline</h2>
      {timeline_html or '<p class="muted">No timeline events recorded.</p>'}
    </section>
    <section class="card">
      <h2>Finding Analyses</h2>
      {analyses_html or '<p class="muted">No per-finding analyses.</p>'}
    </section>
    <section class="card">
      <h2>Causal Chain</h2>
      <ol>{chain_html or '<li class="muted">No causal chain steps.</li>'}</ol>
    </section>
    <section class="card">
      <h2>Correlated Anomaly Clusters</h2>
      {clusters_html or '<p class="muted">No correlation data.</p>'}
    </section>
    <section class="card">
      <h2>Evidence</h2>
      <ul>{citations_html}</ul>
    </section>
    <section class="card">
      <h2>Suggested Next Steps</h2>
      <ul>{fixes_html}</ul>
    </section>
    <section class="card">
      <h2>Web References</h2>
      <ul>{refs_html or '<li class="muted">No reference URLs cited.</li>'}</ul>
    </section>
    <section class="card">
      <h2>Full Text Report</h2>
      <pre class="pretty-report">{pretty}</pre>
    </section>
  </main>
</body>
</html>"""
