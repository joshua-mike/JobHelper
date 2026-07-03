"""Launch the JobHelper dashboard (metrics at a glance + run control).

    python run_ui.py               # serves http://127.0.0.1:8787 and opens a browser
    python run_ui.py --no-browser  # just serve (scheduled tasks, tooling)

Serves the built frontend from web/dist plus the JSON API under /api/*.
The review page (review.py, port 8765) is unchanged and linked from the UI.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn  # noqa: E402

from jobhelper.web.app import app  # noqa: E402

HOST, PORT = "127.0.0.1", 8787


def main() -> int:
    parser = argparse.ArgumentParser(description="JobHelper dashboard UI")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open a browser tab after starting.")
    args = parser.parse_args()

    url = f"http://{HOST}:{PORT}"
    print(f"JobHelper dashboard → {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
