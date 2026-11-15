"""Okapi BM25 (and BM25+) over pre-tokenized documents."""

from __future__ import annotations

import math
from collections import Counter


class BM25:
    """delta=0 is classic BM25. delta>0 is BM25+ (Lv & Zhai, 2011; CS410 Week 2): every matched
    term earns at least a small bonus, so very long sections are not over-penalized."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75, delta: float = 0.0):
        self.k1, self.b, self.delta = k1, b, delta
        self.tf = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avgdl = sum(self.lengths) / len(docs) if docs else 0.0
        df = Counter(term for d in self.tf for term in d)
        n = len(docs)
        # Lucene-style IDF: always positive, even for very common terms.
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        terms = [t for t in query if t in self.idf]
        out = []
        for tf, length in zip(self.tf, self.lengths):
            norm = self.k1 * (1 - self.b + self.b * length / self.avgdl) if self.avgdl else self.k1
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * (f * (self.k1 + 1) / (f + norm) + self.delta)
            out.append(s)
        return out
