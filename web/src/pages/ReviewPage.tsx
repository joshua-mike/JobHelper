import { Download } from 'lucide-react'
import { api } from '../api/client'
import { useFunnel, useReviewAction, useReviewJobs } from '../api/hooks'
import type { ReviewAction } from '../api/types'
import { DoneList } from '../components/review/DoneList'
import { ReviewJobCard } from '../components/review/ReviewJobCard'
import { Card } from '../components/ui/card'
import { useToast } from '../components/ui/toast'

const TOAST: Record<ReviewAction, string> = {
  applied: 'Marked applied — added to your applications log.',
  approve: 'Approved.',
  skip: 'Skipped.',
  reset: 'Undone — back in the review queue.',
}

export default function ReviewPage() {
  const { data, isError } = useReviewJobs()
  const funnel = useFunnel()
  const act = useReviewAction()
  const toast = useToast()

  const pending = data?.pending ?? []
  const applied = data?.applied ?? []
  const skipped = data?.skipped ?? []

  const counts = Object.fromEntries((funnel.data ?? []).map((f) => [f.status, f.count]))
  const backlog = (counts.new ?? 0) + (counts.ranked ?? 0) + (counts.scored ?? 0)
  const busyId = act.isPending ? (act.variables?.id ?? null) : null

  const onAction = (id: number, action: ReviewAction) => {
    act.mutate(
      { id, action },
      {
        onSuccess: () => toast('success', TOAST[action]),
        onError: (e) => toast('error', e.message),
      },
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Review</h1>
          <p className="mt-1 text-sm text-slate-500">
            <span className="font-semibold text-slate-300">{pending.length}</span> to review ·{' '}
            <span className="font-semibold text-slate-300">{counts.applied ?? 0}</span> applied ·{' '}
            <span className="font-semibold text-slate-300">{counts.skipped ?? 0}</span> skipped ·{' '}
            {counts.filtered_out ?? 0} filtered · {backlog} in backlog
          </p>
        </div>
        {(counts.applied ?? 0) > 0 && (
          <a
            href={api.applicationsCsvUrl}
            className="inline-flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300"
          >
            <Download className="h-4 w-4" /> applications log (CSV)
          </a>
        )}
      </div>

      {isError && (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
          Could not load the review board — is the API running?
        </p>
      )}

      {pending.length === 0 && !isError ? (
        <div className="rounded-xl border border-dashed border-slate-700 p-10 text-center text-sm text-slate-500">
          Nothing to review. Start a daily run to generate today's proposals.
        </div>
      ) : (
        <div className="space-y-4">
          {pending.map((job) => (
            <ReviewJobCard
              key={job.id}
              job={job}
              onAction={onAction}
              busy={busyId === job.id}
            />
          ))}
        </div>
      )}

      {applied.length > 0 && (
        <Card title={`Applied (${applied.length})`}>
          <DoneList jobs={applied} mode="applied" onAction={onAction} busy={act.isPending} />
        </Card>
      )}
      {skipped.length > 0 && (
        <Card title={`Skipped (${skipped.length})`}>
          <DoneList jobs={skipped} mode="skipped" onAction={onAction} busy={act.isPending} />
        </Card>
      )}

      <p className="text-center text-xs text-slate-600">
        Nothing is ever submitted automatically — actions only track your own manual
        applications.
      </p>
    </div>
  )
}
