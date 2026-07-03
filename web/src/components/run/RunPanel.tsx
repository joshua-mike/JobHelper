import { Loader2, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useStartRun } from '../../api/hooks'
import type { RunStatus } from '../../api/types'
import { fmtDuration, timeAgo } from '../../lib/format'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Switch } from '../ui/switch'
import { useToast } from '../ui/toast'
import { useRunStream } from './useRunStream'

function useElapsed(sinceIso: string | null | undefined): string | null {
  const [, force] = useState(0)
  useEffect(() => {
    if (!sinceIso) return
    const t = setInterval(() => force((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [sinceIso])
  if (!sinceIso) return null
  const s = Math.max(0, Math.floor((Date.now() - new Date(sinceIso).getTime()) / 1000))
  return fmtDuration(s)
}

function LogViewer({ lines, running }: { lines: string[]; running: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)

  useEffect(() => {
    if (pinned && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [lines, pinned])

  const onScroll = () => {
    const el = ref.current
    if (!el) return
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40)
  }

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      className="mt-4 h-72 overflow-y-auto rounded-lg border border-slate-800 bg-black/60 p-3 font-mono text-xs leading-relaxed text-slate-300"
    >
      {lines.length === 0 ? (
        <p className="text-slate-600">
          {running ? 'Waiting for output…' : 'No run output yet — start a run to see live logs.'}
        </p>
      ) : (
        lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap">
            {line || ' '}
          </div>
        ))
      )}
      {running && <div className="animate-pulse text-slate-500">▋</div>}
    </div>
  )
}

export function RunPanel({
  status,
  onFinished,
}: {
  status?: RunStatus
  onFinished: () => void
}) {
  const [useCache, setUseCache] = useState(false)
  const startRun = useStartRun()
  const toast = useToast()
  const running = status?.state === 'running'

  // Reopen the log stream whenever a new run starts (started_at changes).
  const streamKey = status ? (status.started_at ?? 'no-run-yet') : null
  const lines = useRunStream(streamKey, onFinished)

  // Toast on the running -> idle transition.
  const prevRunning = useRef(false)
  useEffect(() => {
    if (prevRunning.current && !running && status) {
      if (status.exit_code === 0) toast('success', 'Daily run finished.')
      else toast('error', `Run exited with code ${String(status.exit_code ?? '?')}.`)
    }
    prevRunning.current = running
  }, [running, status, toast])

  const elapsed = useElapsed(running ? status?.started_at : null)

  return (
    <Card
      title="Run control"
      action={
        running ? (
          <span className="flex items-center gap-2 text-xs text-emerald-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            running · {elapsed}
          </span>
        ) : undefined
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-xl">
          <p className="text-sm leading-relaxed text-slate-400">
            Executes{' '}
            <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
              python run_daily.py
            </code>{' '}
            — sources every configured board, filters, scores, tailors resumes, and writes
            today's digest. Typically 1–5 minutes.
          </p>
          <div className="mt-3">
            <Switch
              checked={useCache}
              onChange={setUseCache}
              disabled={running}
              label="Use cached fetches (dev/debug)"
            />
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button
            onClick={() =>
              startRun.mutate(useCache, {
                onError: (e) => toast('error', e.message),
              })
            }
            disabled={running || startRun.isPending}
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Running…' : 'Start daily run'}
          </Button>
          {!running && status?.finished_at && (
            <p className="text-xs text-slate-500">
              Last: exit {status.exit_code ?? '—'} · {timeAgo(status.finished_at)}
              {status.use_cache ? ' · cached' : ''}
            </p>
          )}
        </div>
      </div>
      <LogViewer lines={lines} running={running} />
    </Card>
  )
}
