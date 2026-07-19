// Mirrors src/jobhelper/web/schemas.py — keep the two in sync.

export interface LastRun {
  run_id: string
  started_at: string | null
  finished_at: string | null
  sourced: number
  new_jobs: number
  filtered: number
  scored: number
  proposed: number
  errors: number
  notes: string | null
  duration_seconds: number | null
}

export interface Summary {
  last_run: LastRun | null
  proposed_today: number
  pending_review: number
  applied_total: number
  applied_7d: number
  total_jobs: number
  new_7d: number
}

export interface FunnelEntry {
  status: string
  count: number
}

export interface TimelinePoint {
  date: string
  new: number
  proposed: number
  applied: number
}

export interface SourceStats {
  source: string
  total: number
  new_7d: number
  surfaced: number
  avg_llm_score: number | null
}

export interface RunLogEntry extends LastRun {
  run_state: 'complete' | 'incomplete' | 'running'
}

export interface RecentJob {
  id: number
  title: string | null
  company: string | null
  source: string
  url: string | null
  status: string
  llm_score: number | null
  display_score: number | null
  proposed_in_run_id: string | null
  applied_at: string | null
  updated_at: string | null
}

export type ReviewAction = 'applied' | 'approve' | 'skip' | 'reset'

// ---- ATS keyword coverage (ITEM-8). Distinct from ReviewJob.ats (vendor). --

export interface AtsCoverage {
  required_present: number
  required_total: number
  missing: string[]
}

export interface AtsReport {
  keyword_table?: unknown[] | null
  coverage?: AtsCoverage | null
  missing_required?: string[]
  warnings?: string[]
  error?: string
  variant?: { name: string; signals: string[] } | null
}

export interface ReviewJob {
  id: number
  title: string | null
  company: string | null
  location: string | null
  candidate_location: string | null
  remote_type: string | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  url: string | null
  source: string
  status: string
  llm_score: number | null
  display_score: number
  llm_rationale: string | null
  musthaves_met: string[]
  missing: string[]
  notes: string[]
  screening: Record<string, unknown>
  cover_letter_text: string | null
  has_resume: boolean
  ats: string
  can_assist: boolean
  ats_report: AtsReport | null
  date_posted: string | null
  first_seen_at: string | null
  proposed_in_run_id: string | null
  approved_at: string | null
  applied_at: string | null
  updated_at: string | null
}

export interface ReviewLists {
  pending: ReviewJob[]
  applied: ReviewJob[]
  skipped: ReviewJob[]
}

export interface ReviewActionResult {
  ok: boolean
  job: ReviewJob
}

export interface RunStatus {
  state: 'idle' | 'running'
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  use_cache: boolean
  log_path: string | null
  line_count: number
}

// ---- Settings (ITEM-4) -----------------------------------------------------

export type ConfigName = 'profile' | 'sources' | 'criteria'

export interface SettingsStatus {
  anthropic_available: boolean
  run_active: boolean
  profile_exists: boolean
}

export interface ConfigPayload<T> {
  name: ConfigName
  exists: boolean
  seeded_from_example: boolean
  data: T | null
}

export interface SaveResult {
  ok: boolean
  changed: boolean
  applies_next_run: boolean
  backup: string | null
}

export interface CriteriaData {
  daily_target?: number
  max_per_company?: number
  scoring?: 'auto' | 'semantic' | 'lexical'
  llm_shortlist?: number
  min_score?: number
  title_include_any?: string[]
  title_exclude_any?: string[]
  keywords_any?: string[]
  keywords_exclude?: string[]
  remote_required?: boolean
  onsite_ok_companies?: string[]
  allowed_location_tokens?: string[]
  salary_floor?: number
  exclude_companies?: string[]
  max_age_days?: number
  judge_model?: string
  tailor_model?: string
  [key: string]: unknown
}

export interface WorkdayRow {
  tenant: string
  dc: string
  site: string
  company: string
}

