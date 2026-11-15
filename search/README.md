# Search (Group 2)

Give it a question and it returns ranked bill sections with their text, citation and government
source link. Four methods: `bm25` (keyword), `bm25plus` (BM25+), `semantic` (embeddings), and
`hybrid` (BM25 + semantic fused with reciprocal rank fusion, the default). How they compare:
[results/README.md](../results/README.md).

## Setup

You need Docker, [uv](https://docs.astral.sh/uv/) and this repository. Nothing else is installed on
your machine: PostgreSQL runs in the container defined in `compose.yaml` and listens on
`127.0.0.1:55433` only.

```sh
uv sync --python 3.11 --no-editable --group search   # Python deps, incl. fastembed + numpy

docker compose up -d db                               # PostgreSQL 17
docker compose cp database/billbridge.dump db:/tmp/billbridge.dump
docker compose exec -T db createdb -U billbridge billbridge_shared
docker compose exec -T db pg_restore -U billbridge -d billbridge_shared \
  --single-transaction --exit-on-error --no-owner --no-acl /tmp/billbridge.dump
```

Check it: `docker compose exec -T db psql -U billbridge -d billbridge_shared -c "select count(*) from intermediate.sections"` prints 408.

Already have PostgreSQL 17 locally instead? Run `python3 scripts/restore_database.py` (see
[database/README.md](../database/README.md)) and point search at it with
`SEARCH_DATABASE_URL=postgresql://<user>@localhost:5432/billbridge_shared`.

The first `semantic`/`hybrid` query downloads the embedding model (`BAAI/bge-small-en-v1.5`, about
70 MB) and embeds all sections (about a minute). Both are cached in `./.cache/search/` (git-ignored;
change with `SEARCH_CACHE_DIR`), so later starts take about a second. Delete that folder to reset.

To remove everything: `docker compose down -v` (container and database volume) and `rm -rf .cache/search`.

## Use it from Python

```python
from search import Searcher

searcher = Searcher.from_database()     # load sections and build indexes once, at app start-up

results = searcher.search("Can I make my bank delete the personal information it has about me?", k=5)
for r in results:
    print(r.rank, r.score, r.citation)  # 1 0.0325 118th Congress, HR 1165, ih, section 8.
    print(r.heading, r.source_url)
    print(r.text[:300])

payload = [r.to_dict() for r in results]   # plain dicts, ready for JSON
searcher.search("...", k=10, method="bm25")  # or "bm25plus", "semantic", "hybrid" (default)
```

Keep one `Searcher` for the life of the app and call `search()` as often as you like (a few
milliseconds per query on a laptop). The semantic model loads on the first semantic/hybrid query; to avoid
that delay on a user's first question, warm it up at start-up with one throwaway `search()`.

## Use it from the command line

```sh
uv run --no-editable python -m search ask "Would TikTok be banned in the United States?" -k 3
uv run --no-editable python -m search ask "Do data brokers have to register?" --json   # full results
```

## Result fields

| Field | Meaning |
| --- | --- |
| `rank`, `score`, `method` | 1-based position; method-specific score (only comparable within one query and method) |
| `section_id` | Unique record ID from Group 1 (matches `eval/labels.csv`) |
| `package_id`, `bill`, `version_label` | Bill version, e.g. `BILLS-118hr1165ih`, `HR 1165`, `Introduced in House` |
| `number`, `heading` | Section number and heading (heading can be empty) |
| `title` | GovInfo title of this bill version |
| `citation` | Human-readable citation, e.g. `118th Congress, HR 1165, ih, section 8.` |
| `source_url` | GovInfo page for the bill version |
| `text` | Full section text (added/deleted markings preserved; see `docs/data-contract.md`) |

Notes for the app:
- The same section often appears in several versions of a bill (introduced, reported, ...), so
  near-identical results can sit next to each other. They have different `section_id`s and
  `version_label`s; group or de-duplicate them in the UI if you want.
- Bill text is not necessarily enacted law.
- Sections can be long (up to ~77k characters); trim `text` for display or prompts.

## Re-running the evaluation

```sh
uv run --no-editable python -m search run-eval --out results/runs.csv        # 30 questions x 4 methods, top 10
python3 eval/score.py --labels eval/labels.csv --results results/runs.csv     # Group 1's scorer
uv run --no-editable python -m search.compare --out results/comparison.md    # table + significance tests
uv run --no-editable python -m pytest -q                                      # tests (no database needed)
```

## Code map

| File | What it does |
| --- | --- |
| `corpus.py` | Loads `intermediate.sections` from PostgreSQL |
| `text.py` | Tokenizer: lowercase, stopwords, light suffix stemming |
| `bm25.py` | Okapi BM25 / BM25+ |
| `semantic.py` | Chunking (200 words, 50 overlap, heading prefixed), embeddings, max-chunk scoring |
| `engine.py` | `Searcher`, `SearchResult`, reciprocal rank fusion |
| `compare.py` | Metrics and paired significance tests (sign test, Wilcoxon) |
| `__main__.py` | `ask` and `run-eval` commands |
