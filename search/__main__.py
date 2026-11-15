"""Command line: ask a question, or write eval results for eval/score.py.

    uv run --no-editable python -m search ask "Do data brokers have to register?" -k 5
    uv run --no-editable python -m search run-eval --out results/runs.csv
    python eval/score.py --labels eval/labels.csv --results results/runs.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .engine import METHODS, Searcher


def read_questions(labels: Path) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    with labels.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            seen.setdefault(row["question_id"], row["question"])
    return sorted(seen.items())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m search", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="Default: $SEARCH_DATABASE_URL or the Docker database")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Search one question")
    ask.add_argument("question")
    ask.add_argument("-k", type=int, default=5)
    ask.add_argument("--method", choices=METHODS, default="bm25")
    ask.add_argument("--json", action="store_true", help="Print full results as JSON")

    run = sub.add_parser("run-eval", help="Rank sections for every labeled question")
    run.add_argument("--labels", type=Path, default=Path("eval/labels.csv"))
    run.add_argument("--out", type=Path, default=Path("results/runs.csv"))
    run.add_argument("-k", type=int, default=10)
    run.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))

    args = parser.parse_args(argv)
    searcher = Searcher.from_database(args.database_url)

    if args.command == "ask":
        results = searcher.search(args.question, k=args.k, method=args.method)
        if args.json:
            json.dump([r.to_dict() for r in results], sys.stdout, indent=2)
            print()
            return
        for r in results:
            print(f"{r.rank:>2}. [{r.score:.3f}] {r.citation} {r.heading}")
            print(f"    {r.version_label} | {r.source_url}")
            print(f"    {' '.join(r.text.split())[:200]}...")
        return

    questions = read_questions(args.labels)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question_id", "rank", "section_id", "method"])
        for method in args.methods:
            for qid, question in questions:
                for r in searcher.search(question, k=args.k, method=method):
                    writer.writerow([qid, r.rank, r.section_id, method])
    print(f"Wrote {args.out} ({len(questions)} questions, methods: {', '.join(args.methods)})")


if __name__ == "__main__":
    main()
