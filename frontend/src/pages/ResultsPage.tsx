import { useEffect, useState } from "react";
import { RunStatusBadge } from "@/components/RunStatusBadge";
import { StitchIcon } from "@/components/StitchIcon";
import { loadResultsData } from "@/lib/loadResultsData";
import type { ChartSeries, MetricCard, RcaPhaseStatus, ResultsData } from "@/lib/resultsTypes";

function mapResultsStatus(status: ResultsData["status"]): "complete" | "progress" | "failed" | "pending" {
  if (status === "complete") return "complete";
  if (status === "failed") return "failed";
  if (status === "in-progress") return "progress";
  return "pending";
}

function FtdcBarChart({ chart }: Readonly<{ chart: ChartSeries }>) {
  const max = chart.yMax || 1;
  const heights = chart.read.map((v) => Math.max(8, (v / max) * 100));

  return (
    <div className="h-[300px] w-full relative flex flex-col justify-between">
      <div className="absolute inset-0 flex items-end justify-between px-2 gap-1 overflow-hidden pointer-events-none">
        {heights.map((h, i) => (
          <div
            key={i}
            className="flex-1 bg-accent-terracotta/25 rounded-t min-h-[8px]"
            style={{ height: `${h}%`, animation: `heightGrow 1s ease-out ${0.1 + i * 0.05}s both` }}
          />
        ))}
      </div>
      <div className="absolute inset-0 border-b border-l border-outline-variant/30 flex flex-col justify-between py-2 pointer-events-none">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="border-t border-dashed border-outline-variant/20 w-full" />
        ))}
      </div>
      <div className="flex justify-between text-[10px] font-bold text-on-surface-variant/50 pt-4 px-2">
        {chart.labels.map((l, i) => (
          <span key={`${l}-${i}`}>{l}</span>
        ))}
      </div>
    </div>
  );
}

