import { Check, Loader2, Plus, RotateCcw, Save, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { VerifySourceResult } from '../../api/types'
import { Button } from '../ui/button'

export const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-sm ' +
  'text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 ' +
  'focus:outline-none disabled:cursor-not-allowed disabled:opacity-50'

export function Field({
  label,
  hint,
  children,
  className = '',
}: {
  label: string
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

export function TextInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string | undefined | null
  onChange: (v: string) => void
  placeholder?: string
  disabled?: boolean
}) {
  return (
    <input
      type="text"
      className={inputCls}
      value={value ?? ''}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/** Number input that treats an empty box as null (field cleared). */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  placeholder,
}: {
  value: number | undefined | null
  onChange: (v: number | null) => void
  min?: number
  max?: number
  step?: number
  placeholder?: string
}) {
  return (
    <input
      type="number"
      className={inputCls}
      value={value ?? ''}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      onChange={(e) => {
        const raw = e.target.value
        onChange(raw === '' ? null : Number(raw))
      }}
    />
  )
}

export function TextArea({
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  value: string | undefined | null
  onChange: (v: string) => void
  rows?: number
  placeholder?: string
}) {
  return (
    <textarea
      className={`${inputCls} resize-y`}
      value={value ?? ''}
      rows={rows}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

export function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string | undefined | null
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <select
      className={inputCls}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

/** Inline result of a per-entry live source check. */
export function VerifyBadge({
  state,
}: {
  state: { loading: boolean; result?: VerifySourceResult; error?: string } | undefined
}) {
  if (!state) return null
  if (state.loading)
    return (
      <span className="inline-flex items-center gap-1 text-xs text-slate-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> checking…
      </span>
    )
  const r = state.result
  if (state.error || !r)
    return <span className="text-xs text-rose-400">{state.error ?? 'failed'}</span>
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${
        r.ok ? 'text-emerald-400' : 'text-rose-400'
      }`}
      title={r.sample.length ? `e.g. ${r.sample.join(' · ')}` : undefined}
    >
      {r.ok ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
      {r.message}
      {r.ok && r.company ? ` — ${r.company}` : ''}
    </span>
  )
}

export type VerifyState = { loading: boolean; result?: VerifySourceResult; error?: string }

/** Editable list of strings: per-row edit/remove, add row, optional Verify. */
export function StringListEditor({
  items,
  onChange,
  placeholder,
  addLabel = 'Add',
  mono = false,
  onVerify,
  verifyStates,
}: {
  items: string[]
  onChange: (items: string[]) => void
  placeholder?: string
  addLabel?: string
  mono?: boolean
  onVerify?: (value: string, index: number) => void
  verifyStates?: Record<number, VerifyState>
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const v = draft.trim()
    if (!v) return
    onChange([...items, v])
    setDraft('')
  }
  return (
    <div className="space-y-1.5">
      {items.map((item, i) => (
        <div key={i}>
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              className={`${inputCls} ${mono ? 'font-mono' : ''}`}
              value={item}
              onChange={(e) =>
                onChange(items.map((x, j) => (j === i ? e.target.value : x)))
              }
            />
            {onVerify && (
              <Button
                variant="outline"
                className="shrink-0 px-2.5 py-1.5 text-xs"
                disabled={!item.trim() || verifyStates?.[i]?.loading}
                onClick={() => onVerify(item.trim(), i)}
              >
                Verify
              </Button>
            )}
            <button
              type="button"
              className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
              title="Remove"
              onClick={() => onChange(items.filter((_, j) => j !== i))}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {verifyStates?.[i] && (
            <div className="mt-0.5 pl-1">
              <VerifyBadge state={verifyStates[i]} />
            </div>
          )}
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          className={`${inputCls} ${mono ? 'font-mono' : ''}`}
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <Button
          variant="outline"
          className="shrink-0 px-2.5 py-1.5 text-xs"
          disabled={!draft.trim()}
          onClick={add}
        >
          <Plus className="h-3.5 w-3.5" />
          {addLabel}
        </Button>
      </div>
    </div>
  )
}

/** Per-section footer: dirty state, validation errors, Discard + Save. */
export function SaveBar({
  dirty,
  saving,
  errors,
  onSave,
  onDiscard,
}: {
  dirty: boolean
  saving: boolean
  errors: string[]
  onSave: () => void
  onDiscard: () => void
}) {
  return (
    <div className="sticky bottom-0 z-10 -mx-1 rounded-xl border border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur">
      {errors.length > 0 && (
        <ul className="mb-2 space-y-0.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-slate-500">
          {dirty ? 'Unsaved changes' : 'No changes'}
        </span>
        <div className="flex items-center gap-2">
          <Button variant="ghost" disabled={!dirty || saving} onClick={onDiscard}>
            <RotateCcw className="h-4 w-4" />
            Discard
          </Button>
          <Button disabled={!dirty || saving} onClick={onSave}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save
          </Button>
        </div>
      </div>
    </div>
  )
}
