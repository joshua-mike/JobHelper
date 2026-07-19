"""Offline tests for the ATS-upgraded tailor call (ITEM-8).

Covers the {skill, display_as} mirroring fix (boundary-aware containment,
length cap, silent fallback, change-note per alias), the missing_required
flag, and keyword-table injection into the prompt. FakeLLM only — no network.

Run:  python tests/test_tailor_ats.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.tailor import tailor as T  # noqa: E402

PROFILE = {
    "identity": {"full_name": "Jane Doe", "email": "j@x.com", "phone": "555",
                 "city_state": "Remote (US)"},
    "summary": "Backend engineer.",
    "work_history": [
        {"company": "Acme Cloud", "title": "Senior Software Engineer",
         "location": "Remote", "start_date": "2021-03", "end_date": "Present",
         "achievements": [{"text": "Shipped billing API on AWS.", "distinctive": True},
                          {"text": "Improved deploys."}]},
    ],
    "education": [],
    "skills": {"hard_skills": [{"name": "Python"}, {"name": "FastAPI"},
                               {"name": "PostgreSQL"}, {"name": "AWS"},
                               {"name": "Java"}],
               "soft_skills": [], "certifications": []},
}

JOB = {"title": "Senior Backend Engineer", "company": "Globex",
       "location": "Remote", "description_clean": "Python and AWS."}

KEYWORDS = [
    {"term": "Amazon Web Services (AWS)", "category": "hard_skill",
     "required": True, "variants": ["AWS"]},
    {"term": "Agile", "category": "method", "required": False, "variants": []},
]


class FakeLLM:
    available = True

    def __init__(self, result):
        self._result = result
        self.last_user = None

    def structured(self, system, user, *, schema, tool_name, model, max_tokens=1024):
        self.last_system = system
        self.last_user = user
        self.last_schema = schema
        return self._result


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def run_tailor(result, keywords=None):
    llm = FakeLLM(result)
    content, notes, missing = T.tailor_resume(llm, "fake", PROFILE, JOB,
                                              keywords=keywords)
    return content, notes, missing, llm


BASE_RESULT = {
    "summary": "Tailored summary.",
    "skills_order": [],
    "jobs": [],
    "change_notes": ["model note"],
    "missing_required": [],
}


def test_display_as_accepted():
    print("== display_as: valid alias accepted ==")
    r = dict(BASE_RESULT)
    r["skills_order"] = [{"skill": "AWS", "display_as": "Amazon Web Services (AWS)"},
                         {"skill": "Python", "display_as": ""}]
    content, notes, _, _ = run_tailor(r)
    check(content["skills"][0] == "Amazon Web Services (AWS)",
          "alias containing the skill token is displayed")
    check(content["skills"][1] == "Python", "empty display_as -> plain skill")
    check(any("displayed 'AWS' as 'Amazon Web Services (AWS)'" in n for n in notes),
          "change note records the alias")


def test_display_as_rejected():
    print("== display_as: invalid aliases fall back silently ==")
    long_alias = "Amazon Web Services (AWS) certified cloud practitioner platform engineering"
    r = dict(BASE_RESULT)
    r["skills_order"] = [
        {"skill": "PostgreSQL", "display_as": "MySQL databases"},   # not containing
        {"skill": "Java", "display_as": "JavaScript"},              # substring, not token
        {"skill": "AWS", "display_as": long_alias},                 # over 60-char cap
    ]
    content, notes, _, _ = run_tailor(r)
    check(content["skills"][0] == "PostgreSQL", "non-containing alias -> plain skill")
    check(content["skills"][1] == "Java",
          "Java alias 'JavaScript' rejected (boundary-aware containment)")
    check(content["skills"][2] == "AWS", f"alias over cap rejected ({len(long_alias)} chars)")
    check(not any("displayed" in n for n in notes), "no change notes for fallbacks")


def test_skills_integrity():
    print("== skills: invented dropped, plain strings ok, dedup, nothing lost ==")
    r = dict(BASE_RESULT)
    r["skills_order"] = ["FastAPI",                                   # plain string form
                         {"skill": "Rust", "display_as": "Rust"},     # invented
                         {"skill": "fastapi", "display_as": ""}]      # duplicate
    content, _, _, _ = run_tailor(r)
    check(content["skills"][0] == "FastAPI", "plain string entry accepted")
    check("Rust" not in content["skills"], "invented skill dropped")
    check(content["skills"].count("FastAPI") == 1, "duplicate entry deduped")
    check({"Python", "PostgreSQL", "AWS", "Java"} <= set(content["skills"]),
          "dropped profile skills re-appended")


def test_missing_required():
    print("== missing_required flows out ==")
    r = dict(BASE_RESULT)
    r["missing_required"] = ["Kubernetes", "  ", "Terraform"]
    _, _, missing, _ = run_tailor(r)
    check(missing == ["Kubernetes", "Terraform"], "missing_required cleaned + returned")


def test_keyword_injection():
    print("== keyword table injection ==")
    _, _, _, llm = run_tailor(dict(BASE_RESULT), keywords=KEYWORDS)
    check("Amazon Web Services (AWS)" in llm.last_user, "term in prompt")
    check("REQUIRED" in llm.last_user, "required flag in prompt")
    check("missing_required" in str(llm.last_schema["properties"]),
          "schema carries missing_required")

    _, _, _, llm2 = run_tailor(dict(BASE_RESULT), keywords=None)
    check("KEYWORD TABLE" not in llm2.last_user, "no table block when keywords absent")


def test_distinctive_and_embedding_prompt():
    print("== ITEM-14: [DISTINCTIVE] tagging + embedding instructions ==")
    _, _, _, llm = run_tailor(dict(BASE_RESULT))
    check("[DISTINCTIVE] Shipped billing API on AWS." in llm.last_user,
          "flagged achievement tagged in the prompt")
    check("- Improved deploys." in llm.last_user
          and "[DISTINCTIVE] Improved deploys." not in llm.last_user,
          "unflagged achievement left untagged")
    check("[DISTINCTIVE]" in llm.last_system,
          "instructions explain the DISTINCTIVE tag")
    check("at most once" in llm.last_system,
          "metric-once rule present in instructions")
    check("complete outcome sentence" in llm.last_system,
          "full-sentence (embedding) rule present in instructions")
    check(T.distinctive_achievements(PROFILE) == ["Shipped billing API on AWS."],
          "distinctive_achievements collects flagged texts")


def test_no_llm_and_failure():
    print("== degradation ==")
    class NoLLM:
        available = False
    content, notes, missing = T.tailor_resume(NoLLM(), "fake", PROFILE, JOB)
    check(content["skills"], "passthrough content without LLM")
    check(missing == [], "no missing_required without LLM")

    content2, notes2, missing2 = T.tailor_resume(FakeLLM(None), "fake", PROFILE, JOB,
                                                 keywords=KEYWORDS)
    check(content2["skills"], "fallback content when structured() fails")
    check(missing2 == [], "no missing_required on failure")


def main() -> int:
    test_display_as_accepted()
    test_display_as_rejected()
    test_skills_integrity()
    test_missing_required()
    test_keyword_injection()
    test_distinctive_and_embedding_prompt()
    test_no_llm_and_failure()
    print("\nALL TAILOR-ATS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
