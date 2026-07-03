export function ScorePill({ score }: { score: number | null }) {
  const tone =
    score == null
      ? 'text-slate-500 ring-slate-700'
      : score >= 75
        ? 'text-emerald-400 ring-emerald-500/40'
        : score >= 55
          ? 'text-amber-400 ring-amber-500/40'
          : 'text-rose-400 ring-rose-500/40'
  return (
    <span
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums ring-1 ${tone}`}
    >
      {score ?? '—'}
    </span>
  )
}
