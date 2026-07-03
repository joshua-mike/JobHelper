import type { ReactNode } from 'react'

const tones = {
  green: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30',
  yellow: 'bg-amber-500/15 text-amber-400 ring-amber-500/30',
  red: 'bg-rose-500/15 text-rose-400 ring-rose-500/30',
  blue: 'bg-sky-500/15 text-sky-400 ring-sky-500/30',
  violet: 'bg-violet-500/15 text-violet-400 ring-violet-500/30',
  slate: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
} as const

export type Tone = keyof typeof tones

export function Badge({ tone = 'slate', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}
    >
      {children}
    </span>
  )
}
