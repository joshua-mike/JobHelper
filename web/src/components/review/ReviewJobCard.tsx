import { Check, Copy, Download, ExternalLink, Globe, Star } from 'lucide-react'
import { useState } from 'react'
import { api } from '../../api/client'
import type { ReviewAction, ReviewJob } from '../../api/types'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { ScorePill } from '../ui/score-pill'
import { useToast } from '../ui/toast'

function prettyKey(key: string): string {
  const s = key.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function CoverLetter({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-300">
        Cover letter draft
      </summary>
      <div className="mt-2">
        <Button variant="outline" className="px-2.5 py-1 text-xs" onClick={copy}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy cover letter'}
        </Button>
        <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-slate-800 bg-black/40 p-3 font-sans text-xs leading-relaxed text-slate-300">
          {text}
        </pre>
      </div>
    </details>
  )
}

function WorkdaySkills({ skills }: { skills: string[] }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard.writeText(skills.join(', ')).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-300">
        Workday skills list ({skills.length})
      </summary>
      <div className="mt-2">
        <p className="text-xs leading-relaxed text-slate-500">
          Workday scores what you literally enter in its structured skills
          fields — it won&apos;t infer unstated skills from the résumé. Add
          these (your real skills, JD-required first) to the application&apos;s
          skills section.
        </p>
        <Button variant="outline" className="mt-2 px-2.5 py-1 text-xs" onClick={copy}>
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy skills list'}
        </Button>
        <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-slate-800 bg-black/40 p-3 font-sans text-xs leading-relaxed text-slate-300">
          {skills.join(', ')}
        </pre>
      </div>
    </details>
  )
}

export function ReviewJobCard({
  job,
  onAction,
  busy,
}: {
  job: ReviewJob
  onAction: (id: number, action: ReviewAction) => void
  busy: boolean
}) {
  const toast = useToast()
  const screening = Object.entries(job.screening)

  const onAssist = () => {
    api.assistApply(job.id).then(
      () => toast('info', 'Assisted apply launched — check the new console window.'),
      (e: Error) => toast('error', e.message),
    )
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-slate-100">
            {job.title ?? 'Untitled role'}
            <span className="text-slate-400"> — {job.company ?? 'Unknown company'}</span>
          </h3>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {job.location ?? job.candidate_location ?? 'Location n/a'} · {job.source}
            {job.status === 'approved' && <Badge tone="yellow">approved</Badge>}
          </p>
        </div>
        <ScorePill score={job.display_score} />
      </div>

      {job.llm_rationale && (
        <p className="mt-3 text-sm leading-relaxed text-slate-300">{job.llm_rationale}</p>
      )}

      {(job.musthaves_met.length > 0 || job.missing.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {job.musthaves_met.map((m) => (
            <Badge key={`met-${m}`} tone="green">
              ✓ {m}
            </Badge>
          ))}
          {job.missing.map((m) => (
            <Badge key={`gap-${m}`} tone="yellow">
              ⚠ {m}
            </Badge>
          ))}
        </div>
      )}

      {job.ats_report &&
        (job.ats_report.coverage || job.ats_report.error || job.ats_report.variant) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {job.ats_report.variant?.name && (
            <Badge tone="slate">
              variant: {job.ats_report.variant.name}
              {job.ats_report.variant.signals?.length
                ? ` (${job.ats_report.variant.signals.slice(0, 3).join(', ')})`
                : ''}
            </Badge>
          )}
          {job.ats_report.coverage && (
            <Badge
              tone={
                job.ats_report.coverage.required_present >=
                job.ats_report.coverage.required_total
                  ? 'green'
                  : 'yellow'
              }
            >
              ATS {job.ats_report.coverage.required_present}/
              {job.ats_report.coverage.required_total} required
            </Badge>
          )}
          {(job.ats_report.coverage?.missing ?? []).map((m) => (
            <Badge key={`ats-miss-${m}`} tone="yellow">
              missing: {m}
            </Badge>
          ))}
          {(job.ats_report.warnings ?? []).map((w) => (
            <Badge key={`ats-warn-${w}`} tone="red">
              ⚠ {w}
            </Badge>
          ))}
          {job.ats_report.error && (
            <Badge tone="slate">no ATS report: {job.ats_report.error}</Badge>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300"
          >
            Open posting <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
        {job.has_resume && (
          <a
            href={api.resumeUrl(job.id)}
            className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300"
          >
            Tailored résumé <Download className="h-3.5 w-3.5" />
          </a>
        )}
      </div>

      {screening.length > 0 && (
        <p className="mt-3 text-xs text-slate-400">
          {screening.map(([k, v], i) => (
            <span key={k}>
              {i > 0 && ' · '}
              <span className="font-semibold text-slate-300">{prettyKey(k)}:</span>{' '}
              {String(v)}
            </span>
          ))}
        </p>
      )}

      {job.notes.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-300">
            What was tailored ({job.notes.length})
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-400">
            {job.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </details>
      )}

      {job.cover_letter_text && <CoverLetter text={job.cover_letter_text} />}

      {job.ats === 'workday' && (job.workday_skills?.length ?? 0) > 0 && (
        <WorkdaySkills skills={job.workday_skills as string[]} />
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {job.can_assist && (
          <Button
            variant="violet"
            disabled={busy}
            onClick={onAssist}
            title={`Open this ${job.ats} form in a browser and auto-fill it. You review & submit.`}
          >
            <Globe className="h-4 w-4" /> Assisted apply
          </Button>
        )}
        <Button variant="success" disabled={busy} onClick={() => onAction(job.id, 'applied')}>
          <Check className="h-4 w-4" /> Mark applied
        </Button>
        {job.status !== 'approved' && (
          <Button variant="primary" disabled={busy} onClick={() => onAction(job.id, 'approve')}>
            <Star className="h-4 w-4" /> Approve
          </Button>
        )}
        <Button variant="outline" disabled={busy} onClick={() => onAction(job.id, 'skip')}>
          Skip
        </Button>
      </div>
    </section>
  )
}
