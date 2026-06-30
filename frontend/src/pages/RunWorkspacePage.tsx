/** Full RCA workspace — Stitch HTML + existing phase2 JS. */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function RunWorkspacePage() {
  return (
    <iframe
      src={stitchPageUrl("run_workspace")}
      title="Run analysis"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-[#FAF9F5]"
    />
  );
}
