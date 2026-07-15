import type {
  ChartSeries,
  MetricCard,
  RcaPhaseStatus,
  ResultsData,
} from "./resultsTypes";

type ExecutiveContext = {
  activity_summary?: Record<string, number>;
  top_anomaly_windows?: Array<{
    metric: string;
    severity: string;
    peak: number;
    from: string;
    to: string;
  }>;
  findings?: Array<{ name: string; severity: string; suggestion?: string }>;
  host?: string;
};

type Phase2Status = {
  status?: string;
  investigation?: { summary?: string };
  questions?: { questions?: unknown[] };
  answers?: Record<string, string>;
};

type ReportPayload = {
  report?: {
    root_cause?: string;
    summary?: string;
    causal_chain?: string[];
    incident_timeline?: Array<{ observation: string; time_window?: string }>;
    safe_fixes?: string[];
    evidence_citations?: Array<{ reference: string; summary: string }>;
    finding_analyses?: Array<{ finding_name: string; what_observed?: string }>;
    confidence?: number | null;
  };
};

async function fetchJson<T>(url: string): Promise<T | null> {
  const resp = await fetch(url);
  if (!resp.ok) return null;
  return (await resp.json()) as T;
}

function mapOverallStatus(phase2Status?: string, hasReport?: boolean): ResultsData["status"] {
  if (hasReport || phase2Status === "completed") return "complete";
  if (phase2Status === "failed") return "failed";
  if (
    phase2Status === "awaiting_clarifications" ||
    phase2Status === "running_investigation" ||
    phase2Status === "running_rca" ||
    phase2Status === "in_progress"
  ) {
    return "in-progress";
  }
  return "pending";
}

function mapPhaseStatus(
  letter: "A" | "B" | "C",
  state: Phase2Status | null,
  hasReport: boolean,
): RcaPhaseStatus {
  const st = state?.status;
  if (letter === "A") {
    if (state?.investigation) return "complete";
    if (st === "awaiting_clarifications" || st === "running_rca" || st === "completed") {
      return "in-progress";
    }
    return "pending";
  }
  if (letter === "B") {
    const answers = state?.answers ?? {};
    if (Object.keys(answers).length > 0) return "complete";
    if (state?.questions?.questions?.length) return "in-progress";
    return "pending";
  }
  if (hasReport || st === "completed") return "complete";
  if (st === "running_rca") return "in-progress";
  return "pending";
}

function severityFromFindings(
  findings: ExecutiveContext["findings"],
): "HIGH" | "MEDIUM" | "LOW" {
  if (!findings?.length) return "MEDIUM";
  if (findings.some((f) => f.severity === "critical")) return "HIGH";
  if (findings.some((f) => f.severity === "warning")) return "MEDIUM";
  return "LOW";
}

function buildMetricCards(ctx: ExecutiveContext | null): MetricCard[] {
  const activity = ctx?.activity_summary ?? {};
  const windows = ctx?.top_anomaly_windows ?? [];
  const replPeaks = windows.filter((w) => w.metric.includes("repl_lag")).map((w) => w.peak);
  const cpuPeaks = windows.filter((w) => w.metric.includes("cpu_idle")).map((w) => w.peak);
  const replSpark = replPeaks.slice(0, 8);
  const cpuSpark = cpuPeaks.slice(0, 8);

  const peakRepl = replPeaks.length ? Math.max(...replPeaks) : null;
  const peakCpuStress =
    cpuPeaks.length ? Math.min(...cpuPeaks.map((p) => (p <= 1 ? p * 100 : p))) : null;

  const cards: MetricCard[] = [];

  if (peakRepl !== null) {
    cards.push({
      label: "Peak repl lag (s)",
      value: Math.round(peakRepl),
      extra: replPeaks.length > 3 ? "▲ HIGH" : undefined,
      spark: replSpark.length >= 2 ? replSpark : undefined,
      color: "#C96442",
    });
  }

  if (activity.CacheUsed != null) {
    cards.push({
      label: "Cache used",
      value: `${activity.CacheUsed}%`,
      circlePercent: activity.CacheUsed,
      color: "#C96442",
    });
  }

  if (activity.ConnsCurrent != null) {
    cards.push({
      label: "Connections",
      value: activity.ConnsCurrent,
      color: "#6b5b56",
    });
  }

  if (peakCpuStress !== null) {
    cards.push({
      label: "CPU idle (min %)",
      value: Math.round(peakCpuStress),
      extra: peakCpuStress < 30 ? "▲ LOW" : "→ OK",
      spark: cpuSpark.length >= 2 ? cpuSpark : undefined,
      color: "#6b5b56",
    });
  }

  if (ctx?.findings?.length) {
    cards.push({
      label: "Tier-1 findings",
      value: ctx.findings.length,
      extra: severityFromFindings(ctx.findings),
      color: "#7b555d",
    });
  }

  return cards;
}

