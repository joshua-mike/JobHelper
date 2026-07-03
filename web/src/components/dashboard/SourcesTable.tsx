import type { SourceStats } from '../../api/types'

export function SourcesTable({ data }: { data: SourceStats[] }) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No jobs ingested yet — start a run to pull from your configured boards.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wider text-slate-500">
            <th className="pb-2 pr-4 font-medium">Source</th>
            <th className="pb-2 pr-4 text-right font-medium">Jobs</th>
            <th className="pb-2 pr-4 text-right font-medium">New (7d)</th>
            <th className="pb-2 pr-4 text-right font-medium">Surfaced</th>
            <th className="pb-2 text-right font-medium">Avg AI score</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {data.map((s) => (
            <tr key={s.source}>
              <td className="py-2 pr-4 font-medium text-slate-200">{s.source}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">
                {s.total.toLocaleString()}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{s.new_7d}</td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-300">{s.surfaced}</td>
              <td className="py-2 text-right tabular-nums text-slate-300">
                {s.avg_llm_score ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
