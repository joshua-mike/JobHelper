import { Undo2 } from 'lucide-react'
import type { ReviewAction, ReviewJob } from '../../api/types'
import { fmtDateTime } from '../../lib/format'
import { Button } from '../ui/button'

/** Compact applied/skipped history rows with an undo (reset) button. */
export function DoneList({
  jobs,
  mode,
  onAction,
  busy,
}: {
  jobs: ReviewJob[]
  mode: 'applied' | 'skipped'
  onAction: (id: number, action: ReviewAction) => void
  busy: boolean
}) {
  if (jobs.length === 0) {
    return <p className="text-sm text-slate-500">None yet.</p>
  }
  return (
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
            <span className="text-slate-500">
              {' '}
              — {j.company ?? 'Unknown company'}
              {mode === 'applied' && j.applied_at ? ` · ${fmtDateTime(j.applied_at)}` : ''}
            </span>
          </div>
          <Button
            variant="ghost"
            className="px-2.5 py-1 text-xs"
            disabled={busy}
            onClick={() => onAction(j.id, 'reset')}
            title="Back to the review queue"
          >
            <Undo2 className="h-3.5 w-3.5" />
            {mode === 'applied' ? 'undo' : 'restore'}
          </Button>
        </li>
      ))}
    </ul>
  )
}
