/** Modern home = exact Stitch HTML (no React rewrite). */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function HomePage() {
  return (
    <iframe
      src={stitchPageUrl("home")}
      title="Mongo Debugger"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-[#0d0f0d]"
    />
  );
}
