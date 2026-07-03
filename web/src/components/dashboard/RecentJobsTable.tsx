import type { RecentJob } from '../../api/types'
import { STATUS_TONE, fmtRunDay } from '../../lib/format'
import { Badge } from '../ui/badge'
import { ScorePill } from '../ui/score-pill'

export function RecentJobsTable({ data }: { data: RecentJob[] }) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        Nothing proposed yet — run the pipeline to surface matches.
      </p>
    )
  }
  return (
    <ul className="divide-y divide-slate-800/60">
      {data.map((j) => (
        <li key={j.id} className="flex items-center gap-3 py-2.5">
          <ScorePill score={j.display_score} />
          <div className="min-w-0 flex-1">
            {j.url ? (
              <a
                href={j.url}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-sm font-medium text-slate-200 hover:text-indigo-400"
              >
                {j.title ?? 'Untitled role'}
              </a>
            ) : (
              <span className="block truncate text-sm font-medium text-slate-200">
                {j.title ?? 'Untitled role'}
              </span>
            )}
            <p className="truncate text-xs text-slate-500">
              {j.company ?? 'Unknown company'} · {j.source}
              {j.proposed_in_run_id ? ` · ${fmtRunDay(j.proposed_in_run_id)}` : ''}
            </p>
          </div>
          <Badge tone={STATUS_TONE[j.status] ?? 'slate'}>{j.status}</Badge>
        </li>
      ))}
    </ul>
  )
}
