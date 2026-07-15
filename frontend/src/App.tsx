import { useEffect, useState } from "react";
import { StitchShell } from "@/layout/StitchShell";
import {
  pathToPageId,
  runIdFromPath,
  setPageData,
  type PageData,
  type RunEntry,
} from "@/lib/pageData";
import HomePage from "@/pages/HomePage";
import RunsPage from "@/pages/RunsPage";
import UploadPage from "@/pages/UploadPage";
import RunWorkspacePage from "@/pages/RunWorkspacePage";
import PipelinePage from "@/pages/PipelinePage";
import McpWorkareaPage from "@/pages/McpWorkareaPage";
import SkillWorkareaPage from "@/pages/SkillWorkareaPage";

type BootState =
  | { status: "loading" }
  | { status: "ready"; page: PageData["page"] }
  | { status: "error"; message: string };

function catalogHttpError(status: number, label: string): Error {
  if (status === 500 || status === 502 || status === 503) {
    return new Error(
      "Database unavailable. Postgres may still be recovering — wait a minute and refresh.",
    );
  }
  return new Error(`${label} (${status})`);
}

async function fetchCatalog(): Promise<RunEntry[]> {
  const resp = await fetch("/simagix/catalog");
  if (!resp.ok) throw catalogHttpError(resp.status, "Catalog failed");
  const body = (await resp.json()) as { runs?: RunEntry[] };
  return body.runs ?? [];
}

export default function App() {
  const [boot, setBoot] = useState<BootState>({ status: "loading" });
  const path = typeof window !== "undefined" ? window.location.pathname.replace(/\/$/, "") || "/" : "/";

  useEffect(() => {
    let cancelled = false;

    async function bootFromUrl() {
      try {
        const pageId = pathToPageId(path);

        if (pageId === "home" || pageId === "runs") {
          const runs = await fetchCatalog();
          if (cancelled) return;
          const data: PageData =
            pageId === "home" ? { page: "home", runs } : { page: "runs", runs };
          setPageData(data);
          setBoot({ status: "ready", page: pageId });
          return;
        }

        if (pageId === "upload") {
          setPageData({ page: "upload" });
          setBoot({ status: "ready", page: "upload" });
          return;
        }

        if (pageId === "mcp_workarea") {
          setPageData({ page: "mcp_workarea" });
          setBoot({ status: "ready", page: "mcp_workarea" });
          return;
        }

        if (pageId === "skill_workarea") {
          setPageData({ page: "skill_workarea" });
          setBoot({ status: "ready", page: "skill_workarea" });
          return;
        }

        if (pageId === "pipeline" || pageId === "run") {
          const runId = runIdFromPath(path);
          if (!runId) {
            setBoot({ status: "error", message: "Missing run id" });
            return;
          }
          const resp = await fetch(`/simagix/catalog/${encodeURIComponent(runId)}`);
          if (!resp.ok) {
            if (resp.status === 500 || resp.status === 502 || resp.status === 503) {
              throw catalogHttpError(resp.status, "Run lookup failed");
            }
            const text = await resp.text();
            throw new Error(text || `Run lookup failed (${resp.status})`);
          }
          const body = (await resp.json()) as {
            view: string;
            run_id: string;
            pipeline_status?: string;
            phase1_label?: string;
            job_id?: string | null;
            job_message?: string | null;
            upload_time_utc?: string | null;
            selected_llm?: string;
          };
          if (cancelled) return;

          if (body.view === "pipeline" || pageId === "pipeline") {
            const data: PageData = {
              page: "pipeline",
              run_id: body.run_id,
              pipeline_status: body.pipeline_status,
              phase1_label: body.phase1_label,
              job_id: body.job_id,
              job_message: body.job_message,
              upload_time_utc: body.upload_time_utc,
            };
            setPageData(data);
            // Keep URL as /runs/{id} while showing pipeline (no /pipeline required).
            setBoot({ status: "ready", page: "pipeline" });
            return;
          }

          const data: PageData = {
            page: "run_workspace",
            run_id: body.run_id,
            selected_llm: body.selected_llm || "mock",
            upload_time_utc: body.upload_time_utc,
          };
          setPageData(data);
          setBoot({ status: "ready", page: "run_workspace" });
          return;
        }

        setBoot({ status: "ready", page: "unknown" });
      } catch (err) {
        if (cancelled) return;
        setBoot({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }

    void bootFromUrl();
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (boot.status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center text-on-surface-variant">
        Loading…
      </div>
    );
  }

  if (boot.status === "error") {
    return (
      <StitchShell>
        <div className="max-w-xl mx-auto px-6 py-16 text-red-700">
          <p className="font-semibold mb-2">Failed to load</p>
          <pre className="text-sm whitespace-pre-wrap">{boot.message}</pre>
          <a href="/" className="text-brand-primary font-semibold hover:underline mt-4 inline-block">
            Back to home
          </a>
        </div>
      </StitchShell>
    );
  }

  const page = boot.page;
  if (page === "home") return <HomePage />;
  if (page === "upload") return <UploadPage />;
  if (page === "runs") return <RunsPage />;
  if (page === "run_workspace") return <RunWorkspacePage />;
  if (page === "pipeline") return <PipelinePage />;
  if (page === "mcp_workarea") return <McpWorkareaPage />;
  if (page === "skill_workarea") return <SkillWorkareaPage />;

  return (
    <StitchShell>
      <div className="max-w-7xl mx-auto px-6 py-16 text-on-surface-variant">
        <p>Page not found.</p>
        <a href="/" className="text-brand-primary font-semibold hover:underline">
          Back to home
        </a>
      </div>
    </StitchShell>
  );
}
