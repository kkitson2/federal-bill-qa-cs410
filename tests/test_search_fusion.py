"""Group 2: rank fusion, chunking and significance tests (no database or model download)."""

import pytest

from search import Section
from search.compare import sign_test, wilcoxon
from search.engine import RRF_K, ranking, reciprocal_rank_fusion
from search.semantic import chunk_section


def make(text, heading="Heading"):
    return Section("id", "PKG", "HR 1", "Introduced", "1.", heading, "Title", text, "cite", "url", "section")


def test_ranking_is_descending_and_stable():
    assert ranking([0.2, 0.9, 0.2, 0.5]) == [1, 3, 0, 2]


def test_rrf_sums_reciprocal_ranks():
    fused = reciprocal_rank_fusion([[0, 1], [1, 2]])
    assert fused[0] == pytest.approx(1 / (RRF_K + 1))
    assert fused[1] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused[2] == pytest.approx(1 / (RRF_K + 2))
    assert ranking(fused)[0] == 1  # in both lists, so it wins


def test_chunks_cover_text_with_overlap_and_keep_heading():
    words = [f"w{i}" for i in range(450)]
    chunks = chunk_section(make(" ".join(words)), words=200, overlap=50)
    assert len(chunks) == 3
    assert all(c.startswith("Heading\n") for c in chunks)
    assert chunks[0].split()[-1] == "w199" and chunks[1].split()[1] == "w150"
    assert chunks[-1].split()[-1] == "w449"


def test_short_and_empty_sections_get_one_chunk():
    assert chunk_section(make("just a few words")) == ["Heading\njust a few words"]
    assert chunk_section(make("", heading="Only heading")) == ["Only heading"]
    with pytest.raises(ValueError):
        chunk_section(make("x"), words=10, overlap=10)


def test_significance_tests_match_scipy_reference_values():
    diffs = [0.3, -0.1, 0.2, 0.2, 0, 0.5, -0.4, 0.1, 0.25, -0.05, 0.6, 0.3]
    assert sign_test(diffs) == pytest.approx(0.2265625)  # scipy.stats.binomtest
    assert wilcoxon(diffs) == pytest.approx(0.0749356, abs=1e-6)  # scipy.stats.wilcoxon, approx + correction
    assert sign_test([0, 0]) == wilcoxon([0, 0]) == 1.0
