"""Runnable example: send a question, read the results.

    uv run --no-editable python -m search.example                       # in-process Python API
    uv run --no-editable python -m search.example --http http://127.0.0.1:8410   # against `python -m search serve`
"""

from __future__ import annotations

import argparse
import json
import urllib.request

QUESTION = "Can I make my bank delete the personal information it has about me?"


def via_python(question: str, k: int) -> list[dict]:
    from search import Searcher

    searcher = Searcher.from_database()  # in an app: create once at start-up and reuse
    return [r.to_dict() for r in searcher.search(question, k=k)]


def via_http(base_url: str, question: str, k: int) -> list[dict]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/search",
        data=json.dumps({"question": question, "k": k, "method": "hybrid"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["results"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", default=QUESTION)
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--http", metavar="URL", help="Call a running search server instead of the Python API")
    args = parser.parse_args()

    results = via_http(args.http, args.question, args.k) if args.http else via_python(args.question, args.k)
    print(f"Q: {args.question}\n")
    for r in results:
        print(f"#{r['rank']}  {r['citation']}")
        print(f"    {r['heading']}  ({r['version_label']})")
        print(f"    source: {r['source_url']}")
        print(f"    id:     {r['section_id']}")
        print(f"    text:   {' '.join(r['text'].split())[:240]}...\n")


if __name__ == "__main__":
    main()
