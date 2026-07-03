import type {
  FunnelEntry,
  RecentJob,
  ReviewAction,
  ReviewActionResult,
  ReviewLists,
  RunLogEntry,
  RunStatus,
  SourceStats,
  Summary,
  TimelinePoint,
} from './types'

// Same-origin in production (FastAPI serves the build); Vite proxies in dev.
async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`)
  return res.json() as Promise<T>
}

export const api = {
  summary: () => getJson<Summary>('/api/summary'),
  funnel: () => getJson<FunnelEntry[]>('/api/funnel'),
  timeline: (days = 30) => getJson<TimelinePoint[]>(`/api/timeline?days=${days}`),
  sources: () => getJson<SourceStats[]>('/api/sources'),
  runs: (limit = 20) => getJson<RunLogEntry[]>(`/api/runs?limit=${limit}`),
  recentJobs: (limit = 15) => getJson<RecentJob[]>(`/api/jobs/recent?limit=${limit}`),
  runStatus: () => getJson<RunStatus>('/api/run/status'),

  startRun: async (useCache: boolean): Promise<RunStatus> => {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_cache: useCache }),
    })
    if (res.status === 409) throw new Error('A run is already in progress.')
    if (!res.ok) throw new Error(`Failed to start run (HTTP ${res.status})`)
    return res.json() as Promise<RunStatus>
  },

  reviewJobs: () => getJson<ReviewLists>('/api/review/jobs'),

  reviewAction: async (id: number, action: ReviewAction): Promise<ReviewActionResult> => {
    const res = await fetch(`/api/review/jobs/${id}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    if (!res.ok) throw new Error(`Review action failed (HTTP ${res.status})`)
    return res.json() as Promise<ReviewActionResult>
  },

  assistApply: async (id: number): Promise<void> => {
    const res = await fetch(`/api/review/jobs/${id}/assist`, { method: 'POST' })
    if (res.status === 409)
      throw new Error("Assisted apply isn't available for this job's ATS.")
    if (!res.ok) throw new Error(`Failed to launch assisted apply (HTTP ${res.status})`)
  },

  resumeUrl: (id: number) => `/api/review/jobs/${id}/resume`,
  applicationsCsvUrl: '/api/review/applications.csv',
}