export interface AtsData {
  greenhouse?: string[]
  lever?: string[]
  ashby?: string[]
  smartrecruiters?: string[]
  microsoft?: string[]
  amazon?: string[]
  usajobs?: string[]
  adzuna?: string[]
  workday?: WorkdayRow[]
  [key: string]: unknown
}

export interface SourcesData {
  aggregators?: Record<string, boolean>
  ats?: AtsData
  request_delay_seconds?: number
  per_source_cap?: number
  microsoft_per_query?: number
  amazon_per_query?: number
  usajobs_per_query?: number
  adzuna_per_query?: number
  workday_searches?: string[]
  workday_per_search?: number
  [key: string]: unknown
}

export interface AchievementData {
  text: string
  skills_used?: string[]
  verified?: boolean
  distinctive?: boolean
}

export interface WorkEntryData {
  company: string
  title: string
  location?: string
  start_date?: string
  end_date?: string
  employment_type?: string
  summary?: string
  achievements?: AchievementData[]
}

export interface EducationData {
  institution: string
  degree?: string
  field?: string
  grad_date?: string
  gpa?: number | string | null
}

export interface HardSkillData {
  name: string
  years?: number | null
  proficiency?: string
  group?: string
}

export interface CertificationData {
  name: string
  issuer?: string
  date?: string
  expiry?: string | number
}

export interface SkillsData {
  hard_skills?: HardSkillData[]
  soft_skills?: string[]
  certifications?: CertificationData[]
  languages?: string[]
}

export interface ProfileData {
  identity?: {
    full_name?: string
    email?: string
    phone?: string
    city_state?: string
    linkedin_url?: string
    portfolio_url?: string
    work_authorization_status?: string
    credentials_line?: string
    requires_sponsorship?: boolean
    willing_to_relocate?: boolean
    earliest_start_date?: string
    notice_period?: string
    [key: string]: unknown
  }
  compensation?: {
    desired_salary_min?: number | null
    desired_salary_max?: number | null
    currency?: string
    salary_negotiable?: boolean
    [key: string]: unknown
  }
  summary?: string
  work_history?: WorkEntryData[]
  education?: EducationData[]
  skills?: SkillsData
  eeo?: Record<string, string>
  qa_bank?: Record<string, string>
  variants?: Record<string, VariantData>
  [key: string]: unknown
}

export interface VariantData {
  signals?: string[]
  summary_angle?: string
  skills_group_order?: string[]
  default?: boolean
  [key: string]: unknown
}

export type SourceKind =
  | 'remotive'
  | 'arbeitnow'
  | 'remoteok'
  | 'greenhouse'
  | 'lever'
  | 'ashby'
  | 'smartrecruiters'
  | 'microsoft'
  | 'amazon'
  | 'workday'
  | 'usajobs'
  | 'adzuna'

export interface VerifySourceRequest {
  kind: SourceKind
  token?: string
  entry?: WorkdayRow
}

export interface VerifySourceResult {
  ok: boolean
  count: number
  sample: string[]
  company: string | null
  message: string
}

export interface SourceSuggestion {
  id: number
  kind: string
  token: string
  entry: WorkdayRow | null
  company: string | null
  evidence_count: number
  best_score: number | null
  live_count: number | null
  sample: string[]
  via: 'url' | 'redirect' | 'guess'
  status: 'suggested' | 'accepted' | 'dismissed'
  created_at: string | null
  updated_at: string | null
}

export interface SuggestionScanResult {
  new: number
  suggestions: SourceSuggestion[]
}

export interface SuggestionActionResult {
  ok: boolean
  suggestion: SourceSuggestion
  applies_next_run: boolean
  backup: string | null
}

export interface SectionNote {
  section: string
  action: 'imported' | 'preserved' | 'seeded'
  detail: string
}

export interface ResumeImportResult {
  proposed: ProfileData
  sections: SectionNote[]
  model: string
}
