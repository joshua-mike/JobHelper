# JobHelper

A personal, locally-run daily tool that does the soul-crushing 90% of a job
search — **find, filter, match, tailor, and draft** — then hands you a digest of
2–5 well-matched remote roles, each with a tailored ATS-safe resume and a
cover-letter draft, so you can apply with one click.

It is **not** a mass auto-applier. The design is deliberately human-in-the-loop
and low-volume, because tailored applications convert ~2× better than spray-and-
pray and carry none of the account-ban / ToS risk. Nothing is ever submitted on
your behalf — you review and click apply yourself.

## What it does (Phase 0/1)

```
SOURCE → DEDUPE → HARD FILTER → SCORE → SELECT → TAILOR → DAILY DIGEST
```

- **Sources** (all keyless, remote-focused): Remotive, Arbeitnow, RemoteOK, plus
  per-company Greenhouse / Lever / Ashby boards you curate in `config/sources.yaml`.
- **Dedupe**: a `UNIQUE(job_hash)` constraint means a job is never processed twice.
- **Hard filter**: cheap, deterministic rules (remote, title, keywords, salary,
  location, freshness) from `config/criteria.yaml` — runs before any AI spend.
- **Score**: profile-vs-JD similarity. Semantic if `sentence-transformers` is
  installed, otherwise a built-in lexical scorer.
- **Judge** *(optional, needs `ANTHROPIC_API_KEY`)*: Claude scores the shortlist
  0–100 with a met/missing breakdown.
- **Tailor**: an ATS-safe single-column `.docx` resume + an optional cover-letter
  draft + your reusable screening answers. Company/title/dates are copied verbatim
  from your profile; the LLM may only reword/select bullets — it can't invent.
  A separate keyword-extraction call distills the JD into a ranked term table
  (required/preferred + variants) that steers the tailoring, and every saved
  resume is re-extracted and verified: structural problems (lost sections/dates/
  contact, hidden text) fail the job; keyword coverage `N/M required` + any
  frequency-cap warnings land in the digest and on the dashboard card.
- **Digest**: a dated Markdown file in `data/digests/` with everything you need to
  decide and apply.

**It runs with zero API keys** — you'll get a lexically-ranked digest with a
full-profile resume immediately. Adding `ANTHROPIC_API_KEY` upgrades scoring and
turns on per-job tailoring + cover letters.

## Setup

```powershell
# 1. (recommended) create a virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. install core deps
pip install -r requirements.txt

# 3. create your profile and (optionally) your API key
Copy-Item config\profile.example.yaml config\profile.yaml
Copy-Item .env.example .env            # then edit .env to add ANTHROPIC_API_KEY
#   ...edit config\profile.yaml with your real experience...
#   ...tune config\criteria.yaml and config\sources.yaml...

# 4. run
python run_daily.py
```

Open the path it prints (e.g. `data/digests/digest-2026-06-08.md`).

### Review proposals in the browser (Phase 2)

Instead of (or alongside) the Markdown digest, launch the local review page:

```powershell
python review.py     # serves http://127.0.0.1:8765 and opens your browser
```

Each proposal shows its fit score, met/missing breakdown, the tailored résumé
(one-click download), the cover-letter draft, and your screening answers. Buttons:
**Mark applied** (timestamped), **Approve** (flag intent), **Skip**. Applied/skipped
move to history with an undo. It only tracks *your own* manual applications —
nothing is ever submitted for you.

### Dashboard (metrics + one-click run + review)

A local dashboard shows your job-hunt metrics at a glance — last run, proposed
today, pending review, applications this week, a 30-day activity chart, pipeline
funnel, and per-source stats — and can execute the daily run with live log
streaming (no more terminal required):

```powershell
cd web; npm install; npm run build; cd ..   # one-time (and after UI changes)
python run_ui.py                             # serves http://127.0.0.1:8787
```

The React frontend builds to static files that the FastAPI backend serves
directly, so day-to-day only the one Python process runs. For UI development,
`npm run dev` inside `web/` gives hot reload and proxies `/api` to the backend.

The dashboard's **Review** page has full parity with the standalone review page
(same shared action code, identical status transitions): score/rationale/chips,
cover-letter copy, résumé download, assisted apply, and Mark applied / Approve /
Skip with undo. After a run finishes, a **Pending review** tile appears right on
the Runs page with quick actions, and the sidebar badge shows the queue size —
so the whole find → run → review loop happens at `:8787`. The legacy
`review.py` page still works if you prefer it.

