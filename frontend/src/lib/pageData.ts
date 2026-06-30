export type RunEntry = {
  run_id: string;
  phase1_status?: string;
  phase2_status?: string;
  upload_time_utc?: string | null;
  hatchet_status?: string;
  phase1_attempt_count?: number;
  message?: string;
};

export type PageData =
  | { page: "home"; runs: RunEntry[] }
  | { page: "runs"; runs: RunEntry[] }
  | { page: "upload" }
  | {
      page: "run_workspace";
      run_id: string;
      selected_llm: string;
      upload_time_utc?: string | null;
      has_report?: boolean;
      phase2_hatchet_blocked?: boolean;
      host?: string | null;
      export_tier?: string | null;
      hatchet_status?: string;
      has_mongodb_logs?: boolean;
      mongodb_log_files?: string[];
    }
  | {
      page: "results";
      run_id: string;
      selected_llm: string;
      upload_time_utc?: string | null;
    }
  | {
      page: "pipeline";
      run_id: string;
      pipeline_status?: string;
      job_id?: string | null;
      upload_time_utc?: string | null;
    }
  | { page: "mcp_workarea" }
  | { page: "skill_workarea" }
  | { page: "unknown" };

/** Map page_data + URL to a Modern shell page id. */
export function resolveModernPage(data: PageData): PageData["page"] {
  if (data.page !== "unknown") {
    if (data.page === "results") return "run_workspace";
    return data.page;
  }

  const path = currentPath();
  if (/^\/runs\/[^/]+$/.test(path)) return "run_workspace";
  if (/^\/runs\/[^/]+\/pipeline$/.test(path)) return "pipeline";
  if (path === "/mcp-workarea") return "mcp_workarea";
  if (path === "/skill-workarea") return "skill_workarea";
  return "unknown";
}

export function getPageData(): PageData {
  const el = document.getElementById("mdb-page-data");
  if (!el?.textContent) return { page: "unknown" };
  try {
    return JSON.parse(el.textContent) as PageData;
  } catch {
    return { page: "unknown" };
  }
}

export function currentPath(): string {
  return window.location.pathname.replace(/\/$/, "") || "/";
}
