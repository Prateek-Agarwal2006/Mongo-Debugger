/** Phase 1 pipeline status — Stitch HTML shell. */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function PipelinePage() {
  return (
    <iframe
      src={stitchPageUrl("pipeline")}
      title="Phase 1 decode"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-[#FAF9F5]"
    />
  );
}
