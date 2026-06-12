"""Assisted-apply runner: open the company's real careers form, fill what we can,
then STOP. The human reviews every field and clicks Submit. Code never submits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import db
from ..config import load_env, load_profile
from ..util import DATA_DIR, get_logger, now_iso
from .fillers import (apply_url, build_apply_data, detect_ats,
                      is_resume_descriptor, match_descriptor)
from .screening import desired_answer, pick_option

log = get_logger()
PROFILE_DIR = DATA_DIR / "browser_profile"

# Returns [label, aria-label, placeholder, name, id] for an element.
JS_PARTS = """(el) => {
  let label = '';
  if (el.id) { try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = l.innerText; } catch(e){} }
  if (!label) { const p = el.closest('label'); if (p) label = p.innerText; }
  return [label, el.getAttribute('aria-label')||'', el.getAttribute('placeholder')||'', el.getAttribute('name')||'', el.id||''];
}"""

# Best question text for a select/combobox: label, fieldset legend, aria-label,
# or a nearby preceding text block.
JS_QUESTION = """(el) => {
  let t = '';
  if (el.id) { try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = l.innerText; } catch(e){} }
  if (!t) { const p = el.closest('label'); if (p) t = p.innerText; }
  if (!t) { const fs = el.closest('fieldset'); const lg = fs ? fs.querySelector('legend') : null; if (lg) t = lg.innerText; }
  if (!t) t = el.getAttribute('aria-label') || '';
  if (!t) { let n = el.previousElementSibling, h = 0; while (n && h < 3) { if (n.innerText && n.innerText.trim().length > 4) { t = n.innerText; break; } n = n.previousElementSibling; h++; } }
  return (t || '').trim();
}"""

_SKIP_TYPES = {"hidden", "submit", "button", "checkbox", "radio", "file",
               "reset", "image", "password", "range", "color"}
# We open the form but NEVER click anything that submits/sends.
_APPLY_OPENERS = ["apply for this job", "apply now", "apply", "submit application form"]


def _ensure_form_visible(page) -> None:
    """If the apply form isn't shown yet, click an 'Apply' opener (never Submit)."""
    if page.query_selector("input[type=email], input[name*='email' i], input[id*='email' i]"):
        return
    for text in _APPLY_OPENERS:
        try:
            loc = page.get_by_role("link", name=text, exact=False)
            if loc.count() == 0:
                loc = page.get_by_role("button", name=text, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def _fill_form(page, data: dict) -> dict[str, Any]:
    report: dict[str, Any] = {"filled": [], "resume": None, "missing": [], "errors": 0}
    used: set[str] = set()

    for el in page.query_selector_all("input, textarea"):
        try:
            typ = (el.get_attribute("type") or "text").lower()
            if typ in _SKIP_TYPES:
                continue
            parts = el.evaluate(JS_PARTS)
            field, _ = match_descriptor(parts)
            if not field or field in used:
                continue
            val = data.get(field)
            if not val:
                continue
            el.scroll_into_view_if_needed(timeout=2000)
            el.fill(val, timeout=3000)
            used.add(field)
            report["filled"].append(field)
        except Exception:
            report["errors"] += 1

    # Resume upload: prefer a file input labelled resume/cv, else the first one.
    resume = data.get("resume_path")
    if resume and Path(resume).exists():
        file_inputs = page.query_selector_all("input[type=file]")
        target = None
        for fi in file_inputs:
            try:
                if is_resume_descriptor(fi.evaluate(JS_PARTS)):
                    target = fi
                    break
            except Exception:
                continue
        if target is None and file_inputs:
            target = file_inputs[0]
        if target is not None:
            try:
                target.set_input_files(resume, timeout=5000)
                report["resume"] = resume
            except Exception:
                report["errors"] += 1

    # Standard fields we had data for but couldn't place (so the human knows).
    name_ok = ("full_name" in used) or ({"first_name", "last_name"} <= used)
    for f in ("email", "phone"):
        if data.get(f) and f not in used:
            report["missing"].append(f)
    if data.get("full_name") and not name_ok:
        report["missing"].append("name")
    return report


def _answer_screening(page, profile: dict, report: dict) -> None:
    """Best-effort answers to native <select> and ARIA-combobox screening questions.

    Every choice is recorded in report['screening_answered'] for human verification.
    Never touches free-text or anything it can't map confidently.
    """
    report.setdefault("screening_answered", [])
    report.setdefault("screening_skipped", [])

    # 1) Native <select> dropdowns
    for sel in page.query_selector_all("select"):
        try:
            question = sel.evaluate(JS_QUESTION)
            rule, kind = desired_answer(question, profile)
            if not rule or not kind:
                continue
            opts = sel.evaluate("(s) => Array.from(s.options).map(o => o.text)")
            idx = pick_option(opts, kind)
            if idx is None:
                report["screening_skipped"].append(rule)
                continue
            sel.select_option(index=idx)
            report["screening_answered"].append((rule, opts[idx].strip()))
        except Exception:
            report["errors"] = report.get("errors", 0) + 1

    # 2) Custom ARIA comboboxes (Greenhouse's newer boards). Best-effort; scoped
    #    to the opened listbox so we never click a stray option.
    for trg in page.query_selector_all("[role='combobox'], [aria-haspopup='listbox']"):
        try:
            question = trg.evaluate(JS_QUESTION)
            rule, kind = desired_answer(question, profile)
            if not rule or not kind:
                continue
            trg.scroll_into_view_if_needed(timeout=1500)
            trg.click(timeout=2000)
            page.wait_for_timeout(350)
            listbox_id = trg.get_attribute("aria-controls")
            scope = page.query_selector(f"#{listbox_id}") if listbox_id else page
            options = scope.query_selector_all("[role='option']") if scope else []
            texts = [o.inner_text() for o in options]
            idx = pick_option(texts, kind)
            if idx is not None:
                options[idx].click(timeout=2000)
                report["screening_answered"].append((rule, texts[idx].strip()))
            else:
                page.keyboard.press("Escape")
                report["screening_skipped"].append(rule)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
    return report


def _print_summary(job: dict, ats: str, data: dict, report: dict, profile: dict) -> None:
    from ..tailor import screening_answers
    ans = screening_answers(profile)
    print("\n" + "=" * 64)
    print(f"  ASSISTED APPLY — {job.get('title','')} @ {job.get('company','')}")
    print(f"  ATS: {ats}   |   {job.get('url','')}")
    print("=" * 64)
    print(f"  Auto-filled: {', '.join(report['filled']) or '(none)'}")
    print(f"  Resume attached: {'yes' if report['resume'] else 'NO — attach manually'}")
    if report["missing"]:
        print(f"  COULD NOT place: {', '.join(report['missing'])} — fill these by hand")

    answered = report.get("screening_answered", [])
    if answered:
        print("\n  Auto-answered screening dropdowns (VERIFY each — wrong answers auto-reject):")
        for rule, choice in answered:
            print(f"    {rule:20} -> {choice}")
    if report.get("screening_skipped"):
        print(f"  Screening left for you: {', '.join(report['screening_skipped'])}")

    print("\n  Your answers for any remaining questions:")
    print(f"    Years experience : {ans.get('years_of_experience','')}")
    print(f"    Work authorization: {ans.get('work_authorization','')}")
    print(f"    Needs sponsorship : {ans.get('requires_sponsorship','')}")
    print(f"    Willing to relocate: {ans.get('willing_to_relocate','')}")
    print(f"    Desired salary    : {ans.get('desired_salary','')}")
    print(f"    Earliest start    : {ans.get('earliest_start_date','')}")
    print("\n  >> REVIEW EVERY FIELD, including auto-answered dropdowns. Then click")
    print("     Submit YOURSELF. This tool never submits for you.")
    print("=" * 64)


def pick_next() -> int | None:
    conn = db.connect()
    db.init_db(conn)
    row = conn.execute(
        "SELECT id FROM jobs WHERE status IN ('approved','tailored','proposed') "
        "ORDER BY (llm_score IS NULL), llm_score DESC LIMIT 1").fetchone()
    conn.close()
    return row[0] if row else None


def assisted_apply(job_id: int, headless: bool = False) -> dict | None:
    load_env()
    profile = load_profile()
    conn = db.connect()
    db.init_db(conn)
    row = db.get_job(conn, job_id)
    if not row:
        log.error("No job with id=%s", job_id)
        return None
    job = dict(row)
    if not job.get("url"):
        log.error("Job %s has no apply URL", job_id)
        return None

    data = build_apply_data(profile, job)
    ats = detect_ats(job["url"])
    target = apply_url(job["url"], ats)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless, no_viewport=not headless,
            args=["--start-maximized"] if not headless else [])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            _ensure_form_visible(page)
            report = _fill_form(page, data)
            _answer_screening(page, profile, report)
        except Exception as exc:
            log.error("fill failed: %s", exc)
            report = {"filled": [], "resume": None, "missing": [], "errors": 1}

        _print_summary(job, ats, data, report, profile)

        if headless:  # automated test path: capture proof, don't wait
            shot = DATA_DIR / f"apply_debug_{job_id}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                print(f"  [headless] screenshot: {shot}")
            except Exception:
                pass
            ctx.close()
            return report

        try:
            ans = input("\nAfter you SUBMIT in the browser, type 'y' to mark this "
                        "job applied (anything else leaves it pending): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans == "y":
            stamp = now_iso()
            db.update_job(conn, job_id, status="applied", applied_at=stamp,
                          submit_confirmation=f"assisted apply ({ats})")
            conn.commit()
            from ..applog import record_application
            record_application({**job, "applied_at": stamp}, f"assisted-apply ({ats})")
            print("Marked as applied and logged.")
        ctx.close()
    conn.close()
    return report
