"""Public search entry point: a question in, ranked sections with text and citations out."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .bm25 import BM25
from .corpus import Section, load_sections
from .text import tokenize

METHODS = ("bm25",)


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


def bm25_document(section: Section, heading_weight: int = 2, include_title: bool = True) -> str:
    """Text indexed for BM25. Headings are short and on-topic, so they count extra."""
    parts = [section.heading] * heading_weight + [section.text]
    if include_title:
        parts.insert(0, section.title)
    return "\n".join(parts)


class Searcher:
    """Builds the indexes once; `search()` is then cheap to call repeatedly."""

    # include_title=False: the bill title is identical for every section of a bill, so it adds
    # bill-level noise rather than telling sections apart (it lowered nDCG in a quick check).
    def __init__(self, sections: list[Section], heading_weight: int = 2, include_title: bool = False,
                 k1: float = 1.2, b: float = 0.75):
        if not sections:
            raise ValueError("No sections to index")
        self.sections = sections
        docs = [tokenize(bm25_document(s, heading_weight, include_title)) for s in sections]
        self.bm25 = BM25(docs, k1=k1, b=b)

    @classmethod
    def from_database(cls, url: str | None = None, **options) -> "Searcher":
        return cls(load_sections(url), **options)

    def search(self, question: str, k: int = 10, method: str = "bm25") -> list[SearchResult]:
        if method not in METHODS:
            raise ValueError(f"Unknown method {method!r}; choose from {', '.join(METHODS)}")
        scores = self.bm25.scores(tokenize(question))
        # Ties broken by corpus order so results are deterministic.
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        results = []
        for i in order[:k]:
            if scores[i] <= 0:
                break
            s = self.sections[i]
            results.append(SearchResult(
                rank=len(results) + 1, score=round(scores[i], 6), method=method,
                section_id=s.section_id, package_id=s.package_id, bill=s.bill,
                version_label=s.version_label, number=s.number, heading=s.heading, title=s.title,
                citation=s.citation, source_url=s.source_url, text=s.text,
            ))
        return results
