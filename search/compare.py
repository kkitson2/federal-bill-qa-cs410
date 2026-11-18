"""Compare methods from a results CSV with the CS410 Week 3 measures: P@k, R@10, MAP, gMAP, MRR,
nDCG@k, plus paired significance tests (sign test, Wilcoxon signed-rank) on per-question scores.

P@k and nDCG@k come from Group 1's eval/score.py so they match it exactly.

    uv run --no-editable python -m search.compare --results results/runs.csv --out results/comparison.md
"""

from __future__ import annotations

import argparse
import importlib.util
import math
from pathlib import Path

GMAP_EPSILON = 1e-5  # AP of 0 would make the geometric mean 0; the usual TREC-style floor


def load_scorer(path: Path):
    spec = importlib.util.spec_from_file_location("eval_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reciprocal_rank(ranked: list[str], rels: dict[str, float]) -> float:
    for i, sid in enumerate(ranked, start=1):
        if rels.get(sid, 0) > 0:
            return 1.0 / i
    return 0.0


def average_precision(ranked: list[str], rels: dict[str, float]) -> float:
    """Sum of precision at each relevant retrieved rank, divided by the number of relevant sections
    (so relevant sections never retrieved count as precision 0)."""
    relevant = {s for s, r in rels.items() if r > 0}
    if not relevant:
        return 0.0
    hits, total = 0, 0.0
    for i, sid in enumerate(ranked, start=1):
        if sid in relevant:
            hits += 1
            total += hits / i
    return total / len(relevant)


def recall_at_k(ranked: list[str], rels: dict[str, float], k: int) -> float:
    relevant = {s for s, r in rels.items() if r > 0}
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def geometric_mean(values: list[float], epsilon: float = GMAP_EPSILON) -> float:
    return math.exp(sum(math.log(max(v, epsilon)) for v in values) / len(values))


def sign_test(diffs: list[float]) -> float:
    """Exact two-sided binomial sign test; zero differences are dropped."""
    wins = sum(d > 1e-12 for d in diffs)
    n = wins + sum(d < -1e-12 for d in diffs)
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(wins, n - wins) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def wilcoxon(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank test, normal approximation with tie and continuity correction."""
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    n = len(nonzero)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(nonzero[i]))
    ranks = [0.0] * n
    ties = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(abs(nonzero[order[j + 1]]) - abs(nonzero[order[i]])) < 1e-12:
            j += 1
        for m in range(i, j + 1):
            ranks[order[m]] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, nonzero) if d > 0)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - ties / 48
    if var <= 0:
        return 1.0
    z = (abs(w_plus - mean) - 0.5) / math.sqrt(var)
    return min(1.0, math.erfc(max(z, 0) / math.sqrt(2)))


def comparison_pairs(methods: list[str], baseline: str = "bm25") -> list[tuple[str, str]]:
    """Planned comparisons: every method against the BM25 baseline, plus semantic vs hybrid."""
    pairs = [(m, baseline) for m in methods if m != baseline and baseline in methods]
    if "semantic" in methods and "hybrid" in methods:
        pairs.append(("hybrid", "semantic"))
    return pairs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", type=Path, default=Path("eval/labels.csv"))
    parser.add_argument("--results", type=Path, default=Path("results/runs.csv"))
    parser.add_argument("--scorer", type=Path, default=Path("eval/score.py"))
    parser.add_argument("--out", type=Path, help="Also write the report as Markdown")
    args = parser.parse_args(argv)

    score = load_scorer(args.scorer)
    qrels = score.read_qrels(str(args.labels))
    runs = score.read_results(str(args.results))
    methods = list(runs)
    qids = sorted(qrels)
    avg = lambda values: sum(values) / len(values)  # noqa: E731

    ndcg10: dict[str, dict[str, float]] = {}
    ap: dict[str, dict[str, float]] = {}
    lines = ["| Method | P@3 | P@5 | P@10 | R@10 | MAP | gMAP | MRR | nDCG@3 | nDCG@5 | nDCG@10 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in methods:
        ranked = {q: runs[m].get(q, []) for q in qids}
        ndcg10[m] = {q: score.ndcg_at_k(ranked[q], qrels[q], 10) for q in qids}
        ap[m] = {q: average_precision(ranked[q], qrels[q]) for q in qids}
        cells = [avg([score.precision_at_k(ranked[q], qrels[q], k) for q in qids]) for k in (3, 5, 10)]
        cells += [avg([recall_at_k(ranked[q], qrels[q], 10) for q in qids]), avg(list(ap[m].values())),
                  geometric_mean(list(ap[m].values())), avg([reciprocal_rank(ranked[q], qrels[q]) for q in qids])]
        cells += [avg([score.ndcg_at_k(ranked[q], qrels[q], k) for q in qids]) for k in (3, 5)]
        cells.append(avg(list(ndcg10[m].values())))
        lines.append(f"| {m} | " + " | ".join(f"{c:.3f}" for c in cells) + " |")

    lines += ["", f"MAP/gMAP are over the top 10 results only; gMAP floors AP at {GMAP_EPSILON:g}.", "",
              f"Paired tests, two-sided, {len(qids)} questions (planned comparisons: each method vs bm25, "
              "and hybrid vs semantic).", "",
              "| A vs B | metric | mean diff (A-B) | A better / B better / tie | sign test p | Wilcoxon p |",
              "|---|---|---|---|---|---|"]
    for a, b in comparison_pairs(methods):
        for name, per_q in (("nDCG@10", ndcg10), ("AP", ap)):
            diffs = [per_q[a][q] - per_q[b][q] for q in qids]
            wins, losses = sum(d > 1e-12 for d in diffs), sum(d < -1e-12 for d in diffs)
            lines.append(f"| {a} vs {b} | {name} | {avg(diffs):+.3f} | {wins} / {losses} / {len(diffs) - wins - losses}"
                         f" | {sign_test(diffs):.3f} | {wilcoxon(diffs):.3f} |")

    lines += ["", "Per-question nDCG@10:", "", "| Question | " + " | ".join(methods) + " |",
              "|---|" + "---|" * len(methods)]
    for q in qids:
        lines.append(f"| {q} | " + " | ".join(f"{ndcg10[m][q]:.3f}" for m in methods) + " |")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
