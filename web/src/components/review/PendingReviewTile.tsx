import { ArrowRight, Check, Star, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ReviewAction, ReviewJob } from '../../api/types'
import { useReviewAction, useReviewJobs } from '../../api/hooks'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { ScorePill } from '../ui/score-pill'
import { useToast } from '../ui/toast'

const TOAST: Record<string, string> = {
  applied: 'Marked applied — added to your applications log.',
  approve: 'Approved.',
  skip: 'Skipped.',
}

/** Compact review queue for the Runs page — appears when a finished run left
 *  proposals waiting, so review starts right where the run happened. */
export function PendingReviewTile() {
  const { data } = useReviewJobs()
  const act = useReviewAction()
  const toast = useToast()
  const pending = data?.pending ?? []
  if (pending.length === 0) return null

  const onAction = (id: number, action: ReviewAction) => {
    act.mutate(
      { id, action },
      {
        onSuccess: () => toast('success', TOAST[action] ?? 'Done.'),
        onError: (e) => toast('error', e.message),
      },
    )
  }

  return (
    <Card
      title={`Pending review (${pending.length})`}
      action={
        <Link
          to="/review"
          className="inline-flex items-center gap-1 text-xs font-medium text-indigo-400 hover:text-indigo-300"
        >
          Open review board <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      }
    >
      <ul className="divide-y divide-slate-800/60">
        {pending.map((j: ReviewJob) => (
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
              </p>
            </div>
            <div className="flex shrink-0 gap-1.5">
              <Button
                variant="ghost"
                className="px-2 py-1 text-xs text-emerald-400 hover:text-emerald-300"
                disabled={act.isPending}
                onClick={() => onAction(j.id, 'applied')}
                title="Mark applied"
              >
                <Check className="h-3.5 w-3.5" /> applied
              </Button>
              {j.status !== 'approved' && (
                <Button
                  variant="ghost"
                  className="px-2 py-1 text-xs text-indigo-400 hover:text-indigo-300"
                  disabled={act.isPending}
                  onClick={() => onAction(j.id, 'approve')}
                  title="Approve for later"
                >
                  <Star className="h-3.5 w-3.5" /> approve
                </Button>
              )}
              <Button
                variant="ghost"
                className="px-2 py-1 text-xs"
                disabled={act.isPending}
                onClick={() => onAction(j.id, 'skip')}
                title="Skip this job"
              >
                <X className="h-3.5 w-3.5" /> skip
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}
