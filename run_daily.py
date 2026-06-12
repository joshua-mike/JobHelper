"""Entry point for the daily run (call this from Windows Task Scheduler).

    python run_daily.py            # fetch fresh, produce today's digest
    python run_daily.py --use-cache  # reuse cached API responses (dev/debug)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make src/ importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobhelper.pipeline import run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="JobHelper daily run")
    parser.add_argument("--use-cache", action="store_true",
                        help="Reuse cached HTTP responses instead of fetching fresh.")
    args = parser.parse_args()

    summary = run(use_cache=args.use_cache)
    print("\n" + "=" * 60)
    print(f"  Proposed {summary['proposed']} jobs "
          f"(sourced {summary['sourced']}, {summary['new_jobs']} new, "
          f"{summary['filtered']} filtered)")
    print(f"  Scoring: {summary['scorer_mode']}   AI tailoring: "
          f"{'on' if summary['llm_on'] else 'off'}")
    print(f"  Digest:  {summary['digest']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
