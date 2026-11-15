"""Keyword retrieval models from CS410 (Zhai & Massung), all over one inverted index.

Every scorer takes a weighted query {term: c(w,q)} and returns {doc index: score} for the documents
that contain at least one query term (the postings it touched), so non-matching documents are
never ranked. Formulas follow the lecture slides:

- Pivoted length normalization VSM (Week 2, Singhal et al. 1996)
    f(q,d) = sum_{w in q∩d} c(w,q) * ln(1+ln(1+c(w,d))) / (1-b+b*|d|/avdl) * log((M+1)/df(w))
- BM25 (Week 2, Robertson & Walker 1994), with the same IDF as the slides
    f(q,d) = sum_{w in q∩d} c(w,q) * (k1+1)c(w,d) / (c(w,d) + k1(1-b+b*|d|/avdl)) * log((M+1)/df(w))
  BM25+ (Week 2, Lv & Zhai 2011) adds delta to the TF part of every matched term.
- Query likelihood, rank-equivalent forms (Week 4)
    JM:        f(q,d) = sum_{w in q∩d} c(w,q) * log(1 + (1-λ)/λ * c(w,d) / (|d| p(w|C)))
    Dirichlet: f(q,d) = sum_{w in q∩d} c(w,q) * log(1 + c(w,d) / (μ p(w|C))) + |q| log(μ / (μ+|d|))
- Rocchio pseudo-relevance feedback (Week 5): q' = α q + β centroid(top-k documents), γ = 0
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict


class InvertedIndex:
    """Postings lists term -> [(doc, c(w,d))] plus the statistics the scorers need (Week 2)."""

    def __init__(self, docs: list[list[str]]):
        if not docs:
            raise ValueError("No documents to index")
        self.n_docs = len(docs)
        self.lengths = [len(d) for d in docs]
        self.total_terms = sum(self.lengths)
        self.avdl = self.total_terms / self.n_docs
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, count in Counter(doc).items():
                postings[term].append((i, count))
        self.postings = dict(postings)
        self.df = {t: len(p) for t, p in self.postings.items()}
        self.cf = {t: sum(c for _, c in p) for t, p in self.postings.items()}

    def idf(self, term: str) -> float:
        return math.log((self.n_docs + 1) / self.df[term])

    def p_collection(self, term: str) -> float:
        return self.cf[term] / self.total_terms

    def known(self, query: dict[str, float]) -> dict[str, float]:
        return {t: w for t, w in query.items() if t in self.postings and w > 0}


def query_vector(tokens: list[str]) -> dict[str, float]:
    """c(w,q) for each query term."""
    return dict(Counter(tokens))


def pivoted_tfidf(index: InvertedIndex, query: dict[str, float], b: float = 0.2) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for term, qw in index.known(query).items():
        idf = index.idf(term)
        for doc, c in index.postings[term]:
            norm = 1 - b + b * index.lengths[doc] / index.avdl
            scores[doc] += qw * math.log(1 + math.log(1 + c)) / norm * idf
    return dict(scores)


def bm25(index: InvertedIndex, query: dict[str, float], k1: float = 1.2, b: float = 0.75,
         delta: float = 0.0) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for term, qw in index.known(query).items():
        idf = index.idf(term)
        for doc, c in index.postings[term]:
            norm = k1 * (1 - b + b * index.lengths[doc] / index.avdl)
            scores[doc] += qw * ((k1 + 1) * c / (c + norm) + delta) * idf
    return dict(scores)


def ql_jelinek_mercer(index: InvertedIndex, query: dict[str, float], lam: float = 0.1) -> dict[int, float]:
    if not 0 < lam < 1:
        raise ValueError("lambda must be in (0, 1)")
    scores: dict[int, float] = defaultdict(float)
    for term, qw in index.known(query).items():
        pc = index.p_collection(term)
        for doc, c in index.postings[term]:
            scores[doc] += qw * math.log(1 + (1 - lam) / lam * c / (index.lengths[doc] * pc))
    return dict(scores)


def ql_dirichlet(index: InvertedIndex, query: dict[str, float], mu: float = 2000.0) -> dict[int, float]:
    if mu <= 0:
        raise ValueError("mu must be positive")
    known = index.known(query)
    scores: dict[int, float] = defaultdict(float)
    for term, qw in known.items():
        pc = index.p_collection(term)
        for doc, c in index.postings[term]:
            scores[doc] += qw * math.log(1 + c / (mu * pc))
    # Document-length term, applied to matched documents only. |q| counts every query term:
    # unseen-in-collection terms contribute the same constant to every document, so dropping them
    # does not change the ranking.
    n = sum(known.values())
    return {doc: s + n * math.log(mu / (mu + index.lengths[doc])) for doc, s in scores.items()}


def rocchio_expand(index: InvertedIndex, docs_tf: list[Counter], query: dict[str, float], top_docs: list[int],
                   alpha: float = 1.0, beta: float = 0.5, n_terms: int = 10) -> dict[str, float]:
    """Pseudo-relevance feedback: treat `top_docs` as relevant (no negatives, γ = 0).

    Query and documents are TF-IDF vectors (ln(1+ln(1+c)) * idf), each L2-normalized so α and β
    compare like with like. Only the `n_terms` strongest new centroid terms are added, which keeps the
    original query terms dominant (the Week 5 caution about feedback drifting off-topic).
    """
    if not top_docs:
        return dict(query)

    def unit(vec: dict[str, float]) -> dict[str, float]:
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    q = unit({t: w * index.idf(t) for t, w in index.known(query).items()})
    centroid: dict[str, float] = defaultdict(float)
    for doc in top_docs:
        vec = unit({t: math.log(1 + math.log(1 + c)) * index.idf(t) for t, c in docs_tf[doc].items()})
        for t, v in vec.items():
            centroid[t] += v / len(top_docs)
    new_terms = sorted((t for t in centroid if t not in q), key=lambda t: (-centroid[t], t))[:n_terms]
    expanded = {t: alpha * w + beta * centroid.get(t, 0.0) for t, w in q.items()}
    for t in new_terms:
        expanded[t] = beta * centroid[t]
    return expanded
