import type { RunLogEntry } from '../../api/types'
import { fmtDateTime, fmtDuration } from '../../lib/format'
import { Badge, type Tone } from '../ui/badge'

const STATE_TONE: Record<RunLogEntry['run_state'], Tone> = {
  complete: 'green',
  incomplete: 'yellow',
  running: 'blue',
}

export function RunsTable({ data }: { data: RunLogEntry[] }) {
  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No runs recorded yet.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wider text-slate-500">
            <th className="pb-2 pr-4 font-medium">Started</th>
            <th className="pb-2 pr-4 text-right font-medium">Duration</th>
            <th className="pb-2 pr-4 text-right font-medium">Sourced</th>
            <th className="pb-2 pr-4 text-right font-medium">New</th>
            <th className="pb-2 pr-4 text-right font-medium">Filtered</th>
            <th className="pb-2 pr-4 text-right font-medium">Scored</th>
            <th className="pb-2 pr-4 text-right font-medium">Proposed</th>
            <th className="pb-2 pr-4 text-right font-medium">Errors</th>
            <th className="pb-2 font-medium">State</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {data.map((r) => (
            <tr key={r.run_id}>
              <td className="py-2 pr-4 whitespace-nowrap text-slate-200">
                {fmtDateTime(r.started_at)}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">
                {fmtDuration(r.duration_seconds)}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{r.sourced}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{r.new_jobs}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{r.filtered}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{r.scored}</td>
              <td className="py-2 pr-4 text-right tabular-nums font-medium text-slate-100">
                {r.proposed}
              </td>
              <td
                className={`py-2 pr-4 text-right tabular-nums ${
                  r.errors > 0 ? 'font-medium text-rose-400' : 'text-slate-300'
                }`}
              >
                {r.errors}
              </td>
              <td className="py-2">
                <Badge tone={STATE_TONE[r.run_state]}>{r.run_state}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