### Settings (edit config from the UI)

The dashboard's **Settings** page edits all three config files with structured
forms — no YAML hand-editing required. Profile (identity, work history,
skills, EEO, answer bank), Sources (aggregator toggles, every board list
including Workday tenants, crawl knobs), and Criteria (full key parity,
grouped). Saves are validated (pydantic), written atomically, preceded by a
timestamped backup in `data/backups/`, and round-tripped through `ruamel.yaml`
so the comments and ordering in the files survive. Each source row has a live
**Verify** button that hits the real board with the real adapter. Mid-run
saves are allowed — they apply from the next run.

**Resume import:** upload a `.docx`/`.txt`/`.md` resume and Claude extracts a
profile proposal (never inventing facts); resume-derived sections are
proposed while compensation / EEO / answer-bank / work-authorization fields
are preserved (or seeded from the example on a fresh clone). You preview the
sectional merge, apply it to the form, review, and only then save. Works on a
fresh clone with no `profile.yaml`; requires `ANTHROPIC_API_KEY`.

### Applications log

Every time you mark a job applied (review page or assisted apply), a row is
appended to `data/applications_log.csv` — date applied, company, title, location,
ATS, fit score, how you applied, and the résumé used. Download it from the review
page header (**⤓ applications log**) or open the CSV directly. Undoing an apply
removes its row, so the log stays in sync with reality.

### Scoring (semantic by default)

Recall ranking uses `sentence-transformers` (semantic) out of the box, so it knows
"AWS" ≈ "cloud platforms" even with no shared words. It's a ~2–3 GB CPU install
(one-time, runs offline after the first model download). To run lean without it,
set `scoring: lexical` in `config/criteria.yaml` and skip that dependency — the
Claude judge still does the precise scoring either way.

## Configuration

| File | What it controls |
|------|------------------|
| `config/profile.yaml` | **Your master profile** — single source of truth, gitignored. Copy from `profile.example.yaml`. |
| `config/criteria.yaml` | Role targeting, keywords, salary floor, remote/location, daily count, score threshold, **per-company diversity cap** (`max_per_company`), scoring mode, model choices. |
| `config/sources.yaml` | Which aggregators are on, and your curated Greenhouse/Lever/Ashby company list. |
| `.env` | `ANTHROPIC_API_KEY` and optional model overrides. Gitignored. |

To add a target company's ATS board, find its slug in the public board URL:
- Greenhouse → `job-boards.greenhouse.io/<slug>`
- Lever → `jobs.lever.co/<slug>`
- Ashby → `jobs.ashbyhq.com/<slug>`

and add `<slug>` under the matching key in `config/sources.yaml` — or use the
dashboard's **Settings → Sources** form, which has a per-row live **Verify**
button so a typo'd (or wrong-case) slug is caught immediately.

## Schedule it (Windows Task Scheduler)

Create a Basic Task → Daily → 7:00 AM → *Start a program*:
- **Program/script:** `C:\path\to\JobHelper\.venv\Scripts\python.exe`
- **Arguments:** `run_daily.py`
- **Start in:** `C:\path\to\JobHelper`

The pipeline is idempotent, so "run task as soon as possible after a missed start"
is safe to enable.

## Why this design (research-backed)

- **No Indeed/LinkedIn APIs.** Indeed's job-seeker API is deprecated; LinkedIn's is
  partner-only and closed to new partners. The stable, ToS-clean path is keyless
  ATS feeds. Automating logged-in LinkedIn/Indeed actions carries a documented
  ~23% 90-day account-restriction risk — so the tool never touches them.
- **ATS-safe resume rules** (single column, contact in body, whitelisted headings,
  `Month YYYY` dates, substantiated skills, no white-text stuffing) are enforced in
  `tailor/resume_docx.py` — these cause more rejections than content does.
- **Knockout questions** reject more candidates than formatting. Your standard
  answers (work auth, sponsorship, salary, years-of-experience computed from your
  history) are surfaced in every digest to copy-paste.
- **Truthful tailoring by construction:** the model may only select/reword facts
  already in your profile.
- **Checker ≠ writer:** keyword coverage is scored by a separate extraction call
  and a boundary-aware matcher (naive `\b` regex never matches `C#`/`.NET`/`C++`),
  then re-measured on plain text extracted from the saved `.docx` — the artifact
  a parser actually sees. JD-required skills you genuinely lack are flagged
  (`missing_required`), never fabricated.

## Project layout

