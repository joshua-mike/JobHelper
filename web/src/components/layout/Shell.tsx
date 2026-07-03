import { Activity, ClipboardCheck, Gauge, Loader2, Play, Settings } from 'lucide-react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useRunStatus, useStartRun, useSummary } from '../../api/hooks'
import type { RunStatus } from '../../api/types'
import { fmtDateTime } from '../../lib/format'
import { Button } from '../ui/button'
import { useToast } from '../ui/toast'

const NAV = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/runs', label: 'Runs', icon: Activity },
  { to: '/review', label: 'Review', icon: ClipboardCheck },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function StatusPill({ status }: { status?: RunStatus }) {
  const running = status?.state === 'running'
  return (
    <div className="flex items-center gap-2 text-sm text-slate-400">
      <span
        className={`h-2.5 w-2.5 rounded-full ${
          running ? 'animate-pulse bg-emerald-400' : 'bg-slate-600'
        }`}
      />
      {running ? (
        <span>
          Run in progress
          <span className="hidden sm:inline"> — started {fmtDateTime(status?.started_at)}</span>
        </span>
      ) : (
        'Idle'
      )}
    </div>
  )
}

export function Shell() {
  const { data: status } = useRunStatus()
  const { data: summary } = useSummary()
  const startRun = useStartRun()
  const navigate = useNavigate()
  const toast = useToast()
  const running = status?.state === 'running'
  const pendingReview = summary?.pending_review ?? 0

  const onRunNow = () => {
    startRun.mutate(false, {
      onSuccess: () => {
        toast('info', 'Daily run started.')
        navigate('/runs')
      },
      onError: (e) => {
        toast('error', e.message)
        navigate('/runs')
      },
    })
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
        <div className="px-5 py-5 text-lg font-bold tracking-tight">
          Job<span className="text-indigo-400">Helper</span>
        </div>
        <nav className="flex flex-col gap-1 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-slate-800/80 text-slate-100'
                    : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
              {to === '/review' && pendingReview > 0 && (
                <span className="ml-auto rounded-full bg-indigo-500/15 px-2 py-0.5 text-xs font-semibold text-indigo-300 ring-1 ring-inset ring-indigo-500/30">
                  {pendingReview}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <p className="mt-auto px-5 py-4 text-xs text-slate-600">
          Local only · nothing is ever auto-submitted
        </p>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-6 py-3.5 backdrop-blur">
          <StatusPill status={status} />
          <Button onClick={onRunNow} disabled={running || startRun.isPending}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Running…' : 'Run now'}
          </Button>
        </header>
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
