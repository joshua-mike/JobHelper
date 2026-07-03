import { ArrowDown, ArrowUp, Loader2, Plus, Trash2 } from 'lucide-react'
import { ApiError } from '../../api/client'
import { useConfig, useSaveConfig } from '../../api/hooks'
import type {
  AchievementData,
  ProfileData,
  SettingsStatus,
  WorkEntryData,
} from '../../api/types'
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
  TextArea,
  TextInput,
} from './fields'
import { ResumeImportCard } from './ResumeImportCard'
import { useDraft } from './useDraft'

const EEO_FIELDS: { key: string; label: string }[] = [
  { key: 'race_ethnicity', label: 'Race / ethnicity' },
  { key: 'gender', label: 'Gender' },
  { key: 'veteran_status', label: 'Veteran status' },
  { key: 'disability_status', label: 'Disability status' },
]

/** Comma-separated list committed on blur (typing commas stays smooth). */
function SkillsUsedInput({
  value,
  onCommit,
}: {
  value: string[]
  onCommit: (skills: string[]) => void
}) {
  return (
    <input
      type="text"
      className={inputCls}
      defaultValue={value.join(', ')}
      placeholder="skills used (comma-separated)"
      onBlur={(e) =>
        onCommit(
          e.target.value
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
        )
      }
    />
  )
}