```
config/            profile / criteria / sources YAML
src/jobhelper/
  sources/         one adapter per source (Fetcher = throttle+retry+cache)
  rank/            filters, recall scoring, optional Claude judge
  tailor/          resume content, ATS-safe .docx, cover letter, screening answers
  digest/          daily Markdown digest
  web/             dashboard API (metrics, run control + SSE logs, serves web/dist)
  db.py            SQLite schema + state machine
  pipeline.py      the orchestrator
run_daily.py       entry point (Task Scheduler target)
run_ui.py          dashboard entry point (http://127.0.0.1:8787)
web/               React dashboard frontend (Vite + Tailwind; builds to web/dist)
data/              SQLite db, generated resumes, digests, cache (gitignored)
```

### Assisted apply (Phase 3)

For proposals on a hosted ATS (Greenhouse / Lever / Ashby), the tool can open the
real application form in a browser and auto-fill it — then **stop** so you review
every field and click Submit yourself. Nothing is ever submitted automatically.

```powershell
python -m playwright install chromium   # one-time, after pip install
python apply.py --next                   # assist on the highest-scored pending job
python apply.py 229                       # assist on a specific job id
```

Or click **🌐 Assisted apply** on a card in the review page — it opens the form in
a new window, fills your name/contact/links, attaches the tailored résumé, and
**best-effort auto-answers common screening dropdowns** (sponsorship, work auth,
relocation, EEO self-ID → "decline") derived from your profile. It prints every
auto-answer for you to **verify** (a wrong knockout answer auto-rejects) and lists
anything it left blank. You confirm, review, and submit.

**Why not a one-call API submit?** Greenhouse's and Lever's apply APIs exist, but
their POST endpoints require the *employer's* secret API key (created inside the
company's own ATS account) — an outside applicant can't obtain it. The only path
for applying to companies you don't work for is their hosted web form, so assisted
apply drives that form in a real browser. This is also the lowest-risk channel:
you're a genuine applicant on the company's own site, with a human on the trigger.
LinkedIn/Indeed are never automated.

## Tests

```powershell
python tests\test_tailor_wiring.py   # offline: anti-hallucination + ATS-safe docx
python tests\test_keywords.py        # offline: boundary matcher + coverage + extraction
python tests\test_verify.py          # offline: DOCX re-extraction, structural checks
python tests\test_tailor_ats.py      # offline: display_as containment + missing_required
python tests\test_db_migration.py    # offline: ats_report column migration idempotency
python tests\test_review_smoke.py    # in-process: review actions + status flow
python tests\test_apply_matching.py  # offline: form-field matching across ATS
python tests\test_screening.py       # offline: screening polarity + option matching
python tests\test_applog.py          # offline: applications-log upsert/remove
python tests\test_select_diverse.py  # offline: per-company diversity cap
python tests\test_web_smoke.py       # in-process: dashboard API + stubbed run + SSE
python tests\test_web_review_smoke.py # in-process: review API actions on synthetic rows
python tests\test_settings_store.py  # offline: comment-preserving YAML saves + validation
python tests\test_web_settings_smoke.py # in-process: settings API + stubbed LLM/adapters
```

## Roadmap

- **Phase 0/1 — built & verified.** Find → rank → tailor → digest, runs daily.
- **Phase 2 — built & verified.** Local Approve/Skip/Mark-applied page + tracking.
- **Phase 3 — built & verified.** Assisted apply: Playwright fills the hosted ATS
  form (Greenhouse/Lever/Ashby), best-effort auto-answers common screening
  dropdowns, and stops at Submit. Verified live against real Greenhouse and Lever
  forms. Human always submits; never on LinkedIn/Indeed.
- **Phase 4 — built.** Dashboard UI (React + FastAPI, `run_ui.py`): metrics at a
  glance + execute the daily run with live logs. Tracked as ITEM-2 in personal Jira.
- **Phase 5 — built.** Review integrated into the dashboard (ITEM-3): Review board
  + post-run pending tile, same shared action code as the legacy review page.
- **Phase 6 — built.** Settings page (ITEM-4): edit profile/sources/criteria from
  the UI with comment-preserving saves + backups, per-source live Verify, and
  Claude-powered resume import to bootstrap or refresh the profile.
- **Semantic scoring** (sentence-transformers) and the **applications log** are on
  by default.

### Possible future work

- Workday's multi-step/login apply flow (intentionally left manual — see notes).
- Broader screening coverage (radio-group questions, more combobox variants).
