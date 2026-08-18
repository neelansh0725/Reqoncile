"""BM25 lexical retrieval (T026a).

Dense embeddings fail on a specific, repeatable shape: a chunk dominated by
proper nouns with the meaning carried by one buried verb.

    requirement: "Presentation skills"
    chunk:       "Hackathons: Smart India Hackathon (SIH) 2025 - Built and
                  pitched the SafeEdu disaster safety platform to a panel of
                  judges; CodeClash 2.0 - Built and presented the Save & Serve
                  food donation platform."

A single averaged vector cannot hold both the named entities and `pitched` /
`presented`, so the chunk sits at rank 38 of 45 under three different
embedding models (see `docs/classifier_eval.md`). A term-matching retriever
finds it immediately -- *if* `presentation`, `presented` and `presenting`
collapse to the same term. That makes stemming the load-bearing part here,
not BM25 itself.

Implemented directly rather than pulled in as a dependency: it is ~80 lines,
the stemmer needs to be tuned against the failures we actually have, and the
whole point is that it stays inspectable.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import threading

import snowballstemmer

# Keep +/# so "C++" and "C#" survive as distinct terms.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*")


# Terms that carry no retrieval signal in a resume/JD context.
_STOPWORDS = frozenset("""
a an the and or of to in on for with using use used is are be been was were
as at by from that this it its their there here we you your our my i they
them he she his her not no than then so such into over under about across
each any all both few more most other some own same very can will just do
does did done have has had having would should could may might must
experience experienced strong good excellent solid proven demonstrated
ability able skills skill knowledge familiarity familiar proficiency
proficient understanding work working works
""".split())


# One stemmer per thread. Snowball's stemmer object carries per-word parsing
# state on the instance, so a single shared instance corrupts under concurrent
# use -- classification fans out across threads (T034) and every requirement
# tokenises, so this path is genuinely concurrent. Measured: hammering one
# shared instance from 8 threads over this corpus produced 24 IndexErrors,
# while single-threaded it produced none. See D6.
_thread_state = threading.local()


def _get_stemmer() -> "snowballstemmer.stemmer":
    stemmer = getattr(_thread_state, "stemmer", None)
    if stemmer is None:
        stemmer = _thread_state.stemmer = snowballstemmer.stemmer("english")
    return stemmer


def stem(word: str) -> str:
    """Snowball (Porter2) stem.

    A hand-rolled single-pass suffix stripper was tried first and collapsed
    only 3 of 9 target pairs -- it cannot reconcile `orchestration` with
    `orchestrated`, which needs Porter's multi-step ATION->ATE->'' chain.
    Snowball gets 7 of 9 and over-stems none of the technical terms that
    matter here (java/javascript, react/reactive, docker/dock all stay
    distinct). Small pure-Python dependency; worth it over a bad reimplementation.
    """
    return _get_stemmer().stemWord(word)


def tokenize(text: str) -> list[str]:
    """Lowercase, split, drop stopwords, stem."""
    return [
        stem(token)
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


@dataclass
class BM25Index:
    """Okapi BM25 over a fixed set of documents."""

    k1: float = 1.5
    b: float = 0.75

    doc_ids: list[str] = field(default_factory=list)
    _freqs: list[Counter] = field(default_factory=list)
    _lengths: list[int] = field(default_factory=list)
    _doc_freq: Counter = field(default_factory=Counter)
    _avg_len: float = 0.0

    @classmethod
    def build(cls, doc_ids: Sequence[str], texts: Sequence[str]) -> "BM25Index":
        index = cls()
        index.doc_ids = list(doc_ids)
        for text in texts:
            tokens = tokenize(text)
            counts = Counter(tokens)
            index._freqs.append(counts)
            index._lengths.append(len(tokens))
            index._doc_freq.update(counts.keys())
        index._avg_len = (
            sum(index._lengths) / len(index._lengths) if index._lengths else 0.0
        )
        return index

    def _idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self._doc_freq.get(term, 0)
        # +1 keeps the value positive for terms present in every document,
        # which would otherwise score zero or negative.
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return up to k (doc_id, score), best first. Zero-scoring docs are
        omitted -- an unmatched document is not a weak match, it is no match."""
        terms = tokenize(query)
        if not terms or not self.doc_ids:
            return []

        scored: list[tuple[str, float]] = []
        for position, doc_id in enumerate(self.doc_ids):
            freqs = self._freqs[position]
            length = self._lengths[position]
            score = 0.0
            for term in terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                denominator = tf + self.k1 * (
                    1.0 - self.b + self.b * (length / (self._avg_len or 1.0))
                )
                score += self._idf(term) * (tf * (self.k1 + 1.0)) / denominator
            if score > 0.0:
                scored.append((doc_id, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[str]],
    k: int = 60,
) -> list[str]:
    """Fuse ranked id lists by Reciprocal Rank Fusion.

    RRF is used rather than blending the raw scores because cosine similarity
    and BM25 are on incomparable scales -- normalising them would invent a
    weighting we have no basis for. RRF only reads rank position, so a chunk
    that both retrievers rank highly wins, and a chunk either one ranks first
    still surfaces. `k=60` is the standard damping constant.
    """
    totals: dict[str, float] = {}
    for ranking in rankings:
        for position, doc_id in enumerate(ranking, start=1):
            totals[doc_id] = totals.get(doc_id, 0.0) + 1.0 / (k + position)
    return [doc_id for doc_id, _ in sorted(totals.items(), key=lambda p: -p[1])]
