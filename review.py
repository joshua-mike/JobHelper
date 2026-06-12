"""Launch the local review page.

    python review.py            # serves http://127.0.0.1:8765 and opens a browser

Review today's proposals, then Approve / Mark-applied / Skip. Nothing is ever
submitted for you — this only tracks your own manual applications.
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn  # noqa: E402

from jobhelper.review.app import app  # noqa: E402

HOST, PORT = "127.0.0.1", 8765


def main() -> int:
    url = f"http://{HOST}:{PORT}"
    print(f"JobHelper review page → {url}  (Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
