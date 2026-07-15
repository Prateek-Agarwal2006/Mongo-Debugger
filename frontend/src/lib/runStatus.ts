export type RunStatusVariant = "complete" | "progress" | "failed" | "pending";

export function statusVariant(status?: string): RunStatusVariant {
  switch (status) {
    case "finished":
    case "completed":
      return "complete";
    case "processing":
    case "queued":
    case "awaiting_clarifications":
    case "running_investigation":
    case "running_rca":
      return "progress";
    case "failed":
      return "failed";
    default:
      return "pending";
  }
}

export function phase1Label(status?: string, message?: string): string {
  switch (status) {
    case "finished":
    case "completed":
      return "Ready";
    case "processing":
      return /ingest/i.test(message || "") ? "Loading metrics" : "Decoding";
    case "queued":
      return "Queued";
    case "failed":
      return "Failed";
    default:
      return status ?? "Not started";
  }
}

export function phase2PhaseLabel(status?: string): string {
  switch (status) {
    case "completed":
      return "RCA report";
    case "awaiting_clarifications":
      return "Clarifying";
    case "running_investigation":
      return "Investigating";
    case "running_rca":
      return "Running RCA";
    case "not_started":
      return "Not started";
    case "failed":
      return "Failed";
    default:
      return status ?? "Not started";
  }
}

export function deriveRunStatus(entry: {
  phase1_status?: string;
  phase2_status?: string;
}): { label: string; variant: RunStatusVariant } {
  if (entry.phase1_status === "failed" || entry.phase2_status === "failed") {
    return { label: "Failed", variant: "failed" };
  }
  if (entry.phase2_status === "completed") {
    return { label: "Complete", variant: "complete" };
  }
  if (
    entry.phase1_status === "processing" ||
    entry.phase1_status === "queued" ||
    entry.phase2_status === "awaiting_clarifications" ||
    entry.phase2_status === "running_investigation" ||
    entry.phase2_status === "running_rca"
  ) {
    return { label: "In progress", variant: "progress" };
  }
  if (entry.phase1_status === "finished") {
    return { label: "In progress", variant: "progress" };
  }
  return { label: "Pending", variant: "pending" };
}
