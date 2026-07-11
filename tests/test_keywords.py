"""Offline tests for the ATS keyword matcher + coverage (ITEM-8).

The boundary-aware matcher is the load-bearing detail: naive \\b regex never
matches C#, .NET, or C++ (#, +, . are non-word chars). Josh's profile is
C#/.NET-heavy, so the golden test runs against the REAL config/profile.yaml
hard skills in an actually-rendered DOCX.

Run:  python tests/test_keywords.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docx import Document  # noqa: E402

from jobhelper.config import load_profile  # noqa: E402
from jobhelper.tailor import keywords as K  # noqa: E402
from jobhelper.tailor.resume_docx import build_resume  # noqa: E402
from jobhelper.tailor.tailor import passthrough_resume  # noqa: E402


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def hits(text, term, variants=()):
    return K.count_hits(text, term, list(variants))


def test_boundary_matcher_specials():
    print("== boundary-aware matcher: C# / .NET / C++ ==")
    # Adjacent to spaces, commas, periods, line ends.
    check(hits("C#, .NET, C++", "C#") == 1, "C# matches before comma")
    check(hits("C#, .NET, C++", ".NET") == 1, ".NET matches between commas")
    check(hits("C#, .NET, C++", "C++") == 1, "C++ matches at line end")
    check(hits("uses C# daily", "C#") == 1, "C# matches surrounded by spaces")
    check(hits("built on .NET.", ".NET") == 1, ".NET matches before period")
    check(hits("ships C++\nnext line", "C++") == 1, "C++ matches before newline")
    check(hits("in C#.", "C#") == 1, "C# matches before period at sentence end")
    check(hits("(C#)", "C#") == 1, "C# matches inside parens")
    check(hits("C#", "C#") == 1, "C# matches as whole string")


def test_boundary_matcher_negatives():
    print("== boundary-aware matcher: negatives ==")
    check(hits("JavaScript", "Java") == 0, "Java does NOT match inside JavaScript")
    check(hits("C##", "C#") == 0, "C# does NOT match inside C##")
    check(hits("C+++", "C++") == 0, "C++ does NOT match inside C+++")
    check(hits("ASP.NET", ".NET") == 0,
          ".NET does NOT match inside ASP.NET (accepted behavior)")
    check(hits("hyperscaler", "scala") == 0, "no mid-word matches for plain terms")


def test_matcher_case_and_counts():
    print("== matcher: case-insensitive, counts, variants ==")
    check(hits("c# and C# and c#", "C#") == 3, "case-insensitive count of 3")
    check(hits("AWS work", "aws") == 1, "term case ignored")
    text = "Amazon Web Services (AWS) plus more AWS work"
    check(hits(text, "AWS") == 2, "AWS counted twice (bare + parenthesized)")
    check(hits("RESTful services here", "REST API", ["RESTful services"]) == 1,
          "variant counts when base term absent")


def test_coverage():
    print("== coverage ==")
    table = [
        {"term": "C#", "category": "hard_skill", "required": True, "variants": []},
        {"term": "Kubernetes", "category": "hard_skill", "required": True,
         "variants": ["K8s"]},
        {"term": "Agile", "category": "method", "required": False, "variants": []},
    ]
    cov = K.coverage("Deep C# experience; Agile teams.", table)
    check(cov["required_total"] == 2, "required_total counts only required terms")
    check(cov["required_present"] == 1, "C# present, Kubernetes missing")
    check(cov["missing"] == ["Kubernetes"], "missing lists absent required term")
    check(cov["hits"]["C#"] == 1 and cov["hits"]["Agile"] == 1,
          "per-term hit counts recorded")
    cov2 = K.coverage("We run K8s in prod with C#.", table)
    check(cov2["required_present"] == 2, "variant hit counts as presence")
    check(cov2["missing"] == [], "no missing when variants cover")


def test_golden_profile_skills():
    print("== GOLDEN: every real profile hard skill matches in rendered DOCX ==")
    profile = load_profile()
    content = passthrough_resume(profile)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "golden.docx"
        build_resume(content, path)
        text = "\n".join(p.text for p in Document(str(path)).paragraphs)
    for skill in content["skills"]:
        check(hits(text, skill) >= 1, f"profile skill matches rendered text: {skill}")


class FakeLLM:
    available = True

    def __init__(self, result):
        self._result = result

    def structured(self, system, user, *, schema, tool_name, model, max_tokens=1024):
        self.last_user = user
        return self._result


class NoLLM:
    available = False

    def structured(self, *a, **k):
        raise AssertionError("must not be called when unavailable")


def test_extract_keywords():
    print("== extract_keywords ==")
    canned = {"keywords": [
        {"term": "C#", "category": "hard_skill", "required": True,
         "variants": ["C sharp"]},
        {"term": "  ", "category": "hard_skill", "required": True, "variants": []},
        {"term": "Agile", "category": "method", "required": False,
         "variants": ["Scrum", ""]},
    ]}
    llm = FakeLLM(canned)
    job = {"title": "Dev", "company": "Acme", "description_clean": "x" * 20000}
    table = K.extract_keywords(llm, "fake-model", job)
    check(table is not None and len(table) == 2, "blank-term entry dropped")
    check(table[0]["term"] == "C#" and table[0]["required"] is True,
          "term + required preserved")
    check(table[1]["variants"] == ["Scrum"], "empty variant strings dropped")
    check(len(llm.last_user) < 16000, "JD capped at 15k chars in prompt")

    check(K.extract_keywords(FakeLLM(None), "fake-model", job) is None,
          "LLM failure -> None (soft-fail)")
    check(K.extract_keywords(FakeLLM({"keywords": "garbage"}), "fake-model", job)
          is None, "non-list keywords -> None")
    check(K.extract_keywords(NoLLM(), "fake-model", job) is None,
          "no-LLM mode -> None without calling")


def main() -> int:
    test_boundary_matcher_specials()
    test_boundary_matcher_negatives()
    test_matcher_case_and_counts()
    test_coverage()
    test_golden_profile_skills()
    test_extract_keywords()
    print("\nALL KEYWORD CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
