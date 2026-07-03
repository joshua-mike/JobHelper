import { Clock, Inbox, Send, Sparkles } from 'lucide-react'
import { REVIEW_URL } from '../api/client'
import {
  useFunnel,
  useRecentJobs,
  useSources,
  useSummary,
  useTimeline,
} from '../api/hooks'
import { TimelineChart } from '../components/charts/TimelineChart'
import { FunnelBars } from '../components/dashboard/FunnelBars'
import { RecentJobsTable } from '../components/dashboard/RecentJobsTable'
import { SourcesTable } from '../components/dashboard/SourcesTable'
import { Card } from '../components/ui/card'
import { StatCard } from '../components/ui/stat-card'
import { fmtDuration, timeAgo } from '../lib/format'

export default function DashboardPage() {
  const summary = useSummary()
  const timeline = useTimeline(30)
  const funnel = useFunnel()
  const sources = useSources()
  const recent = useRecentJobs(10)
  const s = summary.data

  return (
    <div className="space-y-6">
      {summary.isError && (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          Failed to load metrics — is the API running? ({String(summary.error)})
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Last run"
          icon={Clock}
          value={
            s?.last_run ? timeAgo(s.last_run.finished_at ?? s.last_run.started_at) : '—'
          }
          sub={
            s?.last_run
              ? `${s.last_run.proposed} proposed · ${fmtDuration(s.last_run.duration_seconds)}`
              : 'No runs recorded yet'
          }
        />
        <StatCard
          label="Proposed today"
          icon={Sparkles}
          value={s ? s.proposed_today : '…'}
          sub="jobs selected for today's digest"
        />
        <StatCard
          label="Pending review"
          icon={Inbox}
          value={s ? s.pending_review : '…'}
          sub="waiting on the review page"
        />
        <StatCard
          label="Applied (7d)"
          icon={Send}
          value={s ? s.applied_7d : '…'}
          sub={s ? `${s.applied_total} applications total` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card title="Activity — last 30 days" className="xl:col-span-2">
          <TimelineChart data={timeline.data ?? []} />
        </Card>
        <Card title="Pipeline states">
          <FunnelBars data={funnel.data ?? []} />
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Sources">
          <SourcesTable data={sources.data ?? []} />
        </Card>
        <Card
          title="Recent proposals"
          action={
            <a
              href={REVIEW_URL}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-medium text-indigo-400 hover:underline"
            >
              Open review page ↗
            </a>
          }
        >
          <RecentJobsTable data={recent.data ?? []} />
        </Card>
      </div>
    </div>
  )
}
