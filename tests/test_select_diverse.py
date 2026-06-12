"""Offline test for the per-company diversity cap in proposal selection.
Run:  python tests/test_select_diverse.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.pipeline import _select_diverse


def rows(*pairs):
    # pairs: (id, company) already in best-first order
    return [{"id": i, "company": c} for i, c in pairs]


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    print("== cap=1 spreads across companies ==")
    cands = rows((1, "MeridianLink"), (2, "MeridianLink"), (3, "MeridianLink"),
                 (4, "MeridianLink"), (5, "Delinea"), (6, "BHG"), (7, "PerfectServe"))
    sel = _select_diverse(cands, target=4, max_per_company=1)
    companies = [r["company"] for r in sel]
    check(len(sel) == 4, "returns 4")
    check(companies == ["MeridianLink", "Delinea", "BHG", "PerfectServe"],
          f"one per company, best-first: {companies}")

    print("== cap=2 allows two from one company ==")
    sel2 = _select_diverse(cands, target=4, max_per_company=2)
    c2 = [r["company"] for r in sel2]
    check(c2.count("MeridianLink") == 2, "two MeridianLink allowed")
    check(len(sel2) == 4, "still 4 total")

    print("== pass-2 fills when too few companies ==")
    few = rows((1, "MeridianLink"), (2, "MeridianLink"), (3, "MeridianLink"),
               (4, "Delinea"))
    sel3 = _select_diverse(few, target=4, max_per_company=1)
    check(len(sel3) == 4, "fills to target=4 despite cap")
    # pass1 picks id1 (MeridianLink) + id4 (Delinea); pass2 adds id2, id3
    check([r["id"] for r in sel3][:2] == [1, 4], "diverse picks come first")
    check(set(r["id"] for r in sel3) == {1, 2, 3, 4}, "remainder filled by best-next")

    print("== fewer candidates than target ==")
    sel4 = _select_diverse(rows((1, "A"), (2, "B")), target=4, max_per_company=1)
    check(len(sel4) == 2, "returns all when fewer than target")

    print("\nALL SELECT-DIVERSE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
