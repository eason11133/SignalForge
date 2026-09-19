from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ.setdefault(_k,"1")
import math
from collections import defaultdict
import numpy as np

def _sim(X,i,j):
    return float(X[i].multiply(X[j]).sum())

def weak_label_proxy(rows,X,max_pairs=160):
    by=defaultdict(list)
    for i,r in enumerate(rows):by[r["signature"]].append(i)
    eligible={k:v for k,v in by.items() if len(v)>=3}
    positives=[]
    for sig,idxs in sorted(eligible.items()):
        for i in range(min(len(idxs)-1,8)):
            positives.append((idxs[i],idxs[i+1],sig))
    # Hard negatives: nearest cross-label pairs within a bounded anchor set.
    neg=[]
    n=len(rows)
    for i in range(n):
        if rows[i]["signature"] not in eligible:continue
        best=None
        for j in range(n):
            if i==j or rows[j]["signature"]==rows[i]["signature"] or rows[j]["signature"] not in eligible:continue
            s=_sim(X,i,j)
            if best is None or s>best[0]:best=(s,i,j)
        if best:neg.append(best)
    neg=sorted(neg,reverse=True)[:max_pairs]
    pos_s=[_sim(X,i,j) for i,j,_ in positives[:max_pairs]]
    neg_s=[x[0] for x in neg]
    # nearest-other top1 label recovery proxy
    top1=[]
    for i in range(n):
        if rows[i]["signature"] not in eligible:continue
        best=(-1,None)
        for j in range(n):
            if i==j:continue
            s=_sim(X,i,j)
            if s>best[0]:best=(s,j)
        if best[1] is not None:top1.append(rows[best[1]]["signature"]==rows[i]["signature"])
    p=float(np.mean(pos_s)) if pos_s else None
    q=float(np.mean(neg_s)) if neg_s else None
    return {
      "eligible_signature_groups":len(eligible),
      "eligible_observations":sum(len(v) for v in eligible.values()),
      "positive_pairs":len(pos_s),"hard_negative_pairs":len(neg_s),
      "same_signature_similarity_proxy":round(p,6) if p is not None else None,
      "hard_negative_similarity_proxy":round(q,6) if q is not None else None,
      "separation_margin_proxy":round(p-q,6) if p is not None and q is not None else None,
      "nearest_neighbor_same_signature_proxy":round(float(np.mean(top1)),6) if top1 else None,
      "truth_boundary":"WEAK_LABEL_PROXY_ONLY_NOT_ACCURACY_OR_GROUND_TRUTH",
    }

def cross_arm_table(metrics):
    rows=[]
    for arm,m in metrics.items():
        rows.append({"arm":arm,"status":m.get("status","READY"),
                     "separation_margin_proxy":(m.get("proxy") or {}).get("separation_margin_proxy"),
                     "nearest_neighbor_same_signature_proxy":(m.get("proxy") or {}).get("nearest_neighbor_same_signature_proxy"),
                     "sample_size":m.get("sample_size"),"comparable_scope":m.get("comparable_scope")})
    return rows
