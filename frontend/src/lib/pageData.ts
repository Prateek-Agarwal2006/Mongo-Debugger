export type RunEntry = {
  run_id: string;
  phase1_status?: string;
  phase1_label?: string;
  phase2_status?: string;
  upload_time_utc?: string | null;
  hatchet_status?: string;
  phase1_attempt_count?: number;
  message?: string;
  job_id?: string | null;
  error?: string | null;
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
      page: "pipeline";
      run_id: string;
      pipeline_status?: string;
      phase1_label?: string;
      job_id?: string | null;
      job_message?: string | null;
      upload_time_utc?: string | null;
    }
  | { page: "mcp_workarea" }
  | { page: "skill_workarea" }
  | { page: "unknown" };

export function currentPath(): string {
  return window.location.pathname.replace(/\/$/, "") || "/";
}

/** Write page_data for stitch iframes (they read #mdb-page-data from parent). */
export function setPageData(data: PageData): void {
  let el = document.getElementById("mdb-page-data") as HTMLScriptElement | null;
  if (!el) {
    el = document.createElement("script");
    el.id = "mdb-page-data";
    el.type = "application/json";
    document.body.prepend(el);
  }
  el.textContent = JSON.stringify(data);
}

export function pathToPageId(path: string = currentPath()): PageData["page"] | "run" {
  if (path === "/") return "home";
  if (path === "/upload") return "upload";
  if (path === "/runs") return "runs";
  if (path === "/mcp-workarea") return "mcp_workarea";
  if (path === "/skill-workarea") return "skill_workarea";
  if (/^\/runs\/[^/]+\/pipeline$/.test(path)) return "pipeline";
  if (/^\/runs\/[^/]+$/.test(path)) return "run";
  return "unknown";
}

export function runIdFromPath(path: string = currentPath()): string | null {
  const m = path.match(/^\/runs\/([^/]+)(?:\/pipeline)?$/);
  return m ? decodeURIComponent(m[1]) : null;
}
