# hand calculated values for the scoring script
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "eval"))
import score

def test_teammate_example():
    #B, A, C with only A relevant -> should be 0.333 and 0.631
    rels ={"A": 1}
    assert round(score.precision_at_k(["B", "A", "C"], rels, 3), 3) == 0.333
    assert round(score.ndcg_at_k(["B", "A", "C"], rels, 3), 3) ==0.631

def test_two_relevant():
    #DCG = 1 + 1/log2(4) =1.5, best = 1 + 1/log2(3) = 1.631
    rels = {"D": 1, "E": 1}
    assert round(score.precision_at_k(["D", "F","E"], rels, 3), 3) == 0.667
    assert round(score.ndcg_at_k(["D", "F","E"], rels, 3), 3) == 0.920

def test_graded_order_matters():
    rels = {"X": 2, "Y": 1}
    assert score.ndcg_at_k(["X", "Y"], rels, 2) == 1.0
    assert score.ndcg_at_k(["Y", "X"], rels, 2) < 1.0

def test_empty():
    assert score.precision_at_k([], {"A": 1}, 3) ==0
    assert score.ndcg_at_k([], {"A": 1}, 3) == 0

def test_example_csvs():
    folder = os.path.join(os.path.dirname(__file__), "..", "eval", "examples")
    qrels = score.read_qrels(os.path.join(folder, "example_labels.csv"))
    res = score.read_results(os.path.join(folder, "example_results.csv"))
    assert res["bm25"]["Q01"] == ["B", "A", "C"]
    assert round(score.ndcg_at_k(res["bm25"]["Q01"], qrels["Q01"], 3), 3) == 0.631