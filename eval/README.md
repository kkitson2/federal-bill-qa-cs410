# eval

30 test questions with labeled relevant sections, plus a script to score search results (Precision@k, nDCG@k).

## labels.csv

One row per (question, relevant section). `relevance` is 2 if the section answers the question directly, 1 if partially.

- Sections are labeled in every version they appear in, so match on `section_id` not section number
- `[DELETED]` sections (struck out text in reported versions) aren't labeled
- KOSA and COPPA 2.0 show up in multiple bills, each copy is labeled

## Results format (Group 2)

```
question_id,rank,section_id,method
Q01,1,B,bm25
Q01,2,A,bm25
```

`method` is optional. Put multiple methods in one file to compare them.

## Running

```
python eval/score.py --labels eval/labels.csv --results your_results.csv --verbose
```

k defaults to 3, 5, 10 (change with `--k`). No extra packages needed.

To check the math, run it on `examples/`. Q01 should give P@3 = 0.333 and nDCG@3 = 0.631. Tests are in `tests/test_score.py`.