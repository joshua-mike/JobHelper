// Mirrors src/jobhelper/web/schemas.py — keep the two in sync.

export interface LastRun {
  run_id: string
  started_at: string | null
  finished_at: string | null
  sourced: number
  new_jobs: number
  filtered: number
  scored: number
  proposed: number
  errors: number
  notes: string | null
  duration_seconds: number | null
}

export interface Summary {
  last_run: LastRun | null
  proposed_today: number
  pending_review: number
  applied_total: number
  applied_7d: number
  total_jobs: number
  new_7d: number
}

export interface FunnelEntry {
  status: string
  count: number
}

export interface TimelinePoint {
  date: string
  new: number
  proposed: number
  applied: number
}

export interface SourceStats {
  source: string
  total: number
  new_7d: number
  surfaced: number
  avg_llm_score: number | null
}

export interface RunLogEntry extends LastRun {
  run_state: 'complete' | 'incomplete' | 'running'
}

export interface RecentJob {
  id: number
  title: string | null
  company: string | null
  source: string
  url: string | null
  status: string
  llm_score: number | null
  display_score: number | null
  proposed_in_run_id: string | null
  applied_at: string | null
  updated_at: string | null
}

export interface RunStatus {
  state: 'idle' | 'running'
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  use_cache: boolean
  log_path: string | null
  line_count: number
}
