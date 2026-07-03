import { Loader2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { useConfig, useSaveConfig } from '../../api/hooks'
import type { CriteriaData } from '../../api/types'
import { Card } from '../ui/card'
import { Switch } from '../ui/switch'
import { useToast } from '../ui/toast'
import {
  Field,
  NumberInput,
  SaveBar,
  SelectInput,
  StringListEditor,
  TextInput,
} from './fields'
import { useDraft } from './useDraft'

export function CriteriaSection() {
  const query = useConfig<CriteriaData>('criteria')
  const save = useSaveConfig<CriteriaData>('criteria')
  const { draft, update, discard, clear, dirty } = useDraft(query.data?.data)
  const toast = useToast()

  if (!draft)
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading criteria…
      </div>
    )

  const onSave = () =>
    save.mutate(draft, {
      onSuccess: (res) => {
        clear()
        toast(
          'success',
          !res.changed
            ? 'No effective changes.'
            : res.applies_next_run
              ? 'Criteria saved — applies from the next run.'
              : 'Criteria saved.',
        )
      },
      onError: (e) => {
        if (!(e instanceof ApiError && e.details)) toast('error', e.message)
      },
    })

  const errors =
    save.error instanceof ApiError && save.error.details ? save.error.details : []

  const listCard = (
    title: string,
    hint: string,
    key: 'title_include_any' | 'title_exclude_any' | 'keywords_any' | 'keywords_exclude' | 'onsite_ok_companies' | 'allowed_location_tokens' | 'exclude_companies',
    placeholder: string,
  ) => (
    <Field label={title} hint={hint}>
      <StringListEditor
        items={draft[key] ?? []}
        placeholder={placeholder}
        onChange={(items) => update((d) => void (d[key] = items))}
      />
    </Field>
  )

  return (
    <div className="space-y-4">
      <Card title="Daily digest">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label="Daily target"
            hint="Ceiling, not a quota — roles still need to clear the score bar."
          >
            <NumberInput
              value={draft.daily_target}
              min={1}
              max={100}
              onChange={(v) => update((d) => void (d.daily_target = v ?? undefined))}
            />
          </Field>
          <Field label="Max per company" hint="Spread proposals across employers.">
            <NumberInput
              value={draft.max_per_company}
              min={1}
              max={100}
              onChange={(v) => update((d) => void (d.max_per_company = v ?? undefined))}
            />
          </Field>
          <Field label="Min score (0–100)" hint="Quality bar to make the digest.">
            <NumberInput
              value={draft.min_score}
              min={0}
              max={100}
              onChange={(v) => update((d) => void (d.min_score = v ?? undefined))}
            />
          </Field>
        </div>
      </Card>

      <Card title="Scoring & models">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Recall scoring"
            hint="auto = semantic when installed, else lexical."
          >
            <SelectInput
              value={draft.scoring}
              options={[
                { value: 'auto', label: 'auto' },
                { value: 'semantic', label: 'semantic' },
                { value: 'lexical', label: 'lexical' },
              ]}
              onChange={(v) =>
                update((d) => void (d.scoring = v as CriteriaData['scoring']))
              }
            />
          </Field>
          <Field
            label="LLM shortlist"
            hint="Top N (by recall score) sent to the Claude judge."
          >
            <NumberInput
              value={draft.llm_shortlist}
              min={1}
              max={200}
              onChange={(v) => update((d) => void (d.llm_shortlist = v ?? undefined))}
            />
          </Field>
          <Field label="Judge model" hint="Scores the shortlist.">
            <TextInput
              value={draft.judge_model}
              onChange={(v) => update((d) => void (d.judge_model = v))}
            />
          </Field>
          <Field label="Tailor model" hint="Resume/cover tailoring + resume import.">
            <TextInput
              value={draft.tailor_model}
              onChange={(v) => update((d) => void (d.tailor_model = v))}
            />
          </Field>
        </div>
      </Card>

      <Card title="Role targeting">
        <div className="grid gap-5 lg:grid-cols-2">
          {listCard(
            'Title must contain one of',
            'Case-insensitive substring; empty list disables title gating.',
            'title_include_any',
            'e.g. backend',
          )}
          {listCard(
            'Reject titles containing',
            'Roles you never want (staff/principal are intentionally not here).',
            'title_exclude_any',
            'e.g. recruiter',
          )}
          {listCard(
            'Keywords (title or description)',
            'At least one must appear somewhere; empty disables.',
            'keywords_any',
            'e.g. c#',
          )}
          {listCard(
            'Dealbreaker keywords',
            'Reject when these appear in the description.',
            'keywords_exclude',
            'e.g. onsite only',
          )}
        </div>
      </Card>

      <Card title="Remote & location">
        <div className="space-y-5">
          <Switch
            checked={draft.remote_required ?? false}
            onChange={(v) => update((d) => void (d.remote_required = v))}
            label="Remote required (drop onsite/hybrid roles)"
          />
          <div className="grid gap-5 lg:grid-cols-2">
            {listCard(
              'Onsite OK for these companies',
              'Exact company name as shown in the digest (US locations only).',
              'onsite_ok_companies',
              'e.g. Microsoft',
            )}
            {listCard(
              'Allowed location restrictions',
              'Keep location-restricted postings matching one of these tokens.',
              'allowed_location_tokens',
              'e.g. United States',
            )}
          </div>
        </div>
      </Card>

      <Card title="Compensation, freshness & exclusions">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Salary floor (USD)"
            hint="Reject listed salaries below this; 0 disables. Unlisted salaries are kept."
          >
            <NumberInput
              value={draft.salary_floor}
              min={0}
              step={5000}
              onChange={(v) => update((d) => void (d.salary_floor = v ?? undefined))}
            />
          </Field>
          <Field label="Max posting age (days)" hint="Ignore older postings.">
            <NumberInput
              value={draft.max_age_days}
              min={1}
              max={365}
              onChange={(v) => update((d) => void (d.max_age_days = v ?? undefined))}
            />
          </Field>
          <div className="sm:col-span-2">
            {listCard(
              'Excluded companies',
              'Never surface roles from these employers.',
              'exclude_companies',
              'e.g. Example Bad Corp',
            )}
          </div>
        </div>
      </Card>

      <SaveBar
        dirty={dirty}
        saving={save.isPending}
        errors={errors}
        onSave={onSave}
        onDiscard={discard}
      />
    </div>
  )
}
