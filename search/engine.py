"""Public search entry point: a question in, ranked sections with text and citations out."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .bm25 import BM25
from .corpus import Section, load_sections
from .text import tokenize

# bm25plus is BM25+ (delta=1); hybrid fuses bm25 and semantic with reciprocal rank fusion.
METHODS = ("bm25", "bm25plus", "semantic", "hybrid")
RRF_K = 60  # standard constant from Cormack, Clarke & Buettcher (SIGIR 2009)


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
    """Text indexed for BM25. Headings are short and on-topic, so they count extra (a simple form of
    BM25F field weighting)."""
    parts = [section.heading] * heading_weight + [section.text]
    if include_title:
        parts.insert(0, section.title)
    return "\n".join(parts)


def ranking(scores: list[float]) -> list[int]:
    """Indexes by descending score; ties broken by corpus order so results are deterministic."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> list[float]:
    """score(d) = sum over rankings of 1 / (k + rank of d), with ranks starting at 1."""
    n = max((max(r) for r in rankings if r), default=-1) + 1
    fused = [0.0] * n
    for order in rankings:
        for rank, i in enumerate(order, start=1):
            fused[i] += 1.0 / (k + rank)
    return fused


class Searcher:
    """Builds the keyword index once; `search()` is then cheap to call repeatedly.

    The semantic index (embedding model + chunk vectors) loads on first semantic/hybrid query.
    """

    # include_title=False: the bill title is identical for every section of a bill, so it adds
    # bill-level noise rather than telling sections apart (it lowered nDCG in a quick check).
    def __init__(self, sections: list[Section], heading_weight: int = 2, include_title: bool = False,
                 k1: float = 1.2, b: float = 0.75, model: str | None = None):
        if not sections:
            raise ValueError("No sections to index")
        self.sections = sections
        docs = [tokenize(bm25_document(s, heading_weight, include_title)) for s in sections]
        self.bm25 = BM25(docs, k1=k1, b=b)
        self.bm25plus = BM25(docs, k1=k1, b=b, delta=1.0)
        self.model = model
        self._semantic = None

    @classmethod
    def from_database(cls, url: str | None = None, **options) -> "Searcher":
        return cls(load_sections(url), **options)

    @property
    def semantic(self):
        if self._semantic is None:
            from .semantic import DEFAULT_MODEL, SemanticIndex
            self._semantic = SemanticIndex(self.sections, self.model or DEFAULT_MODEL)
        return self._semantic

    def scores(self, question: str, method: str) -> list[float]:
        """One score per section (same order as self.sections); 0 or less means no keyword match."""
        if method == "bm25":
            return self.bm25.scores(tokenize(question))
        if method == "bm25plus":
            return self.bm25plus.scores(tokenize(question))
        if method == "semantic":
            return self.semantic.scores(question)
        if method == "hybrid":
            keyword = self.bm25.scores(tokenize(question))
            # Only sections with a keyword match enter the keyword ranking; all enter the semantic one.
            keyword_order = [i for i in ranking(keyword) if keyword[i] > 0]
            fused = reciprocal_rank_fusion([keyword_order, ranking(self.semantic.scores(question))])
            return fused + [0.0] * (len(self.sections) - len(fused))
        raise ValueError(f"Unknown method {method!r}; choose from {', '.join(METHODS)}")

    def search(self, question: str, k: int = 10, method: str = "hybrid") -> list[SearchResult]:
        scores = self.scores(question, method)
        keyword_only = method in ("bm25", "bm25plus")
        results = []
        for i in ranking(scores)[:k]:
            if keyword_only and scores[i] <= 0:
                break  # no query word in this section or any later one
            s = self.sections[i]
            results.append(SearchResult(
                rank=len(results) + 1, score=round(scores[i], 6), method=method,
                section_id=s.section_id, package_id=s.package_id, bill=s.bill,
                version_label=s.version_label, number=s.number, heading=s.heading, title=s.title,
                citation=s.citation, source_url=s.source_url, text=s.text,
            ))
        return results
