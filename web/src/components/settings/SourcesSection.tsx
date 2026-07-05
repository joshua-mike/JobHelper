import { Loader2, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import { useConfig, useSaveConfig, useVerifySource } from '../../api/hooks'
import type { SourceKind, SourcesData, WorkdayRow } from '../../api/types'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { Switch } from '../ui/switch'
import { useToast } from '../ui/toast'
import {
  Field,
  inputCls,
  NumberInput,
  SaveBar,
  StringListEditor,
  VerifyBadge,
  type VerifyState,
} from './fields'
import { useDraft } from './useDraft'

const AGGREGATORS: { key: string; label: string; hint: string }[] = [
  { key: 'remotive', label: 'Remotive', hint: 'remotive.com aggregator feed' },
  { key: 'arbeitnow', label: 'Arbeitnow', hint: 'arbeitnow.com job-board API' },
  { key: 'remoteok', label: 'RemoteOK', hint: 'remoteok.com API' },
]

const BOARD_KINDS: {
  kind: SourceKind
  title: string
  hint: string
  placeholder: string
}[] = [
  {
    kind: 'greenhouse',
    title: 'Greenhouse boards',
    hint: 'Board token from job-boards.greenhouse.io/<token>.',
    placeholder: 'e.g. perfectserve',
  },
  {
    kind: 'lever',
    title: 'Lever boards',
    hint: 'Site slug from jobs.lever.co/<site> — CASE-SENSITIVE.',
    placeholder: 'e.g. Mediafly',
  },
  {
    kind: 'ashby',
    title: 'Ashby boards',
    hint: 'Client slug from jobs.ashbyhq.com/<client>.',
    placeholder: 'e.g. delinea',
  },
  {
    kind: 'smartrecruiters',
    title: 'SmartRecruiters companies',
    hint: 'Company slug from jobs.smartrecruiters.com/<slug> — CASE-SENSITIVE.',
    placeholder: 'e.g. Visa',
  },
  {
    kind: 'microsoft',
    title: 'Microsoft careers — search queries',
    hint: 'Items are SEARCH QUERIES, not slugs; top results are pulled per query.',
    placeholder: 'e.g. software engineer',
  },
  {
    kind: 'amazon',
    title: 'Amazon careers — search queries',
    hint: 'Items are SEARCH QUERIES; mostly office-based unless allowed in criteria.',
    placeholder: 'e.g. .net',
  },
  {
    kind: 'usajobs',
    title: 'USAJOBS (federal) — search queries',
    hint: 'Items are SEARCH QUERIES; remote-eligible roles only. Needs USAJOBS_API_KEY + USAJOBS_USER_AGENT in .env — free key at developer.usajobs.gov/apirequest.',
    placeholder: 'e.g. software engineer',
  },
  {
    kind: 'adzuna',
    title: 'Adzuna (aggregator) — search queries',
    hint: 'Items are SEARCH QUERIES; "remote" is required in the ad. Needs ADZUNA_APP_ID + ADZUNA_APP_KEY in .env — free keys at developer.adzuna.com.',
    placeholder: 'e.g. c#',
  },
]

const EMPTY_WD: WorkdayRow = { tenant: '', dc: '', site: '', company: '' }

export function SourcesSection() {
  const query = useConfig<SourcesData>('sources')
  const save = useSaveConfig<SourcesData>('sources')
  const verify = useVerifySource()
  const { draft, update, discard, clear, dirty } = useDraft(query.data?.data)
  const toast = useToast()
  // Verify results keyed by "<kind>:<row-index>" ("workday:2", "remotive:0").
  const [verifyStates, setVerifyStates] = useState<Record<string, VerifyState>>({})

  if (!draft)
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading sources…
      </div>
    )

  const runVerify = (key: string, kind: SourceKind, token?: string, entry?: WorkdayRow) => {
    setVerifyStates((s) => ({ ...s, [key]: { loading: true } }))
    verify.mutate(
      { kind, token, entry },
      {
        onSuccess: (result) =>
          setVerifyStates((s) => ({ ...s, [key]: { loading: false, result } })),
        onError: (e) =>
          setVerifyStates((s) => ({ ...s, [key]: { loading: false, error: e.message } })),
      },
    )
  }

  const kindStates = (kind: string, items: string[]) => {
    const out: Record<number, VerifyState> = {}
    items.forEach((_, i) => {
      const st = verifyStates[`${kind}:${i}`]
      if (st) out[i] = st
    })
    return out
  }

  const onSave = () =>
    save.mutate(draft, {
      onSuccess: (res) => {
        clear()
        setVerifyStates({})
        toast(
          'success',
          !res.changed
            ? 'No effective changes.'
            : res.applies_next_run
              ? 'Sources saved — applies from the next run.'
              : 'Sources saved.',
        )
      },
      onError: (e) => {
        if (!(e instanceof ApiError && e.details)) toast('error', e.message)
      },
    })

  const errors =
    save.error instanceof ApiError && save.error.details ? save.error.details : []
  const workday = draft.ats?.workday ?? []

  return (
    <div className="space-y-4">
      <Card title="Aggregators">
        <p className="mb-3 text-xs text-slate-500">
          Keyless remote job-board feeds — broad coverage, no per-company curation.
        </p>
        <div className="space-y-2">
          {AGGREGATORS.map(({ key, label, hint }) => (
            <div key={key} className="flex flex-wrap items-center gap-3">
              <div className="w-44">
                <Switch
                  checked={draft.aggregators?.[key] ?? false}
                  onChange={(v) =>
                    update((d) => {
                      d.aggregators = { ...(d.aggregators ?? {}), [key]: v }
                    })
                  }
                  label={label}
                />
              </div>
              <span className="text-xs text-slate-600">{hint}</span>
              <Button
                variant="outline"
                className="px-2.5 py-1 text-xs"
                disabled={verifyStates[`${key}:0`]?.loading}
                onClick={() => runVerify(`${key}:0`, key as SourceKind)}
              >
                Verify
              </Button>
              <VerifyBadge state={verifyStates[`${key}:0`]} />
            </div>
          ))}
        </div>
      </Card>

      {BOARD_KINDS.map(({ kind, title, hint, placeholder }) => (
        <Card key={kind} title={title}>
          <p className="mb-3 text-xs text-slate-500">{hint}</p>
          <StringListEditor
            mono
            items={(draft.ats?.[kind] as string[] | undefined) ?? []}
            placeholder={placeholder}
            onChange={(items) =>
              update((d) => {
                d.ats = { ...(d.ats ?? {}), [kind]: items }
              })
            }
            onVerify={(value, i) => runVerify(`${kind}:${i}`, kind, value)}
            verifyStates={kindStates(kind, (draft.ats?.[kind] as string[]) ?? [])}
          />
        </Card>
      ))}

      <Card title="Workday tenants">
        <p className="mb-3 text-xs text-slate-500">
          Three slugs from the careers URL{' '}
          <code className="text-slate-400">
            https://&#123;tenant&#125;.&#123;dc&#125;.myworkdayjobs.com/&#123;site&#125;
          </code>
          ; the crawl is scoped by the search terms below.
        </p>
        <div className="space-y-2">
          {workday.map((row, i) => (
            <div key={i}>
              <div className="flex flex-wrap items-center gap-1.5">
                {(['tenant', 'dc', 'site', 'company'] as const).map((f) => (
                  <input
                    key={f}
                    type="text"
                    className={`${inputCls} ${f === 'dc' ? 'w-16 shrink-0' : 'min-w-28 flex-1'} font-mono`}
                    placeholder={f}
                    value={row[f] ?? ''}
                    onChange={(e) =>
                      update((d) => {
                        const rows = [...(d.ats?.workday ?? [])]
                        rows[i] = { ...rows[i], [f]: e.target.value }
                        d.ats = { ...(d.ats ?? {}), workday: rows }
                      })
                    }
                  />
                ))}
                <Button
                  variant="outline"
                  className="shrink-0 px-2.5 py-1.5 text-xs"
                  disabled={
                    verifyStates[`workday:${i}`]?.loading ||
                    !(row.tenant && row.dc && row.site && row.company)
                  }
                  onClick={() => runVerify(`workday:${i}`, 'workday', undefined, row)}
                >
                  Verify
                </Button>
                <button
                  type="button"
                  className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                  title="Remove"
                  onClick={() =>
                    update((d) => {
                      d.ats = {
                        ...(d.ats ?? {}),
                        workday: (d.ats?.workday ?? []).filter((_, j) => j !== i),
                      }
                    })
                  }
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <VerifyBadge state={verifyStates[`workday:${i}`]} />
            </div>
          ))}
          <Button
            variant="outline"
            className="px-2.5 py-1.5 text-xs"
            onClick={() =>
              update((d) => {
                d.ats = {
                  ...(d.ats ?? {}),
                  workday: [...(d.ats?.workday ?? []), { ...EMPTY_WD }],
                }
              })
            }
          >
            <Plus className="h-3.5 w-3.5" />
            Add tenant
          </Button>
        </div>
      </Card>

      <Card title="Crawl limits & politeness">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Request delay (seconds)" hint="Wait between requests to the same host.">
            <NumberInput
              value={draft.request_delay_seconds}
              min={0}
              max={60}
              step={0.1}
              onChange={(v) =>
                update((d) => void (d.request_delay_seconds = v ?? undefined))
              }
            />
          </Field>
          <Field label="Per-source cap" hint="Hard cap on jobs ingested per source per run.">
            <NumberInput
              value={draft.per_source_cap}
              min={1}
              max={10000}
              onChange={(v) => update((d) => void (d.per_source_cap = v ?? undefined))}
            />
          </Field>
          <Field label="Microsoft: results per query">
            <NumberInput
              value={draft.microsoft_per_query}
              min={1}
              max={500}
              onChange={(v) =>
                update((d) => void (d.microsoft_per_query = v ?? undefined))
              }
            />
          </Field>
          <Field label="Amazon: results per query">
            <NumberInput
              value={draft.amazon_per_query}
              min={1}
              max={500}
              onChange={(v) => update((d) => void (d.amazon_per_query = v ?? undefined))}
            />
          </Field>
          <Field label="USAJOBS: results per query">
            <NumberInput
              value={draft.usajobs_per_query}
              min={1}
              max={500}
              onChange={(v) =>
                update((d) => void (d.usajobs_per_query = v ?? undefined))
              }
            />
          </Field>
          <Field label="Adzuna: results per query">
            <NumberInput
              value={draft.adzuna_per_query}
              min={1}
              max={50}
              onChange={(v) =>
                update((d) => void (d.adzuna_per_query = v ?? undefined))
              }
            />
          </Field>
          <Field label="Workday: results per search term">
            <NumberInput
              value={draft.workday_per_search}
              min={1}
              max={500}
              onChange={(v) =>
                update((d) => void (d.workday_per_search = v ?? undefined))
              }
            />
          </Field>
          <Field
            label="Workday search terms"
            hint="Applied to EVERY tenant to scope the crawl."
            className="sm:col-span-2 lg:col-span-3"
          >
            <StringListEditor
              items={draft.workday_searches ?? []}
              placeholder="e.g. software engineer"
              onChange={(items) => update((d) => void (d.workday_searches = items))}
            />
          </Field>
        </div>
      </Card>

      <SaveBar
        dirty={dirty}
        saving={save.isPending}
        errors={errors}
        onSave={onSave}
        onDiscard={() => {
          discard()
          setVerifyStates({})
        }}
      />
    </div>
  )
}
