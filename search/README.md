# Search (Group 2)

Give it a question and it returns ranked bill sections with their text, citation and government
source link. Use it from Python, from the command line, or over HTTP (any language).

Default method: **`hybrid`**, BM25 keyword search fused with semantic (embedding) search by
reciprocal rank fusion. Every method from the comparison can be selected per call; how they compare
is in [results/README.md](../results/README.md).

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
`createdb` refuses to overwrite: if `billbridge_shared` already exists you are already set up.

Already have PostgreSQL 17 locally instead? Run `python3 scripts/restore_database.py` (see
[database/README.md](../database/README.md)) and point search at it with
`SEARCH_DATABASE_URL=postgresql://<user>@localhost:5432/billbridge_shared`.

The first `semantic`/`hybrid` query downloads the embedding model (`BAAI/bge-small-en-v1.5`, about
70 MB) and embeds all sections (about a minute). Both are cached in `./.cache/search/` (git-ignored;
change with `SEARCH_CACHE_DIR`), so later starts take about a second. Delete that folder to reset.

To remove everything: `docker compose down -v` (container and database volume) and `rm -rf .cache/search`.

## Try it

```sh
uv run --no-editable python -m search.example                 # prints the top 3 for a sample question
uv run --no-editable python -m search ask "Would TikTok be banned in the United States?" -k 3
uv run --no-editable python -m search ask "Do data brokers have to register?" --json   # full results
```

## Use it from Python

```python
from search import Searcher

searcher = Searcher.from_database()     # at app start-up: loads 408 sections, builds the index
searcher.warm_up()                      # optional: load the embedding model now, not on 1st query

results = searcher.search("Can I make my bank delete the personal information it has about me?", k=5)
for r in results:
    print(r.rank, r.citation)           # 1 118th Congress, HR 1165, ih, section 8.
    print(r.heading, r.source_url)
    print(r.text[:300])

payload = [r.to_dict() for r in results]          # plain dicts, ready for JSON
searcher.search("...", k=10, method="bm25")       # any method in search.METHODS
```

Keep one `Searcher` for the life of the app and call `search()` as often as you like, from any
thread (a few milliseconds per query on a laptop). Invalid input (empty question, `k` outside
1–100, unknown method) raises `ValueError`; an unreachable or empty database raises `RuntimeError`
with a hint.

## Use it over HTTP

```sh
uv run --no-editable python -m search serve        # http://127.0.0.1:8410, loads the model first
```

```sh
curl "http://127.0.0.1:8410/health"
curl "http://127.0.0.1:8410/search?q=Do%20data%20brokers%20have%20to%20register%3F&k=3"
curl -X POST http://127.0.0.1:8410/search -H "Content-Type: application/json" \
     -d '{"question": "Do data brokers have to register?", "k": 3, "method": "hybrid"}'
uv run --no-editable python -m search.example --http http://127.0.0.1:8410   # same, from Python
```

Response: `{"question": ..., "method": ..., "k": ..., "results": [<result>, ...]}`, each result
with the fields below. Errors: `{"error": "..."}` with status 400 (bad input), 404 (unknown path)
or 500. The server binds to 127.0.0.1 and has no authentication: it is a local service for the app
to call, not something to expose to the internet.

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
- Keyword methods return only sections containing at least one query word, so they can return
  fewer than `k` results (or none). `semantic` and `hybrid` always return `k`.
- Bill text is not necessarily enacted law.
- Sections can be long (up to ~77k characters); trim `text` for display or prompts.

## Methods

| `method` | Model (CS410 week) |
| --- | --- |
| `tfidf` | Vector space model with pivoted length normalization, b=0.2 (Week 2) |
| `bm25` | Okapi BM25, k1=1.2, b=0.75 (Week 2) |
| `bm25plus` | BM25+ (BM25 with lower-bounded TF, delta=1) (Week 2) |
| `ql_jm` | Query likelihood, Jelinek-Mercer smoothing, λ=0.1 (Week 4) |
| `ql_dirichlet` | Query likelihood, Dirichlet prior smoothing, μ=2000 (Week 4) |
| `bm25_prf` | BM25 with Rocchio pseudo-relevance feedback: top 5, α=1, β=0.5, +10 terms (Week 5) |
| `semantic` | `bge-small-en-v1.5` embeddings over 200-word chunks (50 overlap), best chunk per section |
| `hybrid` | Reciprocal rank fusion (k=60) of `bm25` and `semantic` (default) |

All keyword methods share one inverted index over heading (counted twice, a simple BM25F-style
field weight) + section text, tokenized as lowercase words, stopwords removed, Porter stemming.
Parameters are the standard defaults from the lectures/literature, not tuned on our test questions.

## Re-running the evaluation

```sh
uv run --no-editable python -m search run-eval --out results/runs.csv        # 30 questions x 8 methods, top 10
python3 eval/score.py --labels eval/labels.csv --results results/runs.csv     # Group 1's scorer
uv run --no-editable python -m search.compare --out results/comparison.md    # all measures + significance tests
uv run --no-editable python -m pytest -q                                      # tests (no database needed)
```

`run-eval` is deterministic: two runs, including one with a fresh model download, give byte-identical CSVs.

## Code map

| File | What it does |
| --- | --- |
| `corpus.py` | Loads `intermediate.sections` from PostgreSQL |
| `porter.py`, `text.py` | Porter stemmer (1980) and tokenizer |
| `lexical.py` | Inverted index; TF-IDF, BM25/BM25+, query likelihood (JM, Dirichlet), Rocchio feedback |
| `semantic.py` | Chunking, embeddings, best-chunk scoring |
| `engine.py` | `Searcher`, `SearchResult`, reciprocal rank fusion, input validation |
| `server.py` | JSON HTTP API (standard library) |
| `compare.py` | P@k, R@10, MAP, gMAP, MRR, nDCG@k, sign test, Wilcoxon |
| `example.py` | Runnable example (Python API or HTTP) |
| `__main__.py` | `ask`, `serve` and `run-eval` commands |
