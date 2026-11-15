# Search method comparison (Group 2)

All 30 labeled questions in `eval/labels.csv`, top 10 sections per question, scored with Group 1's
`eval/score.py`. Raw rankings: [runs.csv](runs.csv). Full tables incl. per-question nDCG@10:
[comparison.md](comparison.md). How to re-run: [search/README.md](../search/README.md#re-running-the-evaluation).

Corpus: 408 records of `intermediate.sections` (20 bills, 39 versions). Snapshot `ec140f4e…`
(`database/manifest.json`).

## Methods

| Method | What it does |
| --- | --- |
| `bm25` | Okapi BM25 (k1=1.2, b=0.75) over heading (counted twice) + section text; lowercase, stopwords removed, light suffix stemming |
| `bm25plus` | Same with BM25+ (delta=1), the long-document fix from CS410 Week 2 |
| `semantic` | `BAAI/bge-small-en-v1.5` embeddings (via fastembed); sections split into 200-word chunks with 50-word overlap, heading prefixed; a section scores as its best chunk's cosine similarity |
| `hybrid` | Reciprocal rank fusion (k=60) of the `bm25` and `semantic` rankings, equal weights |

Parameters are textbook defaults, not tuned on these 30 questions (they are our only test set).

## Results

| Method | P@3 | P@5 | P@10 | nDCG@3 | nDCG@5 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|---|
| bm25 | 0.300 | 0.260 | 0.183 | 0.432 | 0.485 | 0.534 | 0.514 |
| bm25plus | 0.244 | 0.233 | 0.183 | 0.353 | 0.412 | 0.490 | 0.442 |
| semantic | **0.367** | 0.280 | **0.203** | **0.567** | 0.567 | **0.644** | **0.683** |
| hybrid | 0.333 | **0.287** | 0.190 | 0.535 | **0.569** | 0.619 | 0.641 |

Paired tests on per-question nDCG@10 (two-sided; sign test and Wilcoxon signed-rank, CS410 Week 3):

| A vs B | mean diff | A better / B better / tie | sign p | Wilcoxon p |
|---|---|---|---|---|
| bm25 vs semantic | -0.110 | 6 / 15 / 9 | 0.078 | 0.251 |
| bm25 vs hybrid | -0.084 | 4 / 13 / 13 | 0.049 | 0.118 |
| semantic vs hybrid | +0.026 | 10 / 6 / 14 | 0.454 | 0.501 |
| bm25 vs bm25plus | +0.045 | 10 / 2 / 18 | 0.039 | 0.065 |

Precision@10 looks low partly by construction: many questions have fewer than 10 relevant
sections, and `eval/score.py` divides by k regardless.

## Findings

1. **Meaning-based search helps most.** Semantic and hybrid beat BM25 on every top-3 measure and on
   MRR (0.68 / 0.64 vs 0.51). The questions are written in everyday language ("Would TikTok be
   banned?") while bills use legal wording ("foreign adversary controlled applications"), which is
   exactly the vocabulary gap keyword matching cannot bridge.
2. **Semantic vs hybrid is a tie.** Semantic is ahead on average, but the difference is small and far
   from significant (p ≈ 0.5). Hybrid has the best P@5/nDCG@5 and keeps exact-term matches (bill
   names, section numbers, defined terms), which these plain-language questions rarely test but real
   users will type. **Hybrid is the default** for Group 3; any method can be selected per call.
3. **Hybrid vs BM25 is the clearest gain** (better on 13 questions, worse on 4; sign test p = 0.049),
   though with 30 questions the Wilcoxon test does not reach 0.05.
4. **BM25+ did not help here**, unlike the general result from lecture. Its per-term bonus favors
   long sections that mention many query words in passing: the median top-3 result is 6,887
   characters with BM25+ vs 4,082 with BM25 (corpus median 1,982). Kept only as a reported variant.
5. **Hard questions for every method**: Q06 (private right to sue) and Q16 (harms to protect kids
   from) score 0 for all four; Q04, Q12, Q21, Q23 and Q29 fail for some methods. These usually need
   one specific provision buried inside a long multi-topic section or bill.

## Limits

- 30 questions is a small sample; only large differences can reach significance.
- One embedding model and default parameters were tried; a larger model, weighted fusion, or a
  re-ranker could do better but should be tuned on questions other than these 30.
- Labels cover every copy of a section across bill versions, so results that list several versions
  of the same section are rewarded here; a UI may still want to group them.
