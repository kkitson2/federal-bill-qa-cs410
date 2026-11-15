"""Compare methods from a results CSV: mean P@k / nDCG@k / MRR, plus paired significance tests on
per-question nDCG@10 (sign test and Wilcoxon signed-rank, as in CS410 Week 3).

Scoring reuses Group 1's eval/score.py so numbers match it exactly.

    uv run --no-editable python -m search.compare --results results/runs.csv --out results/comparison.md
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import math
from pathlib import Path


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


def sign_test(diffs: list[float]) -> float:
    """Exact two-sided binomial sign test; zero differences are dropped."""
    wins = sum(d > 0 for d in diffs)
    n = wins + sum(d < 0 for d in diffs)
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(wins, n - wins) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def wilcoxon(diffs: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank test, normal approximation with tie correction."""
    nonzero = [d for d in diffs if abs(d) > 1e-12]
    n = len(nonzero)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(nonzero[i]))
    ranks = [0.0] * n
    i = 0
    ties = 0.0
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
    z = (abs(w_plus - mean) - 0.5) / math.sqrt(var)  # continuity correction
    return min(1.0, math.erfc(max(z, 0) / math.sqrt(2)))


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
    qids = sorted(qrels)
    ks = (3, 5, 10)

    per_query: dict[str, dict[str, float]] = {}
    lines = ["| Method | P@3 | P@5 | P@10 | nDCG@3 | nDCG@5 | nDCG@10 | MRR |", "|---|---|---|---|---|---|---|---|"]
    for method, run in runs.items():
        cells, per_query[method] = [], {}
        for metric in ("p", "n"):
            for k in ks:
                fn = score.precision_at_k if metric == "p" else score.ndcg_at_k
                cells.append(sum(fn(run.get(q, []), qrels[q], k) for q in qids) / len(qids))
        cells.append(sum(reciprocal_rank(run.get(q, []), qrels[q]) for q in qids) / len(qids))
        for q in qids:
            per_query[method][q] = score.ndcg_at_k(run.get(q, []), qrels[q], 10)
        lines.append(f"| {method} | " + " | ".join(f"{c:.3f}" for c in cells) + " |")

    lines += ["", f"Paired tests on per-question nDCG@10 ({len(qids)} questions; two-sided p-values).", "",
              "| A vs B | mean diff (A-B) | A better / B better / tie | sign test p | Wilcoxon p |",
              "|---|---|---|---|---|"]
    for a, b in itertools.combinations(runs, 2):
        diffs = [per_query[a][q] - per_query[b][q] for q in qids]
        wins, losses = sum(d > 1e-12 for d in diffs), sum(d < -1e-12 for d in diffs)
        lines.append(f"| {a} vs {b} | {sum(diffs) / len(diffs):+.3f} | {wins} / {losses} / {len(diffs) - wins - losses}"
                     f" | {sign_test(diffs):.3f} | {wilcoxon(diffs):.3f} |")

    lines += ["", "Per-question nDCG@10:", "", "| Question | " + " | ".join(runs) + " |",
              "|---|" + "---|" * len(runs)]
    for q in qids:
        lines.append(f"| {q} | " + " | ".join(f"{per_query[m][q]:.3f}" for m in runs) + " |")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
