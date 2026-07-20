import type { FunnelEntry } from '../../api/types'

const LABELS: Record<string, string> = {
  new: 'New (unprocessed)',
  duplicate: 'Duplicates',
  filtered_out: 'Filtered out',
  ranked: 'Ranked',
  scored: 'Scored',
  expired: 'Expired (aged out)',
  proposed: 'Proposed',
  tailored: 'Tailored',
  approved: 'Approved',
  applied: 'Applied',
  skipped: 'Skipped',
  error: 'Errored',
}

const COLORS: Record<string, string> = {
  applied: 'bg-emerald-500/70',
  approved: 'bg-amber-500/70',
  error: 'bg-rose-500/70',
  duplicate: 'bg-slate-600/70',
  filtered_out: 'bg-slate-600/70',
  expired: 'bg-slate-600/70',
  skipped: 'bg-slate-600/70',
}

export function FunnelBars({ data }: { data: FunnelEntry[] }) {
  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No pipeline data yet.</p>
  }
  const max = Math.max(1, ...data.map((d) => d.count))
  return (
    <div className="space-y-2.5">
      {data.map((d) => (
        <div key={d.status} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-xs text-slate-400">
            {LABELS[d.status] ?? d.status}
          </span>
          <div className="h-4 flex-1 overflow-hidden rounded bg-slate-800/60">
            <div
              className={`h-full rounded ${COLORS[d.status] ?? 'bg-indigo-500/70'}`}
              style={{
                width: `${d.count > 0 ? Math.max(2, (d.count / max) * 100) : 0}%`,
              }}
            />
          </div>
          <span className="w-16 shrink-0 text-right text-xs tabular-nums text-slate-300">
            {d.count.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  )
}
