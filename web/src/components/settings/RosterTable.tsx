import { Plus, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { SourceKind, SourcesData, WorkdayRow } from '../../api/types'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { inputCls, VerifyBadge, type VerifyState } from './fields'

const BOARD_TYPES = ['greenhouse', 'lever', 'ashby', 'smartrecruiters'] as const
type BoardType = (typeof BOARD_TYPES)[number]

const KIND_BADGE: Record<string, string> = {
  greenhouse: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  lever: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
  ashby: 'border-violet-500/30 bg-violet-500/10 text-violet-300',
  smartrecruiters: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  workday: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
}

const ADD_HINTS: Record<BoardType, string> = {
  greenhouse: 'token from job-boards.greenhouse.io/<token>',
  lever: 'site from jobs.lever.co/<site> — case-sensitive',
  ashby: 'client from jobs.ashbyhq.com/<client>',
  smartrecruiters: 'slug from jobs.smartrecruiters.com/<slug> — case-sensitive',
}

type FlatRow =
  | { kind: BoardType; idx: number; token: string }
  | { kind: 'workday'; idx: number; entry: WorkdayRow }

const EMPTY_WD: WorkdayRow = { tenant: '', dc: '', site: '', company: '' }

/** One searchable table over every per-company board (all ATS types). */
export function RosterTable({
  draft,
  update,
  runVerify,
  verifyStates,
}: {
  draft: SourcesData
  update: (mut: (d: SourcesData) => void) => void
  runVerify: (key: string, kind: SourceKind, token?: string, entry?: WorkdayRow) => void
  verifyStates: Record<string, VerifyState>
}) {
  const [q, setQ] = useState('')
  const [addKind, setAddKind] = useState<BoardType | 'workday'>('greenhouse')
  const [addToken, setAddToken] = useState('')
  const [addWd, setAddWd] = useState<WorkdayRow>({ ...EMPTY_WD })

  const rows: FlatRow[] = useMemo(() => {
    const out: FlatRow[] = []
    for (const kind of BOARD_TYPES)
      ((draft.ats?.[kind] as string[] | undefined) ?? []).forEach((token, idx) =>
        out.push({ kind, idx, token }),
      )
    ;(draft.ats?.workday ?? []).forEach((entry, idx) =>
      out.push({ kind: 'workday', idx, entry }),
    )
    return out
  }, [draft])

  const needle = q.trim().toLowerCase()
  const visible = needle
    ? rows.filter((r) => {
        const hay =
          r.kind === 'workday'
            ? `workday ${r.entry.tenant} ${r.entry.dc} ${r.entry.site} ${r.entry.company}`
            : `${r.kind} ${r.token}`
        return hay.toLowerCase().includes(needle)
      })
    : rows

  const setToken = (kind: BoardType, idx: number, value: string) =>
    update((d) => {
      const items = [...((d.ats?.[kind] as string[]) ?? [])]
      items[idx] = value
      d.ats = { ...(d.ats ?? {}), [kind]: items }
    })

  const setWdField = (idx: number, f: keyof WorkdayRow, value: string) =>
    update((d) => {
      const items = [...(d.ats?.workday ?? [])]
      items[idx] = { ...items[idx], [f]: value }
      d.ats = { ...(d.ats ?? {}), workday: items }
    })

  const removeRow = (r: FlatRow) =>
    update((d) => {
      if (r.kind === 'workday')
        d.ats = {
          ...(d.ats ?? {}),
          workday: (d.ats?.workday ?? []).filter((_, j) => j !== r.idx),
        }
      else
        d.ats = {
          ...(d.ats ?? {}),
          [r.kind]: ((d.ats?.[r.kind] as string[]) ?? []).filter((_, j) => j !== r.idx),
        }
    })

  const addReady =
    addKind === 'workday'
      ? Boolean(addWd.tenant && addWd.dc && addWd.site && addWd.company)
      : Boolean(addToken.trim())

  const addRow = () => {
    if (!addReady) return
    if (addKind === 'workday') {
      update((d) => {
        d.ats = { ...(d.ats ?? {}), workday: [...(d.ats?.workday ?? []), { ...addWd }] }
      })
      setAddWd({ ...EMPTY_WD })
    } else {
      const v = addToken.trim()
      const kind = addKind
      update((d) => {
        d.ats = {
          ...(d.ats ?? {}),
          [kind]: [...((d.ats?.[kind] as string[]) ?? []), v],
        }
      })
      setAddToken('')
    }
  }

  return (
    <Card title={`Roster — ${rows.length} board${rows.length === 1 ? '' : 's'}`}>
      <p className="mb-3 text-xs text-slate-500">
        Every per-company board in one place. Query-based lanes (Microsoft, Amazon,
        USAJOBS, Adzuna) keep their own cards below. Workday rows are the three
        slugs from{' '}
        <code className="text-slate-400">
          https://&#123;tenant&#125;.&#123;dc&#125;.myworkdayjobs.com/&#123;site&#125;
        </code>
        .
      </p>
      <input
        type="text"
        className={`${inputCls} mb-3`}
        placeholder={`Search ${rows.length} boards by slug, company, or type…`}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="space-y-1.5">
        {visible.map((r) => (
          <div key={`${r.kind}:${r.idx}`}>
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={`w-32 shrink-0 rounded border px-2 py-1 text-center text-[11px] font-medium ${KIND_BADGE[r.kind]}`}
              >
                {r.kind}
              </span>
              {r.kind === 'workday' ? (
                (['tenant', 'dc', 'site', 'company'] as const).map((f) => (
                  <input
                    key={f}
                    type="text"
                    className={`${inputCls} ${f === 'dc' ? 'w-16 shrink-0' : 'min-w-24 flex-1'} font-mono`}
                    placeholder={f}
                    value={r.entry[f] ?? ''}
                    onChange={(e) => setWdField(r.idx, f, e.target.value)}
                  />
                ))
              ) : (
                <input
                  type="text"
                  className={`${inputCls} flex-1 font-mono`}
                  value={r.token}
                  onChange={(e) => setToken(r.kind, r.idx, e.target.value)}
                />
              )}
              <Button
                variant="outline"
                className="shrink-0 px-2.5 py-1.5 text-xs"
                disabled={
                  verifyStates[`${r.kind}:${r.idx}`]?.loading ||
                  (r.kind === 'workday'
                    ? !(r.entry.tenant && r.entry.dc && r.entry.site && r.entry.company)
                    : !r.token.trim())
                }
                onClick={() =>
                  r.kind === 'workday'
                    ? runVerify(`workday:${r.idx}`, 'workday', undefined, r.entry)
                    : runVerify(`${r.kind}:${r.idx}`, r.kind, r.token.trim())
                }
              >
                Verify
              </Button>
              <button
                type="button"
                className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                title="Remove"
                onClick={() => removeRow(r)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <VerifyBadge state={verifyStates[`${r.kind}:${r.idx}`]} />
          </div>
        ))}
        {visible.length === 0 && (
          <p className="py-2 text-xs text-slate-500">No boards match “{q}”.</p>
        )}
      </div>
      <div className="mt-3 border-t border-slate-800 pt-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <select
            className={`${inputCls} w-32 shrink-0`}
            value={addKind}
            onChange={(e) => setAddKind(e.target.value as BoardType | 'workday')}
          >
            {[...BOARD_TYPES, 'workday'].map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {addKind === 'workday' ? (
            (['tenant', 'dc', 'site', 'company'] as const).map((f) => (
              <input
                key={f}
                type="text"
                className={`${inputCls} ${f === 'dc' ? 'w-16 shrink-0' : 'min-w-24 flex-1'} font-mono`}
                placeholder={f}
                value={addWd[f] ?? ''}
                onChange={(e) => setAddWd({ ...addWd, [f]: e.target.value })}
              />
            ))
          ) : (
            <input
              type="text"
              className={`${inputCls} flex-1 font-mono`}
              placeholder={ADD_HINTS[addKind]}
              value={addToken}
              onChange={(e) => setAddToken(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addRow()
                }
              }}
            />
          )}
          <Button
            variant="outline"
            className="shrink-0 px-2.5 py-1.5 text-xs"
            disabled={!addReady}
            onClick={addRow}
          >
            <Plus className="h-3.5 w-3.5" />
            Add
          </Button>
        </div>
      </div>
    </Card>
  )
}
