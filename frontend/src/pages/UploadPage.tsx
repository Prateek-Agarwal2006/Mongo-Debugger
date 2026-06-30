/** Modern upload = exact Stitch HTML (no React rewrite). */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function UploadPage() {
  return (
    <iframe
      src={stitchPageUrl("upload")}
      title="Upload logs"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-surface"
    />
  );
}
