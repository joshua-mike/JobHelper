"""Small shared helpers: paths, logging, HTML->text, hashing, date parsing."""
from __future__ import annotations

import hashlib
import html
import logging
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

# Make console output UTF-8 safe on Windows (default cp1252 crashes on em-dashes,
# arrows, emoji in job titles/logs). Runs once at import, before any logging.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# ---- Paths -------------------------------------------------------------------
# Project root = three parents up from this file (src/jobhelper/util.py).
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RESUME_DIR = DATA_DIR / "resumes"
DIGEST_DIR = DATA_DIR / "digests"
DB_PATH = DATA_DIR / "jobhelper.db"

for _d in (DATA_DIR, CACHE_DIR, RESUME_DIR, DIGEST_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---- Logging -----------------------------------------------------------------
def get_logger(name: str = "jobhelper") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                              datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ---- HTML -> plain text ------------------------------------------------------
_BLOCK_TAGS = {"p", "br", "li", "ul", "ol", "div", "tr", "h1", "h2", "h3",
               "h4", "h5", "h6", "section", "header", "footer"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw: str | None) -> str:
    """Convert an HTML (or HTML-entity-encoded) job description to clean text."""
    if not raw:
        return ""
    # Many ATS feeds double-encode (&lt;p&gt;...). Unescape first so tags parse.
    text = html.unescape(raw)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        text = "".join(parser.parts)
    except Exception:
        # Fall back to a crude tag strip if the parser chokes.
        text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace, keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# ---- Hashing -----------------------------------------------------------------
def stable_hash(*parts: str) -> str:
    """Deterministic short hash used as the dedupe identity for a job."""
    norm = "|".join((p or "").strip().lower() for p in parts)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


# ---- Dates -------------------------------------------------------------------
def parse_date(value) -> datetime | None:
    """Best-effort parse of ISO strings or unix timestamps to aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = s.replace("Z", "+00:00")
    for fmt in (None,):  # try fromisoformat first
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            break
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def age_days(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
