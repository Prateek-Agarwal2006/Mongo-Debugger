/** Modern runs = exact Stitch HTML hydrated from parent page_data. */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function RunsPage() {
  return (
    <iframe
      src={stitchPageUrl("runs")}
      title="Analysis runs"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-surface"
    />
  );
}
