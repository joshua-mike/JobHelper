"""Offline tests for role-family variant presets (ITEM-15).

Covers pure-code signal selection (threshold, boundary-awareness, config-order
precedence, default fallback), group reordering through the tailor, prompt
injection of the VARIANT EMPHASIS block, and the ats_report variant blob.

Run:  python tests/test_variants.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.tailor import tailor as T  # noqa: E402
from jobhelper.tailor import variants as VR  # noqa: E402
from jobhelper.tailor import verify as V  # noqa: E402


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


PROFILE = {
    "identity": {"full_name": "Jane Doe", "email": "j@x.com", "phone": "555",
                 "city_state": "Remote (US)"},
    "summary": "Backend engineer.",
    "work_history": [
        {"company": "Acme Cloud", "title": "Senior Software Engineer",
         "location": "Remote", "start_date": "2021-03", "end_date": "Present",
         "achievements": [{"text": "Shipped billing API on AWS."}]},
    ],
    "education": [],
    "skills": {"hard_skills": [{"name": "Python", "group": "Languages"},
                               {"name": "PostgreSQL", "group": "Data"},
                               {"name": "Docker", "group": "DevOps"}],
               "soft_skills": [], "certifications": []},
    "variants": {
        "cleared": {
            "signals": ["clearance", "secret", "dod", "defense"],
            "summary_angle": "Lead with the clearance.",
            "skills_group_order": ["DevOps", "Data", "Languages"],
        },
        "ms-ai": {
            "signals": ["machine learning", "ai", "python"],
            "summary_angle": "Lead with the ML trajectory.",
        },
        "general": {
            "default": True,
            "summary_angle": "Lead with backend depth.",
        },
    },
}


def job(desc, title="Software Engineer"):
    return {"title": title, "company": "Globex", "description_clean": desc}


def test_selection():
    print("== select_variant: thresholds, boundaries, precedence ==")
    name, cfg, sig = VR.select_variant(
        PROFILE, job("Active Secret clearance required for DoD systems."))
    check(name == "cleared" and len(sig) >= 2,
          f"cleared wins on >=2 signals ({name}, {sig})")

    name, _, sig = VR.select_variant(
        PROFILE, job("Python services with machine learning pipelines."))
    check(name == "ms-ai", f"ms-ai wins on ML signals ({name}, {sig})")

    name, _, sig = VR.select_variant(
        PROFILE, job("Machine learning on DoD systems; Secret clearance."))
    check(name == "cleared",
          f"config order = precedence: cleared beats ms-ai ({name})")

    name, _, sig = VR.select_variant(
        PROFILE, job("We maintain great aim in our domain."))
    check(name == "general" and sig == [],
          f"'maintain'/'aim'/'domain' never hit 'ai' — default wins ({name})")

    name, _, sig = VR.select_variant(
        PROFILE, job("Our government clients expect quality."))
    check(name == "general",
          f"one stray signal is below threshold — default wins ({name})")

    name, cfg, sig = VR.select_variant({}, job("anything"))
    check(name is None and cfg is None and sig == [],
          "no variants configured -> (None, None, [])")


def test_group_reorder_through_tailor():
    print("== variant group order applies in the no-LLM path ==")
    class NoLLM:
        available = False
    _, cfg, _ = VR.select_variant(
        PROFILE, job("Secret clearance, DoD environment."))
    content, _, _ = T.tailor_resume(NoLLM(), "fake", PROFILE, job("x"),
                                    variant_name="cleared", variant=cfg)
    check([g["label"] for g in content["skill_groups"]] ==
          ["DevOps", "Data", "Languages"],
          f"groups reordered per variant ({[g['label'] for g in content['skill_groups']]})")

    content2, _, _ = T.tailor_resume(NoLLM(), "fake", PROFILE, job("x"))
    check([g["label"] for g in content2["skill_groups"]] ==
          ["Languages", "Data", "DevOps"],
          "no variant -> profile group order")


class FakeLLM:
    available = True

    def structured(self, system, user, *, schema, tool_name, model,
                   max_tokens=1024):
        self.last_system, self.last_user = system, user
        return {"summary": "S.", "skills_order": [], "jobs": [],
                "change_notes": [], "missing_required": []}


def test_prompt_and_notes():
    print("== VARIANT EMPHASIS block + change note ==")
    llm = FakeLLM()
    _, cfg, _ = VR.select_variant(
        PROFILE, job("Secret clearance, DoD environment."))
    _, notes, _ = T.tailor_resume(llm, "fake", PROFILE, job("x"),
                                  variant_name="cleared", variant=cfg)
    check("VARIANT EMPHASIS (cleared): Lead with the clearance." in llm.last_user,
          "variant block injected into the prompt")
    check("VARIANT EMPHASIS" in llm.last_system,
          "instructions explain the variant block")
    check(any("variant 'cleared'" in n for n in notes),
          f"change note records the variant ({notes})")

    llm2 = FakeLLM()
    T.tailor_resume(llm2, "fake", PROFILE, job("x"))
    check("VARIANT EMPHASIS" not in llm2.last_user,
          "no variant -> no block in prompt")


def test_report_blob():
    print("== ats_report carries the variant ==")
    r = V.build_ats_report(None, "text", None,
                           variant={"name": "cleared", "signals": ["dod"]})
    check(r["variant"] == {"name": "cleared", "signals": ["dod"]},
          "variant blob stored")
    r2 = V.build_ats_report(None, "text", None)
    check("variant" not in r2, "no variant -> key absent (back-compat)")


def main() -> int:
    test_selection()
    test_group_reorder_through_tailor()
    test_prompt_and_notes()
    test_report_blob()
    print("\nALL VARIANT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
