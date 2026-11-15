"""Group 2: evaluation measures (CS410 Week 3)."""

import math

import pytest

from search.compare import (average_precision, comparison_pairs, geometric_mean, recall_at_k, reciprocal_rank,
                            sign_test, wilcoxon)

RELS = {"r1": 2, "r2": 1, "r3": 1, "r4": 1}


def test_average_precision_divides_by_all_relevant():
    ranked = ["r1", "x", "r2", "x", "x", "r3"]  # relevant at ranks 1, 3, 6; r4 never retrieved
    assert average_precision(ranked, RELS) == pytest.approx((1 + 2 / 3 + 3 / 6) / 4)
    assert average_precision(["x"], RELS) == 0


def test_average_precision_rewards_moving_relevant_up():
    assert average_precision(["r1", "r2", "x"], RELS) > average_precision(["r1", "x", "r2"], RELS)


def test_gmap_is_dominated_by_hard_queries_unlike_map():
    easy_and_hard = [0.9, 0.9, 0.01]
    balanced = [0.6, 0.6, 0.6]
    assert sum(easy_and_hard) / 3 > sum(balanced) / 3 - 0.01
    assert geometric_mean(easy_and_hard) < geometric_mean(balanced)
    assert geometric_mean([0.0, 1.0]) == pytest.approx(math.sqrt(1e-5))


def test_reciprocal_rank_and_recall():
    assert reciprocal_rank(["x", "x", "r2"], RELS) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], RELS) == 0
    assert recall_at_k(["r1", "x", "r2"], RELS, 2) == pytest.approx(1 / 4)


def test_significance_tests_match_scipy_reference_values():
    diffs = [0.3, -0.1, 0.2, 0.2, 0, 0.5, -0.4, 0.1, 0.25, -0.05, 0.6, 0.3]
    assert sign_test(diffs) == pytest.approx(0.2265625)  # scipy.stats.binomtest
    assert wilcoxon(diffs) == pytest.approx(0.0749356, abs=1e-6)  # scipy.stats.wilcoxon(approx, correction)
    assert sign_test([0, 0]) == wilcoxon([0, 0]) == 1.0


def test_planned_comparisons():
    assert comparison_pairs(["bm25", "tfidf", "semantic", "hybrid"]) == [
        ("tfidf", "bm25"), ("semantic", "bm25"), ("hybrid", "bm25"), ("hybrid", "semantic")]
