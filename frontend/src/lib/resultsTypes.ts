export type RcaPhaseStatus = "complete" | "in-progress" | "pending" | "failed";

export interface MetricCard {
  label: string;
  value: number | string;
  extra?: string;
  spark?: number[];
  color?: string;
  circlePercent?: number;
}

export interface ChartSeries {
  labels: string[];
  read: number[];
  write: number[];
  cache: number[];
  yMax: number;
}

export interface ResultsData {
  run_id: string;
  status: "complete" | "in-progress" | "failed" | "pending";
  upload_time?: string;
  metric_cards?: MetricCard[];
  chart?: ChartSeries;
  chart_legend?: { read: string; write: string; cache: string };
  rca_summary?: {
    severity: "HIGH" | "MEDIUM" | "LOW";
    root_cause: string;
    causal_chain: { label: string; description: string }[];
    actions: string[];
  };
  phases?: {
    phaseA: { status: RcaPhaseStatus; timestamp?: string; summary?: string };
    phaseB: { status: RcaPhaseStatus; timestamp?: string; summary?: string };
    phaseC: { status: RcaPhaseStatus; timestamp?: string; report?: string };
  };
  evidence_log?: string;
  selected_llm?: string;
  has_report?: boolean;
  host?: string;
}
