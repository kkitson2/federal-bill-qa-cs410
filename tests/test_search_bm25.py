"""Group 2 search tests: no database needed (toy corpus)."""

from pathlib import Path

import pytest

from search import Searcher, Section
from search.__main__ import read_questions
from search.bm25 import BM25
from search.text import stem, tokenize


def section(sid, heading, text, title="A bill"):
    return Section(section_id=sid, package_id="PKG", bill="HR 1", version_label="Introduced",
                   number="1.", heading=heading, title=title, text=text,
                   citation=f"HR 1, section {sid}", source_url="https://example.gov", record_type="section")


CORPUS = [
    section("a", "Data brokers", "A data broker shall register with the Commission each year."),
    section("b", "Deletion of information", "A consumer may request that a bank delete personal information."),
    section("c", "Short title", "This Act may be cited as the Example Act."),
]


def test_stemming_matches_word_forms():
    assert stem("deletion") == stem("delete") == stem("deleted")
    assert stem("brokers") == stem("broker")
    assert stem("act") == "act"  # short words untouched


def test_tokenize_drops_stopwords_and_punctuation():
    assert tokenize("Can I make my bank delete it?") == ["make", "bank", "delet"]


def test_bm25_prefers_matching_and_rarer_terms():
    docs = [["bank", "delet"], ["bank"], ["other"]]
    scores = BM25(docs).scores(["bank", "delet"])
    assert scores[0] > scores[1] > scores[2] == 0


def test_search_returns_ranked_results_with_citations():
    results = Searcher(CORPUS).search("Do data brokers have to register?", k=2, method="bm25")
    assert [r.section_id for r in results][0] == "a"
    top = results[0]
    assert top.rank == 1 and top.citation == "HR 1, section a" and top.source_url
    assert "register" in top.text and top.to_dict()["heading"] == "Data brokers"


def test_search_omits_zero_score_and_respects_k():
    searcher = Searcher(CORPUS)
    assert [r.section_id for r in searcher.search("bank deletion", k=10, method="bm25")] == ["b"]
    assert searcher.search("zebra", k=10, method="bm25") == []
    assert len(searcher.search("act data bank", k=1, method="bm25")) == 1


def test_ties_are_deterministic():
    twins = [section("x", "Twin", "twin words"), section("y", "Twin", "twin words")]
    assert [r.section_id for r in Searcher(twins).search("twin", k=2, method="bm25")] == ["x", "y"]


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        Searcher(CORPUS).search("bank", method="nope")


def test_read_questions_dedupes_label_rows():
    questions = read_questions(Path(__file__).parents[1] / "eval/labels.csv")
    assert len(questions) == 30 and questions[0][0] == "Q01"


def test_bm25plus_gives_matched_terms_a_floor():
    docs = [["bank"] + ["filler"] * 500, ["other"]]
    plain, plus = BM25(docs).scores(["bank"]), BM25(docs, delta=1.0).scores(["bank"])
    assert plus[0] > plain[0] and plus[1] == plain[1] == 0


def test_hybrid_without_model_uses_fusion(monkeypatch):
    searcher = Searcher(CORPUS)

    class FakeSemantic:  # prefers section "c", BM25 prefers "b"
        def scores(self, question):
            return [0.1, 0.2, 0.9]

    searcher._semantic = FakeSemantic()
    assert searcher.search("bank deletion", k=3, method="semantic")[0].section_id == "c"
    hybrid = [r.section_id for r in searcher.search("bank deletion", k=3, method="hybrid")]
    assert set(hybrid[:2]) == {"b", "c"}  # each is first in one list, so both beat "a"
