import type { Tone } from '../components/ui/badge'

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const h = Math.round(min / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

/** run_id / proposed_in_run_id format is YYYYMMDDTHHMMSS (see pipeline). */
export function fmtRunDay(runId: string | null | undefined): string {
  if (!runId || runId.length < 8) return '—'
  const d = new Date(+runId.slice(0, 4), +runId.slice(4, 6) - 1, +runId.slice(6, 8))
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export const STATUS_TONE: Record<string, Tone> = {
  new: 'slate',
  ranked: 'blue',
  scored: 'blue',
  proposed: 'blue',
  tailored: 'violet',
  approved: 'yellow',
  applied: 'green',
  skipped: 'slate',
  filtered_out: 'slate',
  duplicate: 'slate',
  error: 'red',
}
