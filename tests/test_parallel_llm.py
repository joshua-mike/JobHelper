"""The judge runs its Claude calls a few at a time (pipeline._judge_all).

Covers what going concurrent could break: results must still line up with the
shortlist, one failed call must not cost the others, and the first call must
finish alone so the rest read the prompt cache it writes instead of each
paying to write it. No network — a fake judge stands in.
Run:  python tests/test_parallel_llm.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobhelper.pipeline import _judge_all


class FakeJudge:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.lock = threading.Lock()
        self.active = self.peak = self.finished = 0
        self.started_before_first_finished = 0

    def score(self, job: dict) -> dict:
        with self.lock:
            if job["id"] != 1 and self.finished == 0:
                self.started_before_first_finished += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
            self.finished += 1
        if job["id"] in self.fail_ids:
            raise RuntimeError("boom")
        return {"fit_score": job["id"]}


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        raise AssertionError(msg)


def test_judge_all():
    print("== judge: concurrent calls, results in shortlist order ==")
    shortlist = [{"id": n} for n in range(1, 8)]
    judge = FakeJudge(fail_ids={3})
    results = _judge_all(judge, shortlist)
    want = [None if n == 3 else {"fit_score": n} for n in range(1, 8)]
    check(results == want, f"one result per job, in order, None for the failed call ({results})")
    check(judge.started_before_first_finished == 0,
          "the first call finishes alone (it writes the prompt cache)")
    check(judge.peak > 1, f"the rest overlap (peak {judge.peak} at once)")

    print("== judge: edge cases ==")
    check(_judge_all(FakeJudge(), []) == [], "empty shortlist")
    check(_judge_all(FakeJudge(), [{"id": 1}]) == [{"fit_score": 1}], "a single job")
    check(_judge_all(FakeJudge(fail_ids={1}), [{"id": 1}, {"id": 2}])
          == [None, {"fit_score": 2}], "a failed first call doesn't stop the rest")


if __name__ == "__main__":
    test_judge_all()
    print("\nALL PARALLEL-LLM CHECKS PASSED")
