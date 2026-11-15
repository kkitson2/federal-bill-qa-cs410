# Search method comparison (Group 2)

Eight retrieval methods on the 30 labeled questions in `eval/labels.csv`, top 10 sections each,
judged with the CS410 Week 3 methodology (Cranfield-style test collection, ranked-list measures,
paired significance tests). Precision and nDCG come from Group 1's `eval/score.py`.

Files: [runs.csv](runs.csv) (all rankings), [comparison.md](comparison.md) (all measures, all
planned tests, per-question nDCG@10). Re-run: [search/README.md](../search/README.md#re-running-the-evaluation).

## Setup

- **Corpus**: 408 records of `intermediate.sections` (20 bills, 39 versions), snapshot
  `ec140f4e…` from `database/manifest.json`.
- **Keyword index**: heading (counted twice, BM25F-style) + section text, lowercase words,
  stopwords removed, Porter stemmer (agrees with NLTK's original-algorithm Porter on every corpus
  word longer than two letters).
- **Embeddings**: `BAAI/bge-small-en-v1.5` via fastembed (ONNX file
  `Qdrant/bge-small-en-v1.5-onnx-Q@aa8f8b06`, sha256 `51f1bd0a…f2431`); 200-word chunks with
  50-word overlap, heading prefixed, section = best chunk.
- **Parameters**: standard lecture/literature defaults, fixed before looking at results. The 30
  questions are our only test set, so nothing was tuned on them.
- **Determinism**: two full runs, one from an empty cache with a fresh model download, produced
  byte-identical `runs.csv`.

| Method | Model (CS410 week) |
| --- | --- |
| tfidf | Pivoted length normalization VSM, b=0.2 (Week 2) |
| bm25 | Okapi BM25, k1=1.2, b=0.75, IDF log((M+1)/df) (Week 2) |
| bm25plus | BM25+, delta=1 (Week 2) |
| ql_jm | Query likelihood, Jelinek-Mercer, λ=0.1 (Week 4) |
| ql_dirichlet | Query likelihood, Dirichlet prior, μ=2000 (Week 4) |
| bm25_prf | BM25 + Rocchio pseudo-relevance feedback, top 5, α=1, β=0.5, γ=0, +10 terms (Week 5) |
| semantic | Dense embeddings, cosine similarity |
| hybrid | Reciprocal rank fusion (k=60) of bm25 + semantic, chosen as the design before evaluation |

## Results

| Method | P@3 | P@5 | P@10 | R@10 | MAP | gMAP | MRR | nDCG@3 | nDCG@5 | nDCG@10 |
|---|---|---|---|---|---|---|---|---|---|---|
| tfidf | 0.233 | 0.213 | 0.163 | 0.602 | 0.405 | 0.017 | 0.442 | 0.349 | 0.399 | 0.465 |
| bm25 | 0.244 | 0.240 | 0.173 | 0.616 | 0.421 | 0.025 | 0.479 | 0.372 | 0.438 | 0.491 |
| bm25plus | 0.244 | 0.220 | 0.160 | 0.569 | 0.375 | 0.016 | 0.429 | 0.347 | 0.386 | 0.440 |
| ql_jm | 0.278 | 0.240 | 0.180 | 0.657 | 0.476 | 0.050 | 0.548 | 0.448 | 0.477 | 0.543 |
| ql_dirichlet | 0.233 | 0.227 | 0.180 | 0.632 | 0.393 | 0.039 | 0.445 | 0.340 | 0.385 | 0.470 |
| bm25_prf | 0.200 | 0.207 | 0.163 | 0.577 | 0.351 | 0.014 | 0.383 | 0.282 | 0.339 | 0.416 |
| **semantic** | **0.367** | **0.280** | **0.203** | **0.737** | **0.547** | **0.113** | **0.683** | **0.567** | **0.567** | **0.644** |
| **hybrid** | 0.322 | 0.260 | 0.180 | 0.680 | 0.527 | 0.077 | 0.655 | 0.538 | 0.547 | 0.606 |

MAP and gMAP use the top 10 only (AP divides by all relevant sections, so unretrieved ones count
as 0); gMAP floors AP at 1e-5. P@10 is low partly by construction: many questions have fewer than
10 relevant sections and `score.py` divides by k.

Planned paired tests on per-question nDCG@10 (two-sided; AP gives the same picture, see
comparison.md):

| A vs B | mean diff | A better / B better / tie | sign test p | Wilcoxon p |
|---|---|---|---|---|
| tfidf vs bm25 | -0.026 | 3 / 9 / 18 | 0.146 | 0.367 |
| bm25plus vs bm25 | -0.050 | 2 / 9 / 19 | 0.065 | 0.109 |
| ql_jm vs bm25 | +0.053 | 8 / 5 / 17 | 0.581 | 0.081 |
| ql_dirichlet vs bm25 | -0.020 | 6 / 8 / 16 | 0.791 | 0.802 |
| bm25_prf vs bm25 | -0.075 | 1 / 11 / 18 | **0.006** | **0.005** |
| semantic vs bm25 | +0.154 | 15 / 5 / 10 | **0.041** | 0.083 |
| hybrid vs bm25 | +0.115 | 15 / 4 / 11 | **0.019** | **0.042** |
| hybrid vs semantic | -0.038 | 6 / 9 / 15 | 0.607 | 0.426 |

Nine comparisons at α=0.05 means roughly one false positive could appear by chance; the
bm25_prf result (p≈0.005) and the hybrid result (significant under both tests) are the robust ones.

## Findings

1. **The classic keyword models are statistically indistinguishable.** TF-IDF with pivoted
   normalization, BM25, BM25+ and both query-likelihood variants differ by at most 0.05 nDCG@10,
   none significant. This matches the lecture point that well-designed retrieval functions
   (TF transformation + IDF + length normalization) behave similarly. Query likelihood with
   smoothing is the same story from the probabilistic side: its rank-equivalent form is itself a
   TF-IDF-and-length-normalization function (the tests check that it ranks exactly like log p(q|d)).
2. **Meaning-based search is the real gain.** Questions are in everyday language ("Would TikTok be
   banned?") while bills use legal terms ("foreign adversary controlled applications"). Semantic
   search improves every measure over BM25 (nDCG@10 +0.154, MRR 0.68 vs 0.48, gMAP 4×: fewer
   complete failures).
3. **Hybrid is the default.** It is the only method significantly better than BM25 under both
   tests, and it is statistically tied with semantic (p≈0.4–0.6). It also keeps exact-term
   matching (bill names, section numbers, defined terms) that real users will type but these
   plain-language questions rarely test. Equal-weight fusion costs a little when BM25 is weak; we
   did not tune the weight on the test questions.
4. **Pseudo-relevance feedback hurt significantly** (worse on 11 questions, better on 1). Week 5
   warns that pseudo feedback assumes the top documents are relevant. Here BM25's top 5 are often
   wrong, and they are redundant: in 8 of 30 questions the five feedback sections cover at most
   two distinct headings (the same section in several bill versions), so the expansion terms
   amplify one topic, often the wrong one.
5. **BM25+ did not help.** Its lower bound favors long sections that mention query words in
   passing; the corpus mixes 1-line sections with 77k-character ones.
6. **Stemming is not decisive.** Without stemming, BM25 scores 0.549 and QL-JM 0.497; with Porter,
   0.491 and 0.543. The effect flips sign between models, so we keep the standard Porter stemmer.
7. **Shared failures are vocabulary gaps.** Q06 ("Could I sue a company myself...") needs
   "Private rights of action" / "Enforcement by persons"; Q16 ("What harms ... protect kids
   from?") needs "Duty of care". Every method scores 0 on both (BM25 and semantic first reach a relevant section at rank 19–44),
   and Q04
   and Q29 fail for 7 of 8 methods. Legal terms of art are where a small general-purpose embedding
   model also falls short.

## Limits

- 30 questions is a small test set; only large differences reach significance.
- Default parameters only; tuning (e.g. BM25 b, fusion weight, μ) would need separate tuning
  questions to avoid overfitting.
- Labels cover every copy of a section across bill versions, so listing several versions of the
  same section is rewarded here; the app may still want to group them.
