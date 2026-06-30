import { StitchIcon } from "@/components/StitchIcon";
import type { RunStatusVariant } from "@/lib/runStatus";

const STYLES: Record<
  RunStatusVariant,
  { wrap: string; dot?: string; spin?: boolean }
> = {
  complete: {
    wrap: "bg-emerald-100 text-emerald-800",
    dot: "bg-emerald-600",
  },
  progress: {
    wrap: "bg-blue-100 text-blue-800",
    spin: true,
  },
  failed: {
    wrap: "bg-red-100 text-red-800",
    dot: "bg-red-600",
  },
  pending: {
    wrap: "bg-surface-container text-on-surface-variant",
    dot: "bg-outline",
  },
};

export function RunStatusBadge({
  label,
  variant,
}: Readonly<{ label: string; variant: RunStatusVariant }>) {
  const s = STYLES[variant];
  const completePulse = variant === "complete";
  return (
    <div
      className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-tight ${s.wrap}`}
    >
      {s.spin ? (
        <StitchIcon name="sync" className="status-spinner text-[14px]" size={14} />
      ) : (
        <span className={`w-2 h-2 rounded-full ${s.dot}${completePulse ? " status-pulse" : ""}`} />
      )}
      {label}
    </div>
  );
}
