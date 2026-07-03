import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Kind = 'success' | 'error' | 'info'
interface Toast {
  id: number
  kind: Kind
  text: string
}

const ToastCtx = createContext<(kind: Kind, text: string) => void>(() => {})

export function useToast() {
  return useContext(ToastCtx)
}

const kindClasses: Record<Kind, string> = {
  success: 'border-emerald-500/40 text-emerald-300',
  error: 'border-rose-500/40 text-rose-300',
  info: 'border-slate-600 text-slate-200',
}

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((kind: Kind, text: string) => {
    const id = nextId++
    setToasts((t) => [...t, { id, kind, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000)
  }, [])

  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-lg border bg-slate-900/95 px-4 py-3 text-sm shadow-lg backdrop-blur ${kindClasses[t.kind]}`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
