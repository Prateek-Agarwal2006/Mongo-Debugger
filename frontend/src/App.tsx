import { StitchShell } from "@/layout/StitchShell";
import { getPageData, resolveModernPage } from "@/lib/pageData";
import HomePage from "@/pages/HomePage";
import RunsPage from "@/pages/RunsPage";
import UploadPage from "@/pages/UploadPage";
import RunWorkspacePage from "@/pages/RunWorkspacePage";
import PipelinePage from "@/pages/PipelinePage";
import McpWorkareaPage from "@/pages/McpWorkareaPage";
import SkillWorkareaPage from "@/pages/SkillWorkareaPage";

export default function App() {
  const page = resolveModernPage(getPageData());

  if (page === "home") {
    return <HomePage />;
  }

  if (page === "upload") {
    return <UploadPage />;
  }

  if (page === "runs") {
    return <RunsPage />;
  }

  if (page === "run_workspace") {
    return <RunWorkspacePage />;
  }

  if (page === "pipeline") {
    return <PipelinePage />;
  }

  if (page === "mcp_workarea") {
    return <McpWorkareaPage />;
  }

  if (page === "skill_workarea") {
    return <SkillWorkareaPage />;
  }

  return (
    <StitchShell>
      <div className="max-w-7xl mx-auto px-6 py-16 text-on-surface-variant">
        <p>This page is not in the Modern shell yet.</p>
        <a href="/" className="text-brand-primary font-semibold hover:underline">Back to home</a>
      </div>
    </StitchShell>
  );
}
