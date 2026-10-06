import type { ModelUsage, RunLogEntry } from '../../api/types'
import { fmtDateTime, fmtDuration, fmtTokens, fmtUsd } from '../../lib/format'
import { Badge, type Tone } from '../ui/badge'

const STATE_TONE: Record<RunLogEntry['run_state'], Tone> = {
  complete: 'green',
  incomplete: 'yellow',
  running: 'blue',
}

/** Per-model breakdown for the LLM cell's hover tooltip. */
function usageTitle(usage: ModelUsage[]): string {
  return usage
    .map(
      (u) =>
        `${u.model}: ${u.calls} calls, ${fmtTokens(u.input_tokens)} in, ` +
        `${fmtTokens(u.output_tokens)} out, ${fmtTokens(u.cache_read_input_tokens)} cache read, ` +
        `${fmtTokens(u.cache_creation_input_tokens)} cache write — ${fmtUsd(u.cost_usd)}`,
    )
    .join('\n')
}

function LlmCell({ run }: { run: RunLogEntry }) {
  if (run.llm_usage.length === 0) return <span className="text-slate-600">—</span>
  const tokIn = run.llm_usage.reduce(
    (s, u) => s + u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens,
    0,
  )
  const tokOut = run.llm_usage.reduce((s, u) => s + u.output_tokens, 0)
  return (
    <span title={usageTitle(run.llm_usage)} className="cursor-help">
      <span className="font-medium text-slate-100">{fmtUsd(run.llm_cost_usd)}</span>
      <span className="block text-xs text-slate-500">
        {fmtTokens(tokIn)} in · {fmtTokens(tokOut)} out
      </span>
    </span>
  )
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
            <th className="pb-2 pr-4 text-right font-medium" title="Estimated Claude API cost and tokens; hover a cell for per-model detail">
              LLM est.
            </th>
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
              <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">
                <LlmCell run={r} />
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
