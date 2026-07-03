import { useState } from 'react'
import { useSettingsStatus } from '../api/hooks'
import { CriteriaSection } from '../components/settings/CriteriaSection'
import { ProfileSection } from '../components/settings/ProfileSection'
import { SourcesSection } from '../components/settings/SourcesSection'

const TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'sources', label: 'Sources' },
  { id: 'criteria', label: 'Criteria' },
] as const

type TabId = (typeof TABS)[number]['id']

export default function SettingsPage() {
  const [tab, setTab] = useState<TabId>('profile')
  const { data: status } = useSettingsStatus()

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-slate-400">
          Edit the config files from here — comments and formatting in the YAML are
          preserved, and every save writes a timestamped backup to{' '}
          <code className="rounded bg-slate-800 px-1 py-0.5 text-xs">data/backups/</code>.
        </p>
      </div>

      {status?.run_active && (
        <div className="rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">
          A run is in progress — it started with the previous config. Saves are fine,
          but they apply from the <span className="font-semibold">next</span> run.
        </div>
      )}

      <div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              tab === id
                ? 'bg-slate-800 text-slate-100'
                : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'profile' && <ProfileSection status={status} />}
      {tab === 'sources' && <SourcesSection />}
      {tab === 'criteria' && <CriteriaSection />}
    </div>
  )
}
