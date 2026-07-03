import type { ReactNode } from 'react'

export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-4 border-b border-slate-800/80 px-4 py-3">
          {title && (
            <h2 className="text-sm font-semibold tracking-wide text-slate-300">{title}</h2>
          )}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}
