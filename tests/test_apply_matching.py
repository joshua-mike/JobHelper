"""Offline tests for the assisted-apply matching core (no browser, no network).

Validates field matching against descriptors taken from REAL Greenhouse and Lever
forms, plus ATS detection, apply-URL derivation, name splitting, and data assembly.
Run:  python tests/test_apply_matching.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.apply.fillers import (apply_url, build_apply_data, detect_ats,
                                     is_resume_descriptor, match_descriptor,
                                     match_field, split_name, workday_skills)


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    print("== match_field (single descriptors) ==")
    cases = {
        "First Name": "first_name", "first_name": "first_name", "Given Name": "first_name",
        "Last Name *": "last_name", "Surname": "last_name", "family_name": "last_name",
        "Full name": "full_name", "Name *": "full_name", "Your Name": "full_name",
        "Email": "email", "e-mail address": "email",
        "Phone": "phone", "Mobile Phone": "phone", "Telephone": "phone",
        "LinkedIn Profile": "linkedin", "GitHub URL": "github",
        "Website": "website", "Portfolio": "website",
        "Location (City)": "location", "Current City": "location",
        "Cover Letter": "cover_letter",
    }
    for desc, expected in cases.items():
        check(match_field(desc) == expected, f"'{desc}' -> {expected}")

    print("== match_field negatives (avoid mis-fill) ==")
    check(match_field("Company Name") is None, "'Company Name' -> None (not full_name)")
    check(match_field("Resume/CV") is None, "'Resume/CV' -> None (file, handled separately)")
    check(match_field("") is None, "'' -> None")

    print("== match_descriptor (real form descriptor arrays) ==")
    # Greenhouse: [label, aria, placeholder, name, id]
    gh_first = ["First Name *", "", "", "first_name", "first_name"]
    gh_email = ["Email *", "", "", "email", "email"]
    check(match_descriptor(gh_first) == ("first_name", "First Name *"), "GH first name")
    check(match_descriptor(gh_email) == ("email", "Email *"), "GH email")
    # Lever: label often empty, name carries meaning
    lv_name = ["", "", "Full name", "name", ""]
    lv_email = ["", "", "Email", "email", ""]
    lv_link = ["", "", "", "urls[LinkedIn]", ""]
    check(match_descriptor(lv_name)[0] == "full_name", "Lever full name via placeholder")
    check(match_descriptor(lv_email)[0] == "email", "Lever email")
    check(match_descriptor(lv_link)[0] == "linkedin", "Lever LinkedIn via name attr")

    print("== resume descriptor ==")
    check(is_resume_descriptor(["Resume/CV", "", "", "resume", "resume"]), "GH resume input")
    check(is_resume_descriptor(["", "", "Attach CV", "", ""]), "CV via placeholder")
    check(not is_resume_descriptor(["First Name", "", "", "first_name", ""]), "name is not resume")

    print("== detect_ats ==")
    check(detect_ats("https://job-boards.greenhouse.io/gitlab/jobs/123") == "greenhouse", "GH url")
    check(detect_ats("https://jobs.lever.co/netflix/abc-123") == "lever", "Lever url")
    check(detect_ats("https://jobs.ashbyhq.com/ramp/xyz") == "ashby", "Ashby url")
    check(detect_ats("https://acme.com/careers/1") == "generic", "generic url")

    print("== apply_url ==")
    check(apply_url("https://jobs.lever.co/netflix/abc-123", "lever")
          == "https://jobs.lever.co/netflix/abc-123/apply", "Lever gets /apply")
    check(apply_url("https://jobs.lever.co/x/1/apply", "lever")
          == "https://jobs.lever.co/x/1/apply", "Lever /apply not doubled")
    gh = "https://job-boards.greenhouse.io/gitlab/jobs/123"
    check(apply_url(gh, "greenhouse") == gh, "GH url unchanged (form on page)")

    print("== split_name ==")
    check(split_name("Jane Doe") == ("Jane", "Doe"), "two-part name")
    check(split_name("Jane Q Doe") == ("Jane", "Q Doe"), "three-part name")
    check(split_name("Madonna") == ("Madonna", ""), "single name")

    print("== build_apply_data ==")
    profile = {"identity": {"full_name": "Jane Doe", "email": "j@x.com",
                            "phone": "555", "city_state": "Remote (US)",
                            "linkedin_url": "https://li/jane", "portfolio_url": "https://j.dev"}}
    job = {"cover_letter_text": "Dear team", "tailored_resume_path": "data/r.docx"}
    d = build_apply_data(profile, job)
    check(d["first_name"] == "Jane" and d["last_name"] == "Doe", "name split into data")
    check(d["email"] == "j@x.com" and d["website"] == "https://j.dev", "contact mapped")
    check(d["cover_letter"] == "Dear team" and d["resume_path"] == "data/r.docx", "job fields mapped")

    print("== workday_skills (ITEM-16: taxonomy list, JD-required first) ==")
    wd_profile = {"skills": {
        "hard_skills": [{"name": "Java"}, {"name": "C#"}, {"name": "AWS"},
                        {"name": "Oracle PL/SQL"}, {"name": "Docker"}],
        "certifications": [{"name": "CompTIA Security+"}],
    }}
    table = [
        {"term": "Oracle PL/SQL", "category": "hard_skill", "required": True,
         "variants": []},
        {"term": "Amazon Web Services (AWS)", "category": "hard_skill",
         "required": True, "variants": ["AWS"]},
        {"term": "Kubernetes", "category": "hard_skill", "required": True,
         "variants": ["K8s"]},
        {"term": "JavaScript", "category": "hard_skill", "required": False,
         "variants": []},
        {"term": "Docker", "category": "hard_skill", "required": False,
         "variants": []},
    ]
    wd = workday_skills(wd_profile, table)
    check(wd[:2] == ["Oracle PL/SQL", "AWS"],
          f"JD-required matches first, in table order ({wd})")
    check(wd[2] == "Docker", f"JD-preferred match next ({wd})")
    check("Kubernetes" not in wd, "JD-required term absent from profile is NOT added")
    check("Java" in wd and wd.index("Java") > wd.index("Docker"),
          "unmatched profile skills appended after JD matches")
    check(wd[-1] == "CompTIA Security+", "certifications appended last")
    check(len(wd) == len(set(s.lower() for s in wd)), "no duplicates")
    # 'JavaScript' preferred term must not pull in profile 'Java' (boundary).
    check(wd.index("Java") > wd.index("Docker"),
          "'JavaScript' does not rank 'Java' as a JD match")

    wd2 = workday_skills(wd_profile, None)
    check(wd2[:5] == ["Java", "C#", "AWS", "Oracle PL/SQL", "Docker"]
          and wd2[-1] == "CompTIA Security+",
          "no keyword table -> profile order + certs")

    print("\nALL APPLY-MATCHING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
