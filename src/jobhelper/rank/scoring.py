"""Recall ranking: profile-vs-JD similarity.

Uses sentence-transformers if installed (semantic), otherwise a built-in lexical
cosine over term frequencies (no heavy deps). Either way returns a 0..1 score.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from ..util import get_logger

log = get_logger()

_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]{1,}")
_STOP = {
    "the", "and", "for", "with", "you", "our", "are", "this", "that", "will",
    "have", "from", "your", "all", "can", "but", "not", "who", "his", "her",
    "they", "them", "job", "role", "work", "team", "company", "experience",
    "ability", "including", "must", "should", "would", "across", "within",
}


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")
            if w.lower() not in _STOP and len(w) > 2]


def _lexical_cosine(a: str, b: str) -> float:
    ca, cb = Counter(_tokens(a)), Counter(_tokens(b))
    if not ca or not cb:
        return 0.0
    common = set(ca) & set(cb)
    dot = sum(ca[t] * cb[t] for t in common)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


class Scorer:
    """Profile is fixed for a run; embed it once and reuse.

    prefer: 'auto' (semantic if available, else lexical), 'semantic' (force; warn
    if unavailable), or 'lexical' (skip the heavy model entirely).
    """

    def __init__(self, profile_text: str, prefer: str = "auto") -> None:
        self.profile_text = profile_text
        self._model = None
        self._profile_vec = None
        self._mode = "lexical"
        if prefer == "lexical":
            log.info("Scorer: lexical mode (configured)")
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._profile_vec = self._model.encode(profile_text,
                                                   normalize_embeddings=True)
            self._mode = "semantic"
            log.info("Scorer: semantic mode (sentence-transformers)")
        except Exception as exc:
            level = log.warning if prefer == "semantic" else log.info
            level("Scorer: lexical mode (sentence-transformers unavailable: %s)",
                  type(exc).__name__)

    @property
    def mode(self) -> str:
        return self._mode

    def score(self, jd_text: str) -> float:
        if self._mode == "semantic" and self._model is not None:
            import numpy as np  # noqa: local import; only when semantic
            vec = self._model.encode(jd_text or "", normalize_embeddings=True)
            return float(np.dot(self._profile_vec, vec))
        return _lexical_cosine(self.profile_text, jd_text)