function buildChart(ctx: ExecutiveContext | null): ChartSeries | undefined {
  const windows = (ctx?.top_anomaly_windows ?? []).slice(0, 12);
  if (windows.length < 2) return undefined;

  const labels = windows.map((w) => {
    const d = new Date(w.from);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  });

  const repl = windows.map((w) => (w.metric.includes("repl_lag") ? w.peak : 0));
  const cpu = windows.map((w) =>
    w.metric.includes("cpu_idle") ? (w.peak <= 1 ? w.peak * 100 : w.peak) : 0,
  );
  const cache = windows.map(() => ctx?.activity_summary?.CacheUsed ?? 0);
  const yMax = Math.max(1, ...repl, ...cpu, ...cache);

  return { labels, read: repl, write: cpu, cache, yMax };
}

function buildCausalChain(report: ReportPayload["report"]): { label: string; description: string }[] {
  if (!report) return [];
  if (report.causal_chain?.length) {
    return report.causal_chain.map((text, i) => ({
      label: i === 0 ? "Trigger" : i === report.causal_chain!.length - 1 ? "Impact" : `Step ${i + 1}`,
      description: text,
    }));
  }
  return (report.incident_timeline ?? []).slice(0, 3).map((ev, i) => ({
    label: i === 0 ? "Trigger" : i === 1 ? "Symptom" : "Impact",
    description: ev.observation,
  }));
}

function buildEvidenceLog(report: ReportPayload["report"]): string {
  if (!report) return "No evidence citations yet — run Phase 2 RCA.";
  const lines = (report.evidence_citations ?? []).slice(0, 12).map(
    (c) => `${c.reference}: ${c.summary}`,
  );
  if (lines.length) return lines.join("\n");
  return (report.incident_timeline ?? [])
    .slice(0, 8)
    .map((e) => `${e.time_window ?? "—"} ${e.observation}`)
    .join("\n");
}

export async function loadResultsData(
  runId: string,
  llm: string,
  uploadTimeUtc?: string | null,
): Promise<ResultsData> {
  const [context, phase2, reportWrap] = await Promise.all([
    fetchJson<ExecutiveContext>(`/simagix/runs/${encodeURIComponent(runId)}/context`),
    fetchJson<Phase2Status>(
      `/simagix/runs/${encodeURIComponent(runId)}/phase2/status?llm=${encodeURIComponent(llm)}`,
    ),
    fetchJson<ReportPayload>(
      `/simagix/runs/${encodeURIComponent(runId)}/phase2/reports/latest?llm=${encodeURIComponent(llm)}`,
    ),
  ]);

  const report = reportWrap?.report;
  const hasReport = Boolean(report?.root_cause || report?.summary);
  const phaseStatus = phase2?.status;

  const investigationSummary = phase2?.investigation?.summary;
  const phaseBCount = phase2?.questions?.questions?.length ?? 0;
  const phaseBAnswers = Object.keys(phase2?.answers ?? {}).length;

  const metricCards = buildMetricCards(context);
  const chart = buildChart(context);

  const replMetric = metricCards.find((c) => c.label.startsWith("Peak repl"));
  const chartLegend = {
    read: replMetric ? "Repl lag peaks" : "Primary metric peaks",
    write: "CPU idle (low = stress)",
    cache: "Cache used % (snapshot)",
  };

  return {
    run_id: runId,
    status: mapOverallStatus(phaseStatus, hasReport),
    upload_time: uploadTimeUtc ?? undefined,
    selected_llm: llm,
    has_report: hasReport,
    host: context?.host,
    metric_cards: metricCards,
    chart,
    chart_legend: chartLegend,
    rca_summary: hasReport
      ? {
          severity: severityFromFindings(context?.findings),
          root_cause: report?.root_cause || report?.summary || "Root cause pending.",
          causal_chain: buildCausalChain(report),
          actions: report?.safe_fixes ?? [],
        }
      : context?.findings?.length
        ? {
            severity: severityFromFindings(context.findings),
            root_cause:
              context.findings[0]?.name
                ? `Tier-1 flagged: ${context.findings[0].name}. Run Phase 2 for mechanism.`
                : "Run Phase 2 RCA to generate root cause analysis.",
            causal_chain: context.findings.slice(0, 3).map((f, i) => ({
              label: i === 0 ? "Finding" : `Finding ${i + 1}`,
              description: f.name,
            })),
            actions: context.findings.map((f) => f.suggestion).filter(Boolean) as string[],
          }
        : undefined,
    phases: {
      phaseA: {
        status: mapPhaseStatus("A", phase2, hasReport),
        summary: investigationSummary ?? "Phase A not started.",
      },
      phaseB: {
        status: mapPhaseStatus("B", phase2, hasReport),
        summary:
          phaseBAnswers > 0
            ? `${phaseBAnswers} clarifying answer(s) submitted.`
            : phaseBCount > 0
              ? `${phaseBCount} clarifying question(s) pending.`
              : "Phase B not started.",
      },
      phaseC: {
        status: mapPhaseStatus("C", phase2, hasReport),
        report: report?.summary ?? report?.root_cause ?? "Report not generated yet.",
      },
    },
    evidence_log: buildEvidenceLog(report),
  };
}
