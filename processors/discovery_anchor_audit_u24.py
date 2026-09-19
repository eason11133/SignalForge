from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ.setdefault(_k,"1")
import json,math,sqlite3,re
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

from processors.discovery_representation_contracts_u24 import percentile
from processors.discovery_framegraph_projection_u23 import DB as PROJ_DB

def load_anchor_rows(root:Path):
    con=sqlite3.connect(root/PROJ_DB);con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute("""
      SELECT a.observation_key,a.signature,e.text,e.basis_path,e.basis_class,e.source
      FROM weak_anchors a
      JOIN evidence_spans e ON e.observation_key=a.observation_key AND e.active=1
      ORDER BY a.signature,a.observation_key
    """)]
    con.close()
    # An observation should have one current semantic span in U23; fail closed if duplicates appear.
    seen=set();out=[]
    for r in rows:
        k=r["observation_key"]
        if k in seen:continue
        seen.add(k);out.append(r)
    return out

def load_all_rows(root:Path):
    con=sqlite3.connect(root/PROJ_DB);con.row_factory=sqlite3.Row
    rows=[dict(r) for r in con.execute("""
      SELECT e.observation_key,e.text,e.basis_path,e.basis_class,e.source,g.route,g.reasons_json
      FROM evidence_spans e
      JOIN granularity_routes g ON g.observation_key=e.observation_key
      WHERE e.active=1
      ORDER BY e.observation_key
    """)]
    con.close();return rows

def _cos_sparse_row(mat,i,j):
    return float(mat[i].multiply(mat[j]).sum())

def balanced_group_partitions(group_counts:dict):
    # These are only audit/development partitions, never ground truth Sentinel partitions.
    items=sorted(group_counts.items(),key=lambda kv:(-kv[1],kv[0]))
    bins={"CALIBRATION":[],"VALIDATION":[],"BLIND":[]}
    totals={k:0 for k in bins}
    targets={"CALIBRATION":0.60,"VALIDATION":0.20,"BLIND":0.20}
    grand=max(1,sum(group_counts.values()))
    # Seed each bin repeatedly so 17 groups cannot collapse to 14/2/1 again.
    order=["CALIBRATION","VALIDATION","BLIND","CALIBRATION","VALIDATION","BLIND","CALIBRATION","VALIDATION","BLIND"]
    for idx,(sig,n) in enumerate(items):
        if idx<len(order):
            b=order[idx]
        else:
            # deficit relative to target observation mass
            b=max(bins,key=lambda x: targets[x]-totals[x]/grand)
        bins[b].append(sig);totals[b]+=n
    return {"groups":bins,"observation_counts":totals,
            "truth_boundary":"PARTITIONS_ARE_FOR_WEAK_LABEL_AUDIT_ONLY_NOT_GROUND_TRUTH_SENTINEL"}

def audit_groups(anchor_rows,vectorizer=None,X=None):
    by=defaultdict(list)
    for i,r in enumerate(anchor_rows):by[r["signature"]].append(i)
    if X is None:
        raise ValueError("ANCHOR_AUDIT_REQUIRES_REPRESENTATION")
    centroids={}
    intra={}
    for sig,idxs in by.items():
        c=X[idxs].mean(axis=0)
        # scipy sparse mean yields matrix
        arr=np.asarray(c).reshape(-1)
        norm=np.linalg.norm(arr)
        centroids[sig]=arr/norm if norm else arr
        sims=[]
        if len(idxs)>=2:
            # bounded deterministic pairs
            for a in range(min(len(idxs),12)):
                for b in range(a+1,min(len(idxs),12)):
                    sims.append(_cos_sparse_row(X,idxs[a],idxs[b]))
        intra[sig]=float(np.mean(sims)) if sims else None
    pairs=[]
    sigs=sorted(by)
    for i,a in enumerate(sigs):
        for b in sigs[i+1:]:
            sim=float(np.dot(centroids[a],centroids[b]))
            pairs.append((sim,a,b))
    overlap_thr=percentile([x[0] for x in pairs],0.90) if pairs else None
    coherent_vals=[v for v in intra.values() if v is not None]
    coherence_thr=percentile(coherent_vals,0.25) if coherent_vals else None
    nearest={}
    for sig in sigs:
        cand=[(sim,b if a==sig else a) for sim,a,b in pairs if a==sig or b==sig]
        cand.sort(reverse=True)
        nearest[sig]=cand[0] if cand else (None,None)
    rows=[]
    for sig in sigs:
        n=len(by[sig]);inn=intra[sig];nsim,other=nearest[sig]
        flags=[]
        if n<3:flags.append("LOW_SUPPORT")
        if inn is not None and coherence_thr is not None and inn<coherence_thr:flags.append("LOW_RELATIVE_COHERENCE")
        if nsim is not None and overlap_thr is not None and nsim>=overlap_thr:flags.append("POTENTIAL_LABEL_OVERLAP")
        state="AUDIT_REQUIRED" if flags else "PROVISIONAL_ANCHOR_CANDIDATE"
        rows.append({"signature":sig,"observations":n,"intra_similarity_proxy":round(inn,6) if inn is not None else None,
                     "nearest_signature":other,"nearest_centroid_similarity_proxy":round(nsim,6) if nsim is not None else None,
                     "state":state,"flags":flags})
    return {
        "groups":rows,
        "thresholds":{"relative_coherence_p25":coherence_thr,"cross_group_overlap_p90":overlap_thr},
        "overlap_pairs":[{"a":a,"b":b,"centroid_similarity_proxy":round(sim,6)}
                         for sim,a,b in sorted(pairs,reverse=True)[:12]],
        "partitions":balanced_group_partitions({k:len(v) for k,v in by.items()}),
        "truth_boundary":"AUDIT_STATES_ARE_DIAGNOSTICS_DERIVED_FROM_WEAK_LABELS_NOT_TRUSTED_ANCHORS",
    }
