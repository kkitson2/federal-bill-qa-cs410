# score.py - Precision@k and nDCG@k for our eval questions
# run: python eval/score.py --labels eval/labels.csv --results results.csv
import argparse
import csv
import math




def read_qrels(path):
    # qrels[qid][section_id] = relevance
    qrels = {}
    f = open(path, encoding="utf-8-sig")  # utf-8-sig so it still works if someone saves the csv in excel
    for row in csv.DictReader(f):
        qid = row["question_id"]
        rel = row.get("relevance", "")
        if rel =="" or rel is None:
            rel = 1
        if qid not in qrels:
            qrels[qid] = {}
        qrels[qid][row["section_id"]] = float(rel)
    f.close()
    return qrels

def read_results(path):
    # res[method][qid] = [(rank, section_id), ...]
    res = {}
    f =open(path, encoding="utf-8-sig")
    for row in csv.DictReader(f):
        method = row.get("method") or "results"
        qid = row["question_id"]
        if method not in res:
            res[method] = {}
        if qid not in res[method]:
            res[method][qid] = []
        res[method][qid].append((int(row["rank"]),row["section_id"]))
    f.close()
    for method in res:
        for qid in res[method]:
            ranked = []
            for rank, sid in sorted(res[method][qid]):
                if sid not in ranked:  # same section twice only counts once
                    ranked.append(sid)
            res[method][qid] = ranked
    return res

def precision_at_k(ranked, rels, k):
    hits = 0
    for sid in ranked[:k]:
        if rels.get(sid, 0) > 0:
            hits = hits + 1
    return hits / k  #divide by k even if less than k results came back

def dcg(gains, k):
    score = 0
    for i in range(len(gains)):
        if i >= k:
            break
        score += gains[i] / math.log2(i + 2)  # i starts at 0 so rank+1 = i+2
    return score

def ndcg_at_k(ranked, rels, k):
    gains = [rels.get(sid, 0) for sid in ranked[:k]]
    best = sorted(rels.values(), reverse=True)
    if dcg(best, k) ==0:
        return 0
    return dcg(gains, k) / dcg(best, k)

def main():
    parser = argparse.ArgumentParser(description="score search results against labels.csv")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--k", type=int, nargs="+", default=[3, 5, 10])
    parser.add_argument("--verbose", action="store_true", help="show each question")
    args = parser.parse_args()
    qrels = read_qrels(args.labels)
    res = read_results(args.results)
    # print(qrels)
    for method in res:
        print("Method:", method, "(" + str(len(qrels)) + " questions)")
        for qid in res[method]:
            if qid not in qrels:
                print("  warning:", qid, "isn't in the labels, skipping")
        p_sum = {}
        n_sum = {}
        for k in args.k:
            p_sum[k] = 0
            n_sum[k] = 0
        for qid in sorted(qrels):
            ranked =res[method].get(qid, [])  #no results = 0 for that question
            out = "  " +qid
            for k in args.k:
                p = precision_at_k(ranked, qrels[qid], k)
                n = ndcg_at_k(ranked, qrels[qid], k)
                p_sum[k] += p
                n_sum[k] += n
                out +="   P@%d=%.3f nDCG@%d=%.3f" % (k, p, k, n)
            if args.verbose:
                print(out)
        if args.verbose:
            print("  ---- avg ----")
        for k in args.k:
            print("  Precision@%d: %.3f" % (k, p_sum[k] / len(qrels)))
            print("  nDCG@%d:      %.3f" % (k, n_sum[k] / len(qrels)))
        print()



if __name__ == "__main__":
    main()