"""Group 2: retrieval models checked against their CS410 definitions (no database, no model download)."""

import math
from collections import Counter

import pytest

from search import lexical
from search.porter import stem
from search.text import tokenize

DOCS = [
    "bank delete personal information bank".split(),
    "bank share information foreign government".split(),
    "data broker register commission".split(),
    "bank".split(),
    ("bank " + "filler " * 40).split(),
]
INDEX = lexical.InvertedIndex(DOCS)


def order(scores):
    return sorted(scores, key=lambda i: (-scores[i], i))


# --- Porter stemmer: examples from Porter (1980) ------------------------------------------------

@pytest.mark.parametrize("word, expected", [
    ("caresses", "caress"), ("ponies", "poni"), ("ties", "ti"), ("cats", "cat"), ("feed", "feed"),
    ("agreed", "agre"), ("plastered", "plaster"), ("motoring", "motor"), ("sing", "sing"),
    ("conflated", "conflat"), ("troubled", "troubl"), ("sized", "size"), ("hopping", "hop"),
    ("tanned", "tan"), ("falling", "fall"), ("hissing", "hiss"), ("fizzed", "fizz"), ("filing", "file"),
    ("happy", "happi"), ("sky", "sky"), ("relational", "relat"), ("conditional", "condit"),
    ("rational", "ration"), ("generalization", "gener"), ("oscillators", "oscil"), ("controll", "control"),
    ("probate", "probat"), ("rate", "rate"), ("cease", "ceas"), ("effective", "effect"),
    ("adoption", "adopt"), ("replacement", "replac"), ("electrical", "electr"), ("goodness", "good"),
])
def test_porter_paper_examples(word, expected):
    assert stem(word) == expected


def test_tokenizer_conflates_word_forms_and_drops_stopwords():
    assert tokenize("Would TikTok be banned?") == ["tiktok", "ban"]
    assert stem("deletion") == stem("delete") == stem("deleted")


# --- Inverted index (Week 2) -------------------------------------------------------------------

def test_inverted_index_statistics():
    assert INDEX.postings["bank"] == [(0, 2), (1, 1), (3, 1), (4, 1)]
    assert INDEX.df["bank"] == 4 and INDEX.cf["bank"] == 5
    assert INDEX.avdl == pytest.approx(sum(map(len, DOCS)) / 5)
    assert INDEX.idf("broker") == pytest.approx(math.log(6 / 1))


def test_only_documents_sharing_a_query_term_are_scored():
    for scorer in (lexical.pivoted_tfidf, lexical.bm25, lexical.ql_jelinek_mercer, lexical.ql_dirichlet):
        assert set(scorer(INDEX, {"broker": 1})) == {2}
        assert scorer(INDEX, {"zebra": 1}) == {}


# --- Formulas match the slides ------------------------------------------------------------------

def test_pivoted_tfidf_formula():
    b, d = 0.2, 0
    expected = math.log(1 + math.log(1 + 2)) / (1 - b + b * len(DOCS[d]) / INDEX.avdl) * math.log(6 / 4)
    assert lexical.pivoted_tfidf(INDEX, {"bank": 1}, b=b)[d] == pytest.approx(expected)


def test_bm25_formula_and_query_term_count():
    k1, b, d = 1.2, 0.75, 0
    norm = k1 * (1 - b + b * len(DOCS[d]) / INDEX.avdl)
    expected = (k1 + 1) * 2 / (2 + norm) * math.log(6 / 4)
    assert lexical.bm25(INDEX, {"bank": 1})[d] == pytest.approx(expected)
    assert lexical.bm25(INDEX, {"bank": 2})[d] == pytest.approx(2 * expected)  # c(w,q) multiplies


def test_bm25_tf_is_sublinear_and_bounded_by_k1_plus_1():
    docs = [["w"] * n + ["x"] * (50 - n) for n in (1, 2, 4, 8, 16, 32)]
    scores = lexical.bm25(lexical.InvertedIndex(docs + [["y"] * 50]), {"w": 1}, b=0)
    gains = [scores[i + 1] - scores[i] for i in range(5)]
    assert all(g > 0 for g in gains) and all(a > b_ for a, b_ in zip(gains, gains[1:]))
    idf = math.log(8 / 6)
    assert max(scores.values()) < (1.2 + 1) * idf


def test_bm25_length_normalization_penalizes_long_documents():
    scores = lexical.bm25(INDEX, {"bank": 1})
    assert scores[3] > scores[4]  # same c(w,d)=1; doc 4 is much longer


def test_bm25plus_lower_bounds_long_documents():
    plain, plus = lexical.bm25(INDEX, {"bank": 1}), lexical.bm25(INDEX, {"bank": 1}, delta=1.0)
    idf = INDEX.idf("bank")
    assert plus[4] - plain[4] == pytest.approx(idf)  # delta * idf per matched term
    assert plus[4] >= idf  # any matching document scores at least delta * idf


# --- Query likelihood: the rank-equivalent forms rank exactly like log p(q|d) (Week 4) --------

def full_log_likelihood(query, doc, p_seen):
    return sum(c * math.log(p_seen(t, doc)) for t, c in query.items())


@pytest.mark.parametrize("query", [{"bank": 1, "information": 1}, {"bank": 2, "foreign": 1}, {"broker": 1, "bank": 1}])
def test_jm_ranking_equals_smoothed_query_likelihood(query):
    lam = 0.1
    def p(t, d):
        return (1 - lam) * DOCS[d].count(t) / len(DOCS[d]) + lam * INDEX.p_collection(t)
    fast = lexical.ql_jelinek_mercer(INDEX, query, lam=lam)
    full = {d: full_log_likelihood(query, d, p) for d in fast}
    assert order(fast) == order(full)
    # JM's rank-equivalent form differs from log p(q|d) by a document-independent constant
    offsets = {round(full[d] - fast[d], 9) for d in fast}
    assert len(offsets) == 1


@pytest.mark.parametrize("query", [{"bank": 1, "information": 1}, {"bank": 2, "foreign": 1}, {"broker": 1, "bank": 1}])
def test_dirichlet_ranking_equals_smoothed_query_likelihood(query):
    mu = 10.0
    def p(t, d):
        return (DOCS[d].count(t) + mu * INDEX.p_collection(t)) / (len(DOCS[d]) + mu)
    fast = lexical.ql_dirichlet(INDEX, query, mu=mu)
    full = {d: full_log_likelihood(query, d, p) for d in fast}
    assert order(fast) == order(full)
    offsets = {round(full[d] - fast[d], 9) for d in fast}
    assert len(offsets) == 1


def test_smoothing_parameters_validated():
    with pytest.raises(ValueError):
        lexical.ql_jelinek_mercer(INDEX, {"bank": 1}, lam=0)
    with pytest.raises(ValueError):
        lexical.ql_dirichlet(INDEX, {"bank": 1}, mu=0)


# --- Rocchio pseudo-relevance feedback (Week 5) ------------------------------------------------

def test_rocchio_adds_feedback_terms_but_keeps_original_terms_dominant():
    tfs = [Counter(d) for d in DOCS]
    expanded = lexical.rocchio_expand(INDEX, tfs, {"delete": 1}, top_docs=[0], n_terms=3)
    new = {t: w for t, w in expanded.items() if t != "delete"}
    assert len(new) == 3 and set(new) <= set(DOCS[0])
    assert expanded["delete"] > max(new.values())


def test_rocchio_without_feedback_documents_returns_query():
    assert lexical.rocchio_expand(INDEX, [], {"bank": 1}, top_docs=[]) == {"bank": 1}
