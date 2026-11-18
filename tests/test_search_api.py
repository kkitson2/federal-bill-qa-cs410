"""Group 2: Searcher, fusion, chunking and the HTTP API on a toy corpus (no database, no model download)."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from search import METHODS, Searcher, Section
from search.__main__ import read_questions
from search.engine import RRF_K, ranking, reciprocal_rank_fusion
from search.semantic import chunk_section
from search.server import make_server


def section(sid, heading, text, title="A bill"):
    return Section(section_id=sid, package_id="PKG", bill="HR 1", version_label="Introduced",
                   number="1.", heading=heading, title=title, text=text,
                   citation=f"HR 1, section {sid}", source_url="https://example.gov", record_type="section")


CORPUS = [
    section("a", "Data brokers", "A data broker shall register with the Commission each year."),
    section("b", "Deletion of information", "A consumer may request that a bank delete personal information."),
    section("c", "Short title", "This Act may be cited as the Example Act."),
]


class FakeSemantic:
    """Stands in for the embedding model: prefers section c."""

    def scores(self, question):
        return [0.1, 0.2, 0.9]


@pytest.fixture
def searcher():
    s = Searcher(CORPUS)
    s._semantic = FakeSemantic()
    return s


def test_every_method_returns_ranked_results_with_citations(searcher):
    for method in METHODS:
        results = searcher.search("Can a bank delete personal information?", k=2, method=method)
        assert results and [r.rank for r in results] == list(range(1, len(results) + 1))
        assert all(r.method == method and r.citation and r.source_url and r.text for r in results)
        assert results == sorted(results, key=lambda r: -r.score)


def test_keyword_methods_find_the_matching_section(searcher):
    for method in ("tfidf", "bm25", "bm25plus", "ql_jm", "ql_dirichlet", "bm25_prf"):
        assert searcher.search("Do data brokers have to register?", k=1, method=method)[0].section_id == "a"


def test_keyword_methods_skip_sections_without_query_terms(searcher):
    assert [r.section_id for r in searcher.search("bank deletion", k=10, method="bm25")] == ["b"]
    assert searcher.search("zebra", k=10, method="bm25") == []
    assert searcher.search("the of and", k=10, method="bm25") == []  # only stopwords


def test_hybrid_fuses_keyword_and_semantic(searcher):
    assert searcher.search("bank deletion", k=1, method="semantic")[0].section_id == "c"
    hybrid = [r.section_id for r in searcher.search("bank deletion", k=3, method="hybrid")]
    assert set(hybrid[:2]) == {"b", "c"}  # each is first in one list, so both beat "a"


def test_result_to_dict_is_json_ready(searcher):
    payload = json.dumps([r.to_dict() for r in searcher.search("bank", k=1, method="bm25")])
    assert '"section_id": "b"' in payload


@pytest.mark.parametrize("question, k, method", [
    ("", 5, "bm25"), ("   ", 5, "bm25"), (None, 5, "bm25"), ("bank", 0, "bm25"),
    ("bank", 101, "bm25"), ("bank", "5", "bm25"), ("bank", True, "bm25"), ("bank", 5, "nope"),
])
def test_bad_input_raises_value_error(searcher, question, k, method):
    with pytest.raises(ValueError):
        searcher.search(question, k=k, method=method)


def test_ties_are_deterministic():
    twins = [section("x", "Twin", "twin words"), section("y", "Twin", "twin words")]
    assert [r.section_id for r in Searcher(twins).search("twin", k=2, method="bm25")] == ["x", "y"]


def test_semantic_model_loads_once_under_concurrency(monkeypatch):
    import search.semantic as semantic

    created = []

    class SlowIndex(FakeSemantic):
        def __init__(self, sections, model):
            created.append(model)

    monkeypatch.setattr(semantic, "SemanticIndex", SlowIndex)
    s = Searcher(CORPUS)
    threads = [threading.Thread(target=s.search, args=("bank",), kwargs={"method": "semantic"}) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1


def test_empty_corpus_rejected():
    with pytest.raises(ValueError):
        Searcher([])


# --- Fusion and chunking ---------------------------------------------------------------------

def test_ranking_is_descending_and_stable():
    assert ranking({0: 0.2, 1: 0.9, 2: 0.2, 3: 0.5}) == [1, 3, 0, 2]


def test_rrf_sums_reciprocal_ranks():
    fused = reciprocal_rank_fusion([[0, 1], [1, 2]])
    assert fused[0] == pytest.approx(1 / (RRF_K + 1))
    assert fused[1] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused[2] == pytest.approx(1 / (RRF_K + 2))
    assert ranking(fused)[0] == 1


def make(text, heading="Heading"):
    return Section("id", "PKG", "HR 1", "Introduced", "1.", heading, "Title", text, "cite", "url", "section")


def test_chunks_cover_text_with_overlap_and_keep_heading():
    words = [f"w{i}" for i in range(450)]
    chunks = chunk_section(make(" ".join(words)), words=200, overlap=50)
    assert len(chunks) == 3 and all(c.startswith("Heading\n") for c in chunks)
    assert chunks[0].split()[-1] == "w199" and chunks[1].split()[1] == "w150"
    assert chunks[-1].split()[-1] == "w449"


def test_short_and_empty_sections_get_one_chunk():
    assert chunk_section(make("just a few words")) == ["Heading\njust a few words"]
    assert chunk_section(make("", heading="Only heading")) == ["Only heading"]
    with pytest.raises(ValueError):
        chunk_section(make("x"), words=10, overlap=10)


def test_read_questions_dedupes_label_rows():
    questions = read_questions(Path(__file__).parents[1] / "eval/labels.csv")
    assert len(questions) == 30 and questions[0][0] == "Q01"


# --- HTTP API --------------------------------------------------------------------------------

@pytest.fixture
def server(searcher):
    srv = make_server(searcher, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def call(url, body=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def test_http_health_and_search(server):
    status, health = call(server + "/health")
    assert status == 200 and health["sections"] == 3 and "hybrid" in health["methods"]
    status, body = call(server + "/search?q=bank%20deletion&k=1&method=bm25")
    assert status == 200 and body["results"][0]["section_id"] == "b" and body["k"] == 1
    status, body = call(server + "/search", {"question": "data brokers register", "k": 2, "method": "bm25"})
    assert status == 200 and body["results"][0]["citation"] == "HR 1, section a"


@pytest.mark.parametrize("path, body, code", [
    ("/search", {"question": ""}, 400), ("/search", {"question": "x", "k": "abc"}, 400),
    ("/search", {"question": "x", "method": "nope"}, 400), ("/search", {"k": 3}, 400),
    ("/search", b"not json", 400), ("/search", b"[1, 2]", 400), ("/missing", None, 404),
])
def test_http_errors(server, path, body, code):
    status, payload = call(server + path, body)
    assert status == code and "error" in payload
