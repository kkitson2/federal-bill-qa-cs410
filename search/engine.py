"""Public search entry point: a question in, ranked sections with text and citations out."""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import asdict, dataclass

from . import lexical
from .corpus import Section, load_sections
from .text import tokenize

DEFAULT_METHOD = "hybrid"
# Keyword methods (course retrieval models), then embeddings, then the fusion of bm25 + semantic.
LEXICAL_METHODS = ("tfidf", "bm25", "bm25plus", "ql_jm", "ql_dirichlet", "bm25_prf")
METHODS = LEXICAL_METHODS + ("semantic", "hybrid")
RRF_K = 60  # standard constant from Cormack, Clarke & Buettcher (SIGIR 2009)
MAX_K = 100
PRF_DOCS = 5  # pseudo-relevant documents for Rocchio feedback


@dataclass(frozen=True)
class SearchResult:
    rank: int
    score: float
    method: str
    section_id: str
    package_id: str
    bill: str
    version_label: str
    number: str
    heading: str
    title: str
    citation: str
    source_url: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def bm25_document(section: Section, heading_weight: int = 2, include_title: bool = False) -> str:
    """Text indexed for keyword search. Headings are short and on-topic, so they count extra (a
    simple form of BM25F field weighting: field term counts are combined before scoring)."""
    parts = [section.heading] * heading_weight + [section.text]
    if include_title:
        parts.insert(0, section.title)
    return "\n".join(parts)


def ranking(scores: dict[int, float]) -> list[int]:
    """Document indexes by descending score; ties broken by corpus order so results are deterministic."""
    return sorted(scores, key=lambda i: (-scores[i], i))


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """score(d) = sum over rankings containing d of 1 / (k + rank of d), ranks starting at 1."""
    fused: dict[int, float] = {}
    for order in rankings:
        for rank, i in enumerate(order, start=1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank)
    return fused


class Searcher:
    """Builds the keyword index once; `search()` is then cheap to call repeatedly, from any thread.

    The semantic index (embedding model + chunk vectors) loads on the first semantic/hybrid query,
    or up front with `warm_up()`.
    """

    # include_title=False: the bill title is identical for every section of a bill, so it adds
    # bill-level noise rather than telling sections apart.
    def __init__(self, sections: list[Section], heading_weight: int = 2, include_title: bool = False,
                 model: str | None = None):
        if not sections:
            raise ValueError("No sections to index")
        self.sections = sections
        docs = [tokenize(bm25_document(s, heading_weight, include_title)) for s in sections]
        self.index = lexical.InvertedIndex(docs)
        self.docs_tf = [Counter(d) for d in docs]
        self.model = model
        self._semantic = None
        self._lock = threading.Lock()

    @classmethod
    def from_database(cls, url: str | None = None, **options) -> "Searcher":
        return cls(load_sections(url), **options)

    @property
    def semantic(self):
        if self._semantic is None:
            with self._lock:  # load the model only once even if several requests arrive together
                if self._semantic is None:
                    try:
                        from .semantic import DEFAULT_MODEL, SemanticIndex
                    except ImportError as error:
                        raise RuntimeError("Semantic search needs extra packages: "
                                           "run `uv sync --no-editable --group search`") from error
                    self._semantic = SemanticIndex(self.sections, self.model or DEFAULT_MODEL)
        return self._semantic

    def warm_up(self) -> None:
        """Load the embedding model now instead of on the first semantic/hybrid query."""
        self.semantic  # noqa: B018

    def scores(self, question: str, method: str) -> dict[int, float]:
        """{section index: score}. Keyword methods include only sections sharing a query term."""
        if method == "semantic":
            return dict(enumerate(self.semantic.scores(question)))
        if method == "hybrid":
            keyword = ranking(self.scores(question, "bm25"))
            meaning = ranking(self.scores(question, "semantic"))
            return reciprocal_rank_fusion([keyword, meaning])
        q = lexical.query_vector(tokenize(question))
        if method == "tfidf":
            return lexical.pivoted_tfidf(self.index, q)
        if method == "bm25":
            return lexical.bm25(self.index, q)
        if method == "bm25plus":
            return lexical.bm25(self.index, q, delta=1.0)
        if method == "ql_jm":
            return lexical.ql_jelinek_mercer(self.index, q)
        if method == "ql_dirichlet":
            return lexical.ql_dirichlet(self.index, q)
        if method == "bm25_prf":
            first = ranking(lexical.bm25(self.index, q))[:PRF_DOCS]
            return lexical.bm25(self.index, lexical.rocchio_expand(self.index, self.docs_tf, q, first))
        raise ValueError(f"Unknown method {method!r}; choose from {', '.join(METHODS)}")

    def search(self, question: str, k: int = 10, method: str = DEFAULT_METHOD) -> list[SearchResult]:
        """Top-k sections for a question. Raises ValueError for an empty question, bad k or method."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
            raise ValueError(f"k must be an integer from 1 to {MAX_K}")
        if method not in METHODS:
            raise ValueError(f"Unknown method {method!r}; choose from {', '.join(METHODS)}")
        scores = self.scores(question.strip(), method)
        results = []
        for i in ranking(scores)[:k]:
            s = self.sections[i]
            results.append(SearchResult(
                rank=len(results) + 1, score=round(float(scores[i]), 6), method=method,
                section_id=s.section_id, package_id=s.package_id, bill=s.bill,
                version_label=s.version_label, number=s.number, heading=s.heading, title=s.title,
                citation=s.citation, source_url=s.source_url, text=s.text,
            ))
        return results