function PhaseAccordion({
  letter,
  title,
  subtitle,
  phase,
  defaultOpen = false,
}: Readonly<{
  letter: string;
  title: string;
  subtitle: string;
  phase: { status: RcaPhaseStatus; summary?: string; report?: string };
  defaultOpen?: boolean;
}>) {
  const [open, setOpen] = useState(defaultOpen);
  const done = phase.status === "complete";

  return (
    <div className="group bg-surface-container-lowest rounded-xl border border-outline-variant/30 overflow-hidden transition-all">
      <button
        type="button"
        className="w-full flex items-center justify-between p-6 text-left hover:bg-surface-container-low transition-colors"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-4">
          <span className="w-10 h-10 flex items-center justify-center rounded-lg bg-surface-container-high text-on-surface-variant font-bold">
            {letter}
          </span>
          <div>
            <h3 className="font-bold text-on-surface">{title}</h3>
            <p className="text-sm text-on-surface-variant">{subtitle}</p>
          </div>
        </div>
        <StitchIcon
          name="expand_more"
          className={`transition-transform duration-300${open ? " rotate-180" : ""}`}
          size={24}
        />
      </button>
      {open && (
        <div className="px-6 pb-6">
          <div className="pt-2 border-t border-outline-variant/10 space-y-3">
            <div className="flex items-center gap-3 text-sm text-on-surface-variant">
              <StitchIcon
                name={done ? "check_circle" : "pending"}
                className={done ? "text-green-500" : "text-outline"}
                size={18}
              />
              {phase.summary ?? phase.report ?? "No data yet."}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricTile({ card }: Readonly<{ card: MetricCard }>) {
  return (
    <div className="bg-surface-container-lowest p-6 rounded-xl border border-outline-variant/30 shadow-sm hover:shadow-md transition-shadow">
      <p className="text-on-surface-variant text-sm font-medium mb-1">{card.label}</p>
      <div className="flex items-baseline gap-2 flex-wrap">
        <h3 className="text-3xl font-black text-on-surface">{card.value}</h3>
        {card.extra && (
          <span
            className={`text-xs font-bold ${
              card.extra.includes("HIGH") || card.extra.includes("LOW")
                ? "text-accent-terracotta"
                : "text-green-600"
            }`}
          >
            {card.extra}
          </span>
        )}
      </div>
    </div>
  );
}

export default function ResultsPage({
  runId,
  llm,
  uploadTimeUtc,
}: Readonly<{
  runId: string;
  llm: string;
  uploadTimeUtc?: string | null;
}>) {
  const [data, setData] = useState<ResultsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadResultsData(runId, llm, uploadTimeUtc)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, llm, uploadTimeUtc]);

  const reportUrl = `/simagix/runs/${encodeURIComponent(runId)}/phase2/reports/latest?llm=${encodeURIComponent(llm)}&format=pretty`;

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-12 text-error">
        Could not load run data: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-12 text-on-surface-variant">
        Loading analysis data…
      </div>
    );
  }

  const statusVariant = mapResultsStatus(data.status);
  const statusLabel =
    data.status === "complete"
      ? "Complete"
      : data.status === "failed"
        ? "Failed"
        : data.status === "in-progress"
          ? "In progress"
          : "Pending";

  const rca = data.rca_summary;
  const ph = data.phases;
  const trigger = rca?.causal_chain[0]?.description;

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <nav className="flex text-xs font-medium text-on-surface-variant mb-4 uppercase tracking-wider">
        <a href="/" className="hover:text-on-surface">Home</a>
        <span className="mx-2 text-outline-variant">/</span>
        <a href="/runs" className="hover:text-on-surface">Uploads</a>
        <span className="mx-2 text-outline-variant">/</span>
        <span className="text-accent-terracotta">Analysis Results</span>
      </nav>

      <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
        <div className="flex flex-col md:flex-row md:items-center gap-4">
          <h1 className="text-4xl font-black font-headline tracking-tight text-on-surface">
            Analysis Results
          </h1>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-3 py-1 bg-surface-container-highest text-on-surface-variant rounded-md font-mono text-sm border border-outline-variant">
              {data.run_id}
            </span>
            <RunStatusBadge label={statusLabel} variant={statusVariant} />
            {data.host && (
              <span className="text-sm text-on-surface-variant">{data.host}</span>
            )}
          </div>
        </div>
        <div className="flex gap-3 flex-wrap">
          <button
            type="button"
            className="flex items-center gap-2 px-5 py-2.5 bg-surface-container-highest text-on-surface-variant rounded-lg font-bold hover:bg-surface-variant transition-all active:scale-95"
            onClick={() => window.applyAppTheme?.("classic")}
          >
            <StitchIcon name="open_in_new" size={20} />
            Full workspace
          </button>
          {data.has_report && (
            <a
              href={reportUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-5 py-2.5 bg-surface-container-highest text-on-surface-variant rounded-lg font-bold hover:bg-surface-variant transition-all active:scale-95"
            >
              <StitchIcon name="download" size={20} />
              Export report
            </a>
          )}
          <a
            href={`/runs/${encodeURIComponent(runId)}?llm=${encodeURIComponent(llm)}`}
            className="flex items-center gap-2 px-5 py-2.5 bg-accent-terracotta text-white rounded-lg font-bold shadow-lg shadow-accent-terracotta/20 hover:brightness-110 transition-all active:scale-95"
            onClick={(e) => {
              e.preventDefault();
              window.applyAppTheme?.("classic");
              window.location.href = `/runs/${encodeURIComponent(runId)}?llm=${encodeURIComponent(llm)}`;
            }}
          >
            <StitchIcon name="refresh" size={20} />
            Rerun in Classic
          </a>
        </div>
      </div>

      {data.upload_time && (
        <p className="text-sm text-on-surface-variant mb-6">Uploaded {data.upload_time}</p>
      )}

      {data.metric_cards && data.metric_cards.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          {data.metric_cards.slice(0, 4).map((card) => (
            <MetricTile key={card.label} card={card} />
          ))}
        </div>
      )}

      {data.chart && (
        <section className="bg-surface-container-lowest rounded-2xl border border-outline-variant/30 shadow-sm p-8 mb-8">
          <div className="flex items-center justify-between mb-8 flex-wrap gap-4">
            <div>
              <h2 className="text-xl font-bold text-on-surface">FTDC Metrics</h2>
              <p className="text-sm text-on-surface-variant">
                {data.chart_legend?.read ?? "Anomaly window peaks"}
              </p>
            </div>
          </div>
          <FtdcBarChart chart={data.chart} />
        </section>
      )}

      {rca && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
          <div className="space-y-8">
            <section className="bg-surface-container-lowest rounded-2xl border border-outline-variant/30 shadow-sm p-8 accent-border-left">
              <h2 className="text-xl font-bold text-on-surface mb-4">Root Cause Analysis</h2>
              <p className="text-on-surface-variant leading-relaxed mb-6">{rca.root_cause}</p>
              {trigger && (
                <div className="bg-surface-container-low p-4 rounded-lg flex items-start gap-4">
                  <StitchIcon name="lightbulb" className="text-accent-terracotta mt-1 shrink-0" size={22} />
                  <div>
                    <p className="font-bold text-sm text-on-surface">Primary trigger</p>
                    <p className="text-sm text-on-surface-variant">{trigger}</p>
                  </div>
                </div>
              )}
            </section>

            {rca.actions.length > 0 && (
              <section className="bg-surface-container-lowest rounded-2xl border border-outline-variant/30 shadow-sm p-8">
                <h2 className="text-xl font-bold text-on-surface mb-4">Recommended Actions</h2>
                <ul className="space-y-4">
                  {rca.actions.map((action, i) => (
                    <li key={i} className="flex items-center gap-4 group">
                      <div className="w-8 h-8 rounded-full bg-accent-terracotta/10 text-accent-terracotta flex items-center justify-center shrink-0 group-hover:bg-accent-terracotta group-hover:text-white transition-colors">
                        <span className="text-xs font-bold">{i + 1}</span>
                      </div>
                      <span className="text-on-surface font-medium">{action}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>

          <section className="bg-inverse-surface rounded-2xl shadow-xl overflow-hidden flex flex-col min-h-[400px]">
            <div className="bg-on-surface-variant/20 px-6 py-4 flex items-center justify-between border-b border-outline-variant/10">
              <div className="flex items-center gap-2">
                <div className="flex gap-1.5 mr-4">
                  <div className="w-3 h-3 rounded-full bg-red-400" />
                  <div className="w-3 h-3 rounded-full bg-yellow-400" />
                  <div className="w-3 h-3 rounded-full bg-green-400" />
                </div>
                <h2 className="text-sm font-bold text-surface-bright uppercase tracking-widest">
                  Evidence log
                </h2>
              </div>
              <span className="text-[10px] font-mono text-outline-variant">tier-1 + report</span>
            </div>
            <pre className="p-6 font-mono text-xs overflow-y-auto leading-relaxed flex-grow text-outline-variant whitespace-pre-wrap">
              {data.evidence_log ?? "No evidence loaded."}
            </pre>
          </section>
        </div>
      )}

      {ph && (
        <section className="space-y-4 mb-12">
          <h2 className="text-2xl font-black font-headline text-on-surface mb-6">
            Execution Timeline
          </h2>
          <PhaseAccordion
            letter="A"
            title="Phase A: Investigation"
            subtitle="Scanning and indexing diagnostic evidence"
            phase={ph.phaseA}
            defaultOpen
          />
          <PhaseAccordion
            letter="B"
            title="Phase B: Clarification"
            subtitle="Identifying patterns and cross-referencing metrics"
            phase={ph.phaseB}
          />
          <PhaseAccordion
            letter="C"
            title="Phase C: Final RCA"
            subtitle="Drawing conclusions and generating action items"
            phase={ph.phaseC}
          />
        </section>
      )}
    </div>
  );
}
