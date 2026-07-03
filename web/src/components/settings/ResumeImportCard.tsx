import { FileText, Loader2, Sparkles, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useImportResume } from '../../api/hooks'
import type { ProfileData, ResumeImportResult } from '../../api/types'
import { Button } from '../ui/button'
import { Card } from '../ui/card'
import { useToast } from '../ui/toast'

const ACTION_STYLE: Record<string, string> = {
  imported: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  preserved: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
  seeded: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
}

/** Upload a resume, preview the proposed sectional merge, apply it to the form.
 * Nothing is saved here — the user still reviews the form and clicks Save. */
export function ResumeImportCard({
  anthropicAvailable,
  hasProfile,
  onApply,
}: {
  anthropicAvailable: boolean
  hasProfile: boolean
  onApply: (proposed: ProfileData) => void
}) {
  const importResume = useImportResume()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ResumeImportResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const toast = useToast()

  const reset = () => {
    setResult(null)
    setFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const analyze = () => {
    if (!file) return
    importResume.mutate(file, {
      onSuccess: setResult,
      onError: (e) => toast('error', e.message),
    })
  }

  return (
    <Card
      title={hasProfile ? 'Refresh profile from a resume' : 'Bootstrap profile from a resume'}
      className="border-indigo-500/20"
    >
      {!anthropicAvailable ? (
        <p className="text-sm text-slate-400">
          Resume import needs Claude. Set{' '}
          <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs">ANTHROPIC_API_KEY</code>{' '}
          in <code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs">.env</code> and
          restart the dashboard to enable it.
        </p>
      ) : result ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Proposed changes from <span className="font-medium">{file?.name}</span>{' '}
            <span className="text-xs text-slate-500">(extracted by {result.model})</span>
          </p>
          <ul className="space-y-1.5">
            {result.sections.map((s) => (
              <li key={s.section} className="flex items-start gap-2 text-sm">
                <span
                  className={`mt-0.5 w-20 shrink-0 rounded-full px-2 py-0.5 text-center text-xs font-semibold ring-1 ring-inset ${ACTION_STYLE[s.action]}`}
                >
                  {s.action}
                </span>
                <span>
                  <span className="font-medium text-slate-200">{s.section}</span>{' '}
                  <span className="text-slate-400">— {s.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2 pt-1">
            <Button
              onClick={() => {
                onApply(result.proposed)
                reset()
                toast('info', 'Proposal applied to the form — review it, then Save.')
              }}
            >
              <Sparkles className="h-4 w-4" />
              Apply to form
            </Button>
            <Button variant="ghost" onClick={reset}>
              <X className="h-4 w-4" />
              Discard
            </Button>
            <span className="text-xs text-slate-500">
              Nothing is written until you review the form and click Save.
            </span>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-400">
            Upload a <span className="text-slate-300">.docx</span>,{' '}
            <span className="text-slate-300">.txt</span> or{' '}
            <span className="text-slate-300">.md</span> resume (no PDF). Resume-derived
            sections are proposed; compensation, EEO, answer bank and
            work-authorization fields are {hasProfile ? 'kept' : 'seeded from the example'}.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".docx,.txt,.md"
              className="text-sm text-slate-400 file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-200 hover:file:bg-slate-700"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <Button disabled={!file || importResume.isPending} onClick={analyze}>
              {importResume.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileText className="h-4 w-4" />
              )}
              {importResume.isPending ? 'Analyzing…' : 'Analyze resume'}
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
