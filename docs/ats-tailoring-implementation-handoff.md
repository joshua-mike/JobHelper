# ATS-Optimized Resume Tailoring Engine — Implementation Handoff

**Ticket:** [ITEM-8](https://joshuamike.atlassian.net/browse/ITEM-8) (Subtask of ITEM-1)
**Design agreed:** 2026-07-11 grilling session. Every decision below was explicitly confirmed — implement as written; don't re-litigate.
**Research source:** `docs/ats-resume-optimization-research.md` (the July 2026 ATS handoff brief — read §1, §2, §5 before starting).

## Context

JobHelper's daily pipeline ([pipeline.py](../src/jobhelper/pipeline.py)) proposes ~4 jobs/day (`daily_target`), then step 6 tailors a resume per job: `tailor_resume()` (LLM, anti-hallucination assembly) → `build_resume()` (ATS-safe DOCX) → DB row update. The parser-gate rules from the research (§1) are already implemented in [resume_docx.py](../src/jobhelper/tailor/resume_docx.py). This work adds the **ranker gate** (keyword extraction + coverage) and a **verification pass**, plus small renderer fixes.

Human-in-the-loop is a hard invariant: nothing is submitted without Josh reviewing in the dashboard (`run_ui.py`, :8787). The anti-hallucination design in [tailor.py](../src/jobhelper/tailor/tailor.py) (companies/titles/dates copied verbatim; LLM output validated against profile) must survive intact.

## Agreed design decisions

1. **Keyword extraction = separate structured LLM call** (checker independent of writer — the coverage report must not be the tailor call grading its own homework). Runs per proposed job before tailoring. Input: job title/company + **full** `description_clean` capped at 15,000 chars (the tailor call's existing 5,000 cap stays — it receives the distilled table). Output schema: ranked list of `{term, category: hard_skill|method|title|soft, required: bool, variants: [...]}` where variants carry acronym/expansion pairs and 2–3 semantic variations (§2 of research). Model: reuse the existing `tailor_model` criteria knob — **no new config keys anywhere in this feature**; frequency cap and char limits are code constants.

2. **Tailor prompt/schema upgrade:** inject the keyword table (required terms first, with variants). Instructions encode §2: mirror JD's exact wording where truthful; acronym + expansion once each; aim for 2–3 placements of each required term (summary, one evidence bullet, skills line); never place a keyword without profile evidence; 60–80% of bullets follow `action verb + task-with-keyword + quantified outcome` using only numbers present in profile achievements. New schema field **`missing_required`**: JD-required terms the candidate genuinely lacks (flag, don't fabricate — §5.4).

3. **Skills mirroring fix** (resolves the conflict between §2 "mirror exact wording" and the exact-match whitelist at `tailor.py:144-145`): `skills_order` entries become `{skill, display_as}` pairs.
   - `skill` must exist in profile (exact case-insensitive match, unchanged behavior).
   - `display_as` must **contain** `skill` as a token, checked with the boundary-aware matcher (below) — so "Amazon Web Services (AWS)" validates for "AWS".
   - `display_as` capped at ~60 chars; validation failure → silently fall back to plain skill name.
   - Every surviving alias gets a `change_notes` entry ("displayed 'AWS' as 'Amazon Web Services (AWS)'").
   - Prompt instruction: expansion or JD's exact phrasing only — never add versions, certifications, or proficiency levels.
   - Bullets/summary are free text and may mirror JD terminology already — no change there.

4. **Boundary-aware matcher** — THE load-bearing detail. Naive `\b` regex **never matches C#, .NET, or C++** (`#`, `+`, `.` are non-word chars; `\b` requires a word↔non-word transition, so `\bC#\b` fails on "C#, " and `\b\.NET\b` fails on " .NET"). Josh's profile is C#/.NET-heavy; get this wrong and the coverage report systematically lies about his core skills. Build guards per-term from the term's edge characters:
   - Left guard: `(?<!\w)`.
   - Right guard: `(?!\w)` if the term ends in a word char; `(?![#+\w])` if it ends in `#`/`+`.
   - `re.escape` the term; match case-insensitively.
   - A term counts as **present** if the term itself or any extractor-supplied variant hits. Same machinery counts occurrences for the frequency cap.
   - Known/accepted behavior: "ASP.NET" does NOT count as a ".NET" hit (skills line always renders ".NET" verbatim anyway — assembly re-appends dropped profile skills).

5. **Verification pass** — runs against **plain text re-extracted from the saved DOCX** (walk paragraphs with python-docx), not the in-memory dict, so we test the artifact. Two check classes with different failure policy (**no auto-retry in v1**):
   - **Structural (hard-fail → existing per-job `status='error'` path):** every company, title, and date range from the content dict present in extracted text **in order**; all section headings present; contact info within first 5 lines of body; no hidden runs (scan runs for `font.hidden` / white RGB — we never write these; the scan makes §3's no-hidden-text guarantee explicit).
   - **Model-behavior (warn only, into `ats_report.warnings`):** required-keyword coverage `N/M`; frequency cap — flag any term with >4 hits document-wide. Low coverage is information (`missing_required`), not an error.

6. **Storage:** new `jobs.ats_report` TEXT (JSON) column holding `{keyword_table, coverage: {required_present, required_total, missing}, missing_required, warnings, error?}`. Migration: idempotent guard in `db.init_db()` — check `PRAGMA table_info(jobs)`, `ALTER TABLE jobs ADD COLUMN` if absent (~6 lines; there is no migration framework, `SCHEMA` is `CREATE TABLE IF NOT EXISTS` so editing SCHEMA alone does nothing for the existing `data/jobhelper.db`). Add `ats_report` to `_WRITABLE` in [db.py](../src/jobhelper/db.py). Old rows stay NULL; UI shows nothing for them — accepted, no backfill.

7. **Renderer changes** ([resume_docx.py](../src/jobhelper/tailor/resume_docx.py)):
   - Heading `SUMMARY` → `PROFESSIONAL SUMMARY` (parsers segment on literal heading strings; other headings already on the §1 whitelist — leave them).
   - Job entry becomes 3 lines per §4 skeleton: **Title** (bold, own line) / `Company — Location` / `Month YYYY – Month YYYY`. (Current `Title — Company` one-liner is the exact pattern §1 warns against.)
   - Skills stay a flat comma-separated list (no category data in `HardSkill`; grouping explicitly rejected for v1).
   - Resume path: `data/resumes/{date}/{id}/Firstname_Lastname_{RoleSlug}.docx` — job id becomes a **folder**, filename is recruiter-facing (name from `profile.identity.full_name`, role slug via the existing `_safe()` helper in pipeline.py, truncated to keep paths sane). `tailored_resume_path` stores the full path so downstream (apply, review, digest) keeps working unchanged.

8. **Surfacing:**
   - **Digest** ([digest.py](../src/jobhelper/digest/digest.py)): one line per job — `ATS coverage: 7/9 required · missing: Kubernetes, Terraform` — plus warnings only when present.
   - **Dashboard:** `enrich()` in [review/actions.py](../src/jobhelper/review/actions.py) parses the JSON → job `ats_report` key; add `"ats_report"` to `_FIELDS` in [web/review.py](../src/jobhelper/web/review.py). **Naming caution:** there is an existing `ats` field (detected ATS vendor for assisted apply) — do not collide. Card UI (static assets under repo-root `web/`): small coverage badge + missing-required chips + warnings; follow the existing chips pattern (`musthaves_met`/`missing`). Legacy review page: untouched (shared `enrich()` means it keeps working; only the dashboard gets rendering).
   - Full keyword table stays in the blob — no UI in v1. Per-term evidence view: explicitly deferred.

9. **Degradation:**
   - Extraction call fails/garbage → **soft-fail**: tailor without keyword table (today's behavior), write `ats_report = {"error": "keyword extraction failed"}` so the card shows why there's no badge. A dead extraction call must not cost a day's proposals.
   - No-LLM mode (`llm.available == False`) → no extraction/coverage, passthrough resume as today, but **structural verification still runs** (needs no LLM; protects the passthrough artifact).
   - Cover letter: **unchanged** — no keyword table injection.

## Out of scope (explicitly rejected — do not add)

PDF sibling output; title variants ("Software Engineer III (Senior Software Engineer)"); skills category grouping; auto-retry on verification warnings; evidence-per-term UI; new criteria.yaml knobs; backfilling old rows.

## File-by-file plan

| File | Change |
|---|---|
| `src/jobhelper/tailor/keywords.py` (new) | `KEYWORD_SCHEMA`, `extract_keywords(llm, model, job)`, `term_pattern(term)` (boundary guards), `count_hits`/`coverage(text, table)` |
| `src/jobhelper/tailor/verify.py` (new) | `extract_docx_text(path)`, structural checks (hard), quality checks (warn), `build_ats_report(...)` |
| `src/jobhelper/tailor/tailor.py` | `tailor_resume(..., keywords=None)`; prompt + schema upgrade (`{skill, display_as}` pairs, `missing_required`); containment validation w/ fallback + change-notes |
| `src/jobhelper/tailor/resume_docx.py` | heading, 3-line job entry |
| `src/jobhelper/tailor/__init__.py` | export new functions |
| `src/jobhelper/db.py` | `ats_report` migration guard + `_WRITABLE` |
| `src/jobhelper/pipeline.py` | step 6 wiring: extract → tailor → build (new path scheme) → verify → hard-fail vs warn → `update_job(ats_report=...)` |
| `src/jobhelper/review/actions.py` | `enrich()` parses `ats_report` |
| `src/jobhelper/web/review.py` | `_FIELDS` + `"ats_report"` |
| repo-root `web/` static assets | dashboard card: coverage badge, missing chips, warnings |
| `src/jobhelper/digest/digest.py` | coverage/missing/warnings lines |
| `README.md` | tailoring section: keyword/verification flow |

LLM plumbing: reuse `LLM.structured(...)` from [llm.py](../src/jobhelper/llm.py) exactly as `tailor_resume` does (`tool_name`, `model`, `max_tokens` ~1200 for extraction).

## Tests (non-negotiable)

1. **Golden matcher test**: every hard skill in the real `config/profile.yaml` must match in rendered text; negatives: `Java` must NOT match inside `JavaScript`, `C#` not inside `C##`; `C#`/`.NET`/`C++` must match adjacent to spaces, commas, periods, line ends.
2. **verify.py round-trip**: render a known content dict → verification passes; mutate (drop a date range, blank contact) → structural failure fires.
3. **display_as containment**: accepts `Amazon Web Services (AWS)` for `AWS`; rejects non-containing alias (falls back to plain skill); enforces length cap.
4. **Migration idempotency**: `init_db` on a DB without `ats_report` adds it; running twice harmless.
5. Update `tests/test_tailor_wiring.py` for new signature + `ats_report` persistence.

## Gotchas / housekeeping

- `config/criteria.yaml` and `config/sources.yaml` have **unrelated uncommitted local modifications** — keep them out of any commit for this work.
- The real `data/jobhelper.db` has live history; test migrations against a copy, never mutate it destructively.
- Windows paths; repo lives at `Y:\JobHelper`; run tests with `pytest` from repo root.
- Commit style: see recent history (`feat:`/`fix:` + ITEM-n reference), e.g. `feat: ATS keyword extraction + coverage verification for tailoring (ITEM-8)`.
