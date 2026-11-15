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

# granite-small-r2 can read whole JDs (8192-token context); on this user's judged
# jobs it agreed with the LLM judge at rho=0.41 vs all-MiniLM-L6-v2's 0.05.
# Symmetric similarity — no query prefix needed. Scores run ~0.85-0.90 for good
# matches (vs MiniLM's ~0.5-0.7); all downstream use is rank-based so the scale
# doesn't matter, but don't mix scores from different models in one pool.
_MODEL_ID = "ibm-granite/granite-embedding-small-english-r2"

# JDs are cut to their first 512 tokens before embedding. CPU cost grows steeply
# with length, and a third of JDs run 1,500-2,700 tokens: the cut makes scoring
# ~2.7x faster. Measured 2026-11-14 on 150 judged jobs, the cut scores agree
# with the LLM judge as well as whole-JD scores do (rho 0.38 vs 0.37) and keep
# 13 of the top 15. The profile is still embedded whole.
_JD_MAX_TOKENS = 512
_BATCH_SIZE = 8  # no faster than one at a time on CPU; just one call

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
            self._model = SentenceTransformer(_MODEL_ID)
            self._profile_vec = self._model.encode(profile_text,
                                                   normalize_embeddings=True)
            # The profile above is embedded whole; JDs are cut to _JD_MAX_TOKENS.
            self._model.max_seq_length = _JD_MAX_TOKENS
            self._mode = "semantic"
            log.info("Scorer: semantic mode (%s)", _MODEL_ID)
        except Exception as exc:
            level = log.warning if prefer == "semantic" else log.info
            level("Scorer: lexical mode (sentence-transformers unavailable: %s)",
                  type(exc).__name__)

    @property
    def mode(self) -> str:
        return self._mode

    def score(self, jd_text: str) -> float:
        return self.score_many([jd_text])[0]

    def score_many(self, jd_texts: list[str]) -> list[float]:
        """Scores for a batch of JDs, in order. One encode call for the lot."""
        if not jd_texts:
            return []
        if self._mode == "semantic" and self._model is not None:
            vecs = self._model.encode([t or "" for t in jd_texts],
                                      batch_size=_BATCH_SIZE,
                                      normalize_embeddings=True)
            return [float(s) for s in vecs @ self._profile_vec]
        return [_lexical_cosine(self.profile_text, t) for t in jd_texts]
