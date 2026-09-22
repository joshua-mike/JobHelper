import { ShieldCheck } from 'lucide-react'
import type { ReviewJob } from '../../api/types'
import { Button } from '../ui/button'

/** Jobs parked by the direct-hire gate, with the reason and a rescue button. */
export function ParkedList({
  jobs,
  total,
  onNotStaffing,
  busy,
}: {
  jobs: ReviewJob[]
  total: number
  onNotStaffing: (job: ReviewJob) => void
  busy: boolean
}) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Parked as staffing-agency or contract postings.{' '}
        <span className="text-slate-400">Not staffing</span> adds the company to your allow list
        and returns its jobs to the pool — they're scored on the next run.
        {total > jobs.length && ` Showing the ${jobs.length} newest of ${total}.`}
      </p>
      <ul className="divide-y divide-slate-800/60">
        {jobs.map((j) => (
          <li key={j.id} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1 text-sm">
              {j.url ? (
                <a
                  href={j.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-slate-200 hover:text-indigo-400"
                >
                  {j.title ?? 'Untitled role'}
                </a>
              ) : (
                <span className="font-medium text-slate-200">{j.title ?? 'Untitled role'}</span>
              )}
              <span className="text-slate-500"> — {j.company ?? 'Unknown company'}</span>
              {j.status_reason && (
                <p className="truncate text-xs text-slate-500" title={j.status_reason}>
                  {j.status_reason.replace(/^staffing:\s*/, '')}
                </p>
              )}
            </div>
            <Button
              variant="ghost"
              className="px-2.5 py-1 text-xs"
              disabled={busy}
              onClick={() => onNotStaffing(j)}
              title="Allow-list this company and return its jobs to the pool"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Not staffing
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}
