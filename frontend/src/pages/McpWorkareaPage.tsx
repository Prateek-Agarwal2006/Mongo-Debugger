/** MCP WorkArea — Stitch HTML + mcp-workarea.js */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function McpWorkareaPage() {
  return (
    <iframe
      src={stitchPageUrl("mcp_workarea")}
      title="MCP WorkArea"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-[#FAF9F5]"
    />
  );
}
