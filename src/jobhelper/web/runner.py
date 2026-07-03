"""Run manager: launches run_daily.py as a child process and captures output.

One run at a time (guarded by a lock). Output lines land in a bounded
in-memory buffer for SSE streaming/replay and are mirrored to data/logs/
for post-hoc inspection. Persistent run history/counters stay in the
run_log table, which the pipeline itself writes — nothing is duplicated.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..util import DATA_DIR, ROOT, now_iso

LOG_DIR = DATA_DIR / "logs"
BUFFER_LINES = 4000


class RunManager:
    """Owns the lifecycle of a single run_daily.py child process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wakeup = threading.Condition(self._lock)
        self._buf: deque[tuple[int, str]] = deque(maxlen=BUFFER_LINES)
        self._seq = 0
        self._state = "idle"
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._exit_code: int | None = None
        self._use_cache = False
        self._log_path: Path | None = None

    # Separated out so tests can substitute a cheap stub process.
    def command(self, use_cache: bool) -> list[str]:
        cmd = [sys.executable, str(ROOT / "run_daily.py")]
        if use_cache:
            cmd.append("--use-cache")
        return cmd

    def start(self, use_cache: bool = False) -> bool:
        """Spawn the daily run. Returns False if one is already in progress."""
        with self._lock:
            if self._state == "running":
                return False
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            log_path = LOG_DIR / f"ui-run-{stamp}.log"
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            kwargs: dict[str, Any] = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(
                self.command(use_cache),
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **kwargs,
            )
            self._buf.clear()
            self._seq = 0
            self._state = "running"
            self._started_at = now_iso()
            self._finished_at = None
            self._exit_code = None
            self._use_cache = use_cache
            self._log_path = log_path
            threading.Thread(
                target=self._pump, args=(proc, log_path), daemon=True
            ).start()
            return True

    def _pump(self, proc: subprocess.Popen[str], log_path: Path) -> None:
        assert proc.stdout is not None
        with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                log_file.write(line + "\n")
                log_file.flush()
                with self._wakeup:
                    self._seq += 1
                    self._buf.append((self._seq, line))
                    self._wakeup.notify_all()
        code = proc.wait()
        with self._wakeup:
            self._exit_code = code
            self._finished_at = now_iso()
            self._state = "idle"
            self._wakeup.notify_all()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "exit_code": self._exit_code,
                "use_cache": self._use_cache,
                "log_path": str(self._log_path) if self._log_path else None,
                "line_count": self._seq,
            }

    def stream(self, after: int = 0) -> Iterator[tuple[str, int, str]]:
        """Yield ('line', seq, text) events past `after`, then ('done', seq, '').

        Blocking generator — serve it with a sync StreamingResponse so
        Starlette iterates it in a threadpool. Emits ('ping', ...) heartbeats
        while idle so the connection stays alive.
        """
        last = after
        while True:
            with self._wakeup:
                pending = [(s, t) for s, t in self._buf if s > last]
                running = self._state == "running"
                if not pending and running:
                    self._wakeup.wait(timeout=15.0)
                    pending = [(s, t) for s, t in self._buf if s > last]
                    running = self._state == "running"
            for seq, text in pending:
                last = seq
                yield ("line", seq, text)
            if not running and not pending:
                yield ("done", last, "")
                return
            if not pending:
                yield ("ping", last, "")


MANAGER = RunManager()
