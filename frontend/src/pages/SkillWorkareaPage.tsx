/** Skill WorkArea — Stitch HTML + skill-workarea.js */
import { stitchPageUrl } from "@/lib/stitchAssets";

export default function SkillWorkareaPage() {
  return (
    <iframe
      src={stitchPageUrl("skill_workarea")}
      title="Skill WorkArea"
      className="fixed inset-0 w-full h-full border-0 z-[100] bg-[#FAF9F5]"
    />
  );
}