export function ProfileSection({ status }: { status?: SettingsStatus }) {
  const query = useConfig<ProfileData>('profile')
  const save = useSaveConfig<ProfileData>('profile')
  const { draft, update, replace, discard, clear, dirty } = useDraft(query.data?.data)
  const toast = useToast()

  if (!draft)
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading profile…
      </div>
    )

  const exists = query.data?.exists ?? true
  const ident = draft.identity ?? {}
  const comp = draft.compensation ?? {}
  const skills = draft.skills ?? {}

  const onSave = () =>
    save.mutate(draft, {
      onSuccess: (res) => {
        clear()
        toast(
          'success',
          !res.changed
            ? 'No effective changes.'
            : !exists
              ? 'profile.yaml created.'
              : res.applies_next_run
                ? 'Profile saved — applies from the next run.'
                : 'Profile saved.',
        )
      },
      onError: (e) => {
        if (!(e instanceof ApiError && e.details)) toast('error', e.message)
      },
    })

  const errors =
    save.error instanceof ApiError && save.error.details ? save.error.details : []

  const setIdent = (key: string, v: unknown) =>
    update((d) => void (d.identity = { ...(d.identity ?? {}), [key]: v }))
  const setComp = (key: string, v: unknown) =>
    update((d) => void (d.compensation = { ...(d.compensation ?? {}), [key]: v }))
  const setWork = (mutate: (list: WorkEntryData[]) => void) =>
    update((d) => {
      const list = [...(d.work_history ?? [])]
      mutate(list)
      d.work_history = list
    })

  return (
    <div className="space-y-4">
      {!exists && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          No <code className="text-amber-100">config/profile.yaml</code> yet — this form
          is prefilled from the example. Import your resume below or edit the fields,
          then <span className="font-semibold">Save</span> to create it. The file stays
          local (gitignored).
        </div>
      )}

      <ResumeImportCard
        anthropicAvailable={status?.anthropic_available ?? false}
        hasProfile={exists}
        onApply={replace}
      />

      <Card title="Identity & contact">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Full name">
            <TextInput value={ident.full_name} onChange={(v) => setIdent('full_name', v)} />
          </Field>
          <Field label="Email">
            <TextInput value={ident.email} onChange={(v) => setIdent('email', v)} />
          </Field>
          <Field label="Phone">
            <TextInput value={ident.phone} onChange={(v) => setIdent('phone', v)} />
          </Field>
          <Field label="City / state">
            <TextInput value={ident.city_state} onChange={(v) => setIdent('city_state', v)} />
          </Field>
          <Field label="LinkedIn URL">
            <TextInput value={ident.linkedin_url} onChange={(v) => setIdent('linkedin_url', v)} />
          </Field>
          <Field label="Portfolio URL">
            <TextInput value={ident.portfolio_url} onChange={(v) => setIdent('portfolio_url', v)} />
          </Field>
        </div>
      </Card>

      <Card title="Work authorization & availability">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Work authorization" className="sm:col-span-2">
            <TextInput
              value={ident.work_authorization_status}
              onChange={(v) => setIdent('work_authorization_status', v)}
            />
          </Field>
          <Field label="Earliest start date">
            <TextInput
              value={ident.earliest_start_date}
              onChange={(v) => setIdent('earliest_start_date', v)}
            />
          </Field>
          <Field label="Notice period">
            <TextInput
              value={ident.notice_period}
              onChange={(v) => setIdent('notice_period', v)}
            />
          </Field>
          <Switch
            checked={ident.requires_sponsorship ?? false}
            onChange={(v) => setIdent('requires_sponsorship', v)}
            label="Requires visa sponsorship"
          />
          <Switch
            checked={ident.willing_to_relocate ?? false}
            onChange={(v) => setIdent('willing_to_relocate', v)}
            label="Willing to relocate"
          />
        </div>
      </Card>

      <Card title="Compensation">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Desired salary min">
            <NumberInput
              value={comp.desired_salary_min}
              min={0}
              step={5000}
              onChange={(v) => setComp('desired_salary_min', v)}
            />
          </Field>
          <Field label="Desired salary max">
            <NumberInput
              value={comp.desired_salary_max}
              min={0}
              step={5000}
              onChange={(v) => setComp('desired_salary_max', v)}
            />
          </Field>
          <Field label="Currency">
            <TextInput value={comp.currency} onChange={(v) => setComp('currency', v)} />
          </Field>
          <div className="flex items-end pb-2">
            <Switch
              checked={comp.salary_negotiable ?? false}
              onChange={(v) => setComp('salary_negotiable', v)}
              label="Negotiable"
            />
          </div>
        </div>
      </Card>

      <Card title="Professional summary">
        <Field
          label="Summary"
          hint="One short, factual paragraph — the tailor may reword it per job."
        >
          <TextArea
            value={draft.summary}
            rows={4}
            onChange={(v) => update((d) => void (d.summary = v))}
          />
        </Field>
      </Card>

      <Card
        title="Work history"
        action={
          <Button
            variant="outline"
            className="px-2.5 py-1.5 text-xs"
            onClick={() =>
              setWork((list) =>
                list.unshift({ company: '', title: '', achievements: [] }),
              )
            }
          >
            <Plus className="h-3.5 w-3.5" />
            Add position
          </Button>
        }
      >
        <p className="mb-3 text-xs text-slate-500">
          Reverse-chronological. Achievements are the raw material the tailor selects
          from — action verb + what you did + quantified result. The tailor only ever
          selects/rewords facts from here; it never invents.
        </p>
        <div className="space-y-4">
          {(draft.work_history ?? []).map((job, i) => (
            <div key={i} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-slate-300">
                  {job.title || 'Untitled'} @ {job.company || '?'}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="rounded p-1 text-slate-500 hover:bg-slate-800 disabled:opacity-30"
                    disabled={i === 0}
                    title="Move up"
                    onClick={() =>
                      setWork((l) => l.splice(i - 1, 0, ...l.splice(i, 1)))
                    }
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="rounded p-1 text-slate-500 hover:bg-slate-800 disabled:opacity-30"
                    disabled={i === (draft.work_history?.length ?? 0) - 1}
                    title="Move down"
                    onClick={() =>
                      setWork((l) => l.splice(i + 1, 0, ...l.splice(i, 1)))
                    }
                  >
                    <ArrowDown className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                    title="Remove position"
                    onClick={() => setWork((l) => void l.splice(i, 1))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Company">
                  <TextInput
                    value={job.company}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], company: v }))}
                  />
                </Field>
                <Field label="Title">
                  <TextInput
                    value={job.title}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], title: v }))}
                  />
                </Field>
                <Field label="Location">
                  <TextInput
                    value={job.location}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], location: v }))}
                  />
                </Field>
                <Field label="Start (YYYY-MM)">
                  <TextInput
                    value={job.start_date}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], start_date: v }))}
                  />
                </Field>
                <Field label="End (YYYY-MM or Present)">
                  <TextInput
                    value={job.end_date}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], end_date: v }))}
                  />
                </Field>
                <Field label="Employment type">
                  <TextInput
                    value={job.employment_type}
                    onChange={(v) =>
                      setWork((l) => void (l[i] = { ...l[i], employment_type: v }))
                    }
                  />
                </Field>
                <Field label="Role summary" className="sm:col-span-2 lg:col-span-3">
                  <TextInput
                    value={job.summary}
                    onChange={(v) => setWork((l) => void (l[i] = { ...l[i], summary: v }))}
                  />
                </Field>
              </div>
              <div className="mt-3 space-y-2">
                <span className="text-xs font-medium text-slate-400">Achievements</span>
                {(job.achievements ?? []).map((ach, j) => (
                  <div key={j} className="rounded-lg border border-slate-800/70 p-3">
                    <TextArea
                      value={ach.text}
                      rows={2}
                      onChange={(v) =>
                        setWork((l) => {
                          const achs = [...(l[i].achievements ?? [])]
                          achs[j] = { ...achs[j], text: v }
                          l[i] = { ...l[i], achievements: achs }
                        })
                      }
                    />
                    <div className="mt-2 flex flex-wrap items-center gap-3">
                      <div className="min-w-48 flex-1">
                        <SkillsUsedInput
                          value={ach.skills_used ?? []}
                          onCommit={(sk) =>
                            setWork((l) => {
                              const achs = [...(l[i].achievements ?? [])]
                              achs[j] = { ...achs[j], skills_used: sk }
                              l[i] = { ...l[i], achievements: achs }
                            })
                          }
                        />
                      </div>
                      <Switch
                        checked={ach.verified ?? false}
                        onChange={(v) =>
                          setWork((l) => {
                            const achs = [...(l[i].achievements ?? [])]
                            achs[j] = { ...achs[j], verified: v }
                            l[i] = { ...l[i], achievements: achs }
                          })
                        }
                        label="Metric verified"
                      />
                      <button
                        type="button"
                        className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                        title="Remove achievement"
                        onClick={() =>
                          setWork((l) => {
                            const achs = (l[i].achievements ?? []).filter(
                              (_: AchievementData, k: number) => k !== j,
                            )
                            l[i] = { ...l[i], achievements: achs }
                          })
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))}
                <Button
                  variant="ghost"
                  className="px-2 py-1 text-xs"
                  onClick={() =>
                    setWork((l) => {
                      l[i] = {
                        ...l[i],
                        achievements: [
                          ...(l[i].achievements ?? []),
                          { text: '', skills_used: [], verified: false },
                        ],
                      }
                    })
                  }
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add achievement
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card
        title="Education"
        action={
          <Button
            variant="outline"
            className="px-2.5 py-1.5 text-xs"
            onClick={() =>
              update((d) => void (d.education = [...(d.education ?? []), { institution: '' }]))
            }
          >
            <Plus className="h-3.5 w-3.5" />
            Add entry
          </Button>
        }
      >
        <div className="space-y-2">
          {(draft.education ?? []).map((ed, i) => (
            <div key={i} className="flex flex-wrap items-center gap-1.5">
              {(
                [
                  ['institution', 'institution'],
                  ['degree', 'degree'],
                  ['field', 'field'],
                  ['grad_date', 'YYYY-MM'],
                ] as const
              ).map(([f, ph]) => (
                <input
                  key={f}
                  type="text"
                  className={`${inputCls} min-w-28 flex-1`}
                  placeholder={ph}
                  value={(ed[f] as string) ?? ''}
                  onChange={(e) =>
                    update((d) => {
                      const list = [...(d.education ?? [])]
                      list[i] = { ...list[i], [f]: e.target.value }
                      d.education = list
                    })
                  }
                />
              ))}
              <button
                type="button"
                className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                title="Remove"
                onClick={() =>
                  update(
                    (d) => void (d.education = (d.education ?? []).filter((_, j) => j !== i)),
                  )
                }
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Skills">
        <div className="space-y-5">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">
                Hard skills (name · years · proficiency)
              </span>
              <Button
                variant="outline"
                className="px-2.5 py-1 text-xs"
                onClick={() =>
                  update((d) => {
                    d.skills = {
                      ...(d.skills ?? {}),
                      hard_skills: [...(d.skills?.hard_skills ?? []), { name: '' }],
                    }
                  })
                }
              >
                <Plus className="h-3.5 w-3.5" />
                Add skill
              </Button>
            </div>
            <div className="grid gap-1.5 lg:grid-cols-2">
              {(skills.hard_skills ?? []).map((sk, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <input
                    type="text"
                    className={`${inputCls} flex-1`}
                    placeholder="name"
                    value={sk.name ?? ''}
                    onChange={(e) =>
                      update((d) => {
                        const list = [...(d.skills?.hard_skills ?? [])]
                        list[i] = { ...list[i], name: e.target.value }
                        d.skills = { ...(d.skills ?? {}), hard_skills: list }
                      })
                    }
                  />
                  <input
                    type="number"
                    className={`${inputCls} w-16 shrink-0`}
                    placeholder="yrs"
                    min={0}
                    value={sk.years ?? ''}
                    onChange={(e) =>
                      update((d) => {
                        const list = [...(d.skills?.hard_skills ?? [])]
                        list[i] = {
                          ...list[i],
                          years: e.target.value === '' ? null : Number(e.target.value),
                        }
                        d.skills = { ...(d.skills ?? {}), hard_skills: list }
                      })
                    }
                  />
                  <input
                    type="text"
                    className={`${inputCls} w-32 shrink-0`}
                    placeholder="proficiency"
                    value={sk.proficiency ?? ''}
                    onChange={(e) =>
                      update((d) => {
                        const list = [...(d.skills?.hard_skills ?? [])]
                        list[i] = { ...list[i], proficiency: e.target.value }
                        d.skills = { ...(d.skills ?? {}), hard_skills: list }
                      })
                    }
                  />
                  <button
                    type="button"
                    className="shrink-0 rounded-lg p-1 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                    title="Remove"
                    onClick={() =>
                      update((d) => {
                        d.skills = {
                          ...(d.skills ?? {}),
                          hard_skills: (d.skills?.hard_skills ?? []).filter((_, j) => j !== i),
                        }
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Field label="Soft skills">
              <StringListEditor
                items={skills.soft_skills ?? []}
                placeholder="e.g. mentoring"
                onChange={(items) =>
                  update((d) => void (d.skills = { ...(d.skills ?? {}), soft_skills: items }))
                }
              />
            </Field>
            <Field label="Languages">
              <StringListEditor
                items={skills.languages ?? []}
                placeholder="e.g. English (native)"
                onChange={(items) =>
                  update((d) => void (d.skills = { ...(d.skills ?? {}), languages: items }))
                }
              />
            </Field>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium text-slate-400">
                Certifications (name · issuer · expiry)
              </span>
              <Button
                variant="outline"
                className="px-2.5 py-1 text-xs"
                onClick={() =>
                  update((d) => {
                    d.skills = {
                      ...(d.skills ?? {}),
                      certifications: [...(d.skills?.certifications ?? []), { name: '' }],
                    }
                  })
                }
              >
                <Plus className="h-3.5 w-3.5" />
                Add certification
              </Button>
            </div>
            <div className="space-y-1.5">
              {(skills.certifications ?? []).map((cert, i) => (
                <div key={i} className="flex flex-wrap items-center gap-1.5">
                  {(
                    [
                      ['name', 'name'],
                      ['issuer', 'issuer'],
                      ['expiry', 'expiry'],
                    ] as const
                  ).map(([f, ph]) => (
                    <input
                      key={f}
                      type="text"
                      className={`${inputCls} min-w-28 flex-1`}
                      placeholder={ph}
                      value={String(cert[f] ?? '')}
                      onChange={(e) =>
                        update((d) => {
                          const list = [...(d.skills?.certifications ?? [])]
                          list[i] = { ...list[i], [f]: e.target.value }
                          d.skills = { ...(d.skills ?? {}), certifications: list }
                        })
                      }
                    />
                  ))}
                  <button
                    type="button"
                    className="shrink-0 rounded-lg p-1.5 text-slate-500 hover:bg-slate-800 hover:text-rose-400"
                    title="Remove"
                    onClick={() =>
                      update((d) => {
                        d.skills = {
                          ...(d.skills ?? {}),
                          certifications: (d.skills?.certifications ?? []).filter(
                            (_, j) => j !== i,
                          ),
                        }
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>

      <Card title="Voluntary self-ID (EEO)">
        <p className="mb-3 text-xs text-slate-500">
          Always optional and confidential. Default is “decline to self-identify”;
          change only if you choose to disclose.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          {EEO_FIELDS.map(({ key, label }) => (
            <Field key={key} label={label}>
              <TextInput
                value={draft.eeo?.[key]}
                onChange={(v) =>
                  update((d) => void (d.eeo = { ...(d.eeo ?? {}), [key]: v }))
                }
              />
            </Field>
          ))}
        </div>
      </Card>

      <Card title="Answer bank">
        <p className="mb-3 text-xs text-slate-500">
          Reusable answers for recurring free-text questions.{' '}
          <code className="text-slate-400">{'{company}'}</code> and{' '}
          <code className="text-slate-400">{'{role}'}</code> are filled in per
          application.
        </p>
        <div className="space-y-4">
          {Object.entries(draft.qa_bank ?? {}).map(([key, value]) => (
            <Field key={key} label={key.replaceAll('_', ' ')}>
              <TextArea
                value={value}
                rows={3}
                onChange={(v) =>
                  update((d) => void (d.qa_bank = { ...(d.qa_bank ?? {}), [key]: v }))
                }
              />
            </Field>
          ))}
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
