import { RunStatusBadge } from "@/components/RunStatusBadge";
import { StitchIcon } from "@/components/StitchIcon";
import type { RunEntry } from "@/lib/pageData";
import { phase1Label, phase2PhaseLabel, statusVariant } from "@/lib/runStatus";

export function RunsTable({ runs }: Readonly<{ runs: RunEntry[] }>) {
  if (runs.length === 0) {
    return (
      <div className="px-6 py-16 text-center">
        <p className="text-on-surface-variant mb-4">No uploads yet.</p>
        <a
          href="/upload"
          className="inline-flex items-center gap-2 px-6 py-3 bg-accent text-white font-semibold rounded-lg"
        >
          <StitchIcon name="upload" size={20} />
          New upload
        </a>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-surface-container-low border-b border-outline-variant/30">
            <th className="px-6 py-4 text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Run ID
            </th>
            <th className="px-6 py-4 text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Uploaded
            </th>
            <th className="px-6 py-4 text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Phase 1
            </th>
            <th className="px-6 py-4 text-xs font-bold text-on-surface-variant uppercase tracking-wider">
              Phase 2
            </th>
            <th className="px-6 py-4 text-xs font-bold text-on-surface-variant uppercase tracking-wider text-right">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-outline-variant/20">
          {runs.map((entry) => {
            const phase1Variant = statusVariant(entry.phase1_status);
            const phase2Variant = statusVariant(entry.phase2_status);
            const hatchetVariant = statusVariant(entry.hatchet_status);
            return (
              <tr key={entry.run_id} className="group hover:bg-surface-container/30 transition-colors">
                <td className="px-6 py-5 font-mono text-sm text-on-surface font-medium">
                  {entry.run_id}
                </td>
                <td className="px-6 py-5 text-on-surface-variant">
                  {entry.upload_time_utc ?? "—"}
                </td>
                <td className="px-6 py-5">
                  <div className="flex flex-wrap gap-2">
                    <RunStatusBadge label={phase1Label(entry.phase1_status)} variant={phase1Variant} />
                    {entry.hatchet_status && (
                      <RunStatusBadge label={`Logs ${entry.hatchet_status}`} variant={hatchetVariant} />
                    )}
                  </div>
                </td>
                <td className="px-6 py-5">
                  <RunStatusBadge label={phase2PhaseLabel(entry.phase2_status)} variant={phase2Variant} />
                </td>
                <td className="px-6 py-5 text-right">
                  <a
                    href={`/runs/${encodeURIComponent(entry.run_id)}`}
                    className="text-brand-primary font-semibold hover:underline decoration-2 transition-all"
                  >
                    View
                  </a>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
