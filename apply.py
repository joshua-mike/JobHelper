"""Assisted apply — open a proposal's careers form, auto-fill it, you submit.

    python apply.py 229          # assist on job id 229
    python apply.py --next       # assist on the highest-scored pending job
    python apply.py 229 --headless   # fill + screenshot only (no wait); for testing

The browser fills standard fields and attaches your tailored résumé, then STOPS.
You review every field, answer screening questions, and click Submit yourself.
Nothing is ever submitted automatically.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobhelper.apply.runner import assisted_apply, pick_next  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="JobHelper assisted apply")
    parser.add_argument("job_id", nargs="?", type=int, help="Job id to apply to.")
    parser.add_argument("--next", action="store_true",
                        help="Use the highest-scored pending job.")
    parser.add_argument("--headless", action="store_true",
                        help="Fill + screenshot without waiting (testing).")
    args = parser.parse_args()

    job_id = args.job_id
    if args.next or job_id is None:
        job_id = pick_next()
        if job_id is None:
            print("No pending jobs to apply to. Run `python run_daily.py` first.")
            return 1
        print(f"Selected highest-scored pending job: id={job_id}")

    assisted_apply(job_id, headless=args.headless)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
