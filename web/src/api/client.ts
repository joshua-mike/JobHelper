import type {
  ConfigName,
  ConfigPayload,
  FunnelEntry,
  RecentJob,
  ResumeImportResult,
  ReviewAction,
  ReviewActionResult,
  ReviewLists,
  RunLogEntry,
  RunStatus,
  SaveResult,
  SettingsStatus,
  SourceStats,
  Summary,
  TimelinePoint,
  VerifySourceRequest,
  VerifySourceResult,
} from './types'

// Same-origin in production (FastAPI serves the build); Vite proxies in dev.
async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`)
  return res.json() as Promise<T>
}

/** Error carrying per-field validation messages from a 422 response. */
export class ApiError extends Error {
  details?: string[]
}

async function throwApiError(res: Response, fallback: string): Promise<never> {
  const err = new ApiError(fallback)
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') {
      err.message = body.detail
    } else if (Array.isArray(body.detail)) {
      // pydantic errors: {loc: ["work_history", 0, "company"], msg: "..."}
      err.details = body.detail.map(
        (d: { loc?: (string | number)[]; msg?: string }) =>
          `${(d.loc ?? []).join('.') || 'config'}: ${d.msg ?? 'invalid'}`,
      )
      err.message = 'Validation failed — nothing was saved.'
    }
  } catch {
    /* keep fallback message */
  }
  throw err
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

  // ---- Settings -------------------------------------------------------------
  settingsStatus: () => getJson<SettingsStatus>('/api/settings'),

  getConfig: <T>(name: ConfigName) =>
    getJson<ConfigPayload<T>>(`/api/settings/${name}`),

  saveConfig: async <T>(name: ConfigName, data: T): Promise<SaveResult> => {
    const res = await fetch(`/api/settings/${name}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) await throwApiError(res, `Save failed (HTTP ${res.status})`)
    return res.json() as Promise<SaveResult>
  },

  verifySource: async (req: VerifySourceRequest): Promise<VerifySourceResult> => {
    const res = await fetch('/api/settings/sources/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (!res.ok) await throwApiError(res, `Verify failed (HTTP ${res.status})`)
    return res.json() as Promise<VerifySourceResult>
  },

  importResume: async (file: File): Promise<ResumeImportResult> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/settings/profile/import-resume', {
      method: 'POST',
      body: form,
    })
    if (!res.ok) await throwApiError(res, `Import failed (HTTP ${res.status})`)
    return res.json() as Promise<ResumeImportResult>
  },
}
