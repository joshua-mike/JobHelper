import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: LucideIcon
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-slate-600" />}
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-100">{value}</p>
      {sub && <p className="mt-1 truncate text-xs text-slate-500">{sub}</p>}
    </div>
  )
}
