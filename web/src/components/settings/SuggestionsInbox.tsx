import { Check, Loader2, RefreshCw, X } from 'lucide-react'
import {
  useScanSuggestions,
  useSuggestionAction,
  useSuggestions,
} from '../../api/hooks'
import type { SourceSuggestion } from '../../api/types'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { useToast } from '../ui/toast'

const VIA_BADGE: Record<string, { cls: string; label: string; title?: string }> = {
  url: {
    cls: 'border-slate-500/30 bg-slate-500/10 text-slate-300',
    label: 'from job url',
  },
  redirect: {
    cls: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
    label: 'via redirect',
  },
  guess: {
    cls: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    label: 'slug guess — confirm company',
    title:
      'This token was guessed from the company name; a different company could own ' +
      'the board. Check the sample titles before accepting.',
  },
}

/** Harvester output (ITEM-5): live-verified board candidates, accept/dismiss. */
export function SuggestionsInbox({
  rosterDirty,
  onAccepted,
}: {
  rosterDirty: boolean
  onAccepted: () => void
}) {
  const query = useSuggestions()
  const scan = useScanSuggestions()
  const act = useSuggestionAction()
  const toast = useToast()
  const items = query.data ?? []

  const onScan = () =>
    scan.mutate(undefined, {
      onSuccess: (r) =>
        toast(
          'success',
          r.new
            ? `${r.new} new suggestion${r.new === 1 ? '' : 's'} found.`
            : 'Scan complete — nothing new this time.',
        ),
      onError: (e) => toast('error', e.message),
    })

  const onAct = (s: SourceSuggestion, action: 'accept' | 'dismiss') =>
    act.mutate(
      { id: s.id, action },
      {
        onSuccess: () => {
          if (action === 'accept') {
            toast('success', `${s.kind}/${s.token} added to the roster.`)
            onAccepted()
          }
        },
        onError: (e) => toast('error', e.message),
      },
    )

  return (
    <Card title="Suggested sources">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-xl text-xs text-slate-500">
          Harvested from aggregator jobs that keep clearing your criteria; every
          candidate is live-verified before it appears here. Accepting merges the
          board into sources.yaml directly — no Save needed.
        </p>
        <Button
          variant="outline"
          className="shrink-0 px-2.5 py-1.5 text-xs"
          disabled={scan.isPending}
          onClick={onScan}
        >
          {scan.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          {scan.isPending ? 'Scanning… (~30s)' : 'Scan now'}
        </Button>
      </div>
      {query.isLoading ? (
        <div className="flex items-center gap-2 py-4 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      ) : items.length === 0 ? (
        <p className="py-2 text-xs text-slate-500">
          No suggestions yet. They accumulate as daily runs feed aggregator jobs
          through your filters — try a scan after a few runs.
        </p>
      ) : (
        <div className="space-y-2">
          {items.map((s) => {
            const via = VIA_BADGE[s.via] ?? VIA_BADGE.url
            return (
              <div
                key={s.id}
                className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <code className="text-xs text-slate-200">
                    {s.kind}/{s.token}
                  </code>
                  {s.company && (
                    <span className="text-xs text-slate-400">{s.company}</span>
                  )}
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] ${via.cls}`}
                    title={via.title}
                  >
                    {via.label}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {s.evidence_count} matching job
                    {s.evidence_count === 1 ? '' : 's'}
                    {s.best_score ? ` · best score ${s.best_score}` : ''}
                    {s.live_count ? ` · ${s.live_count}+ live` : ''}
                  </span>
                  <span className="ml-auto flex items-center gap-1.5">
                    <Button
                      className="px-2.5 py-1 text-xs"
                      disabled={act.isPending || rosterDirty}
                      onClick={() => onAct(s, 'accept')}
                    >
                      <Check className="h-3.5 w-3.5" />
                      Accept
                    </Button>
                    <Button
                      variant="ghost"
                      className="px-2.5 py-1 text-xs"
                      disabled={act.isPending}
                      onClick={() => onAct(s, 'dismiss')}
                    >
                      <X className="h-3.5 w-3.5" />
                      Dismiss
                    </Button>
                  </span>
                </div>
                {s.sample.length > 0 && (
                  <p className="mt-1 truncate text-[11px] text-slate-500">
                    e.g. {s.sample.join(' · ')}
                  </p>
                )}
              </div>
            )
          })}
          {rosterDirty && (
            <p className="text-[11px] text-amber-400/80">
              Accept is disabled while the roster has unsaved edits — save or
              discard them first.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}
