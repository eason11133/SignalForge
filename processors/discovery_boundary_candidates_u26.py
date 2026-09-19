from __future__ import annotations
import json,sqlite3,hashlib
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from scipy.sparse import hstack

from processors.discovery_boundary_contracts_u26 import DB,stable_id,freeze_hash
from processors.discovery_benchmark_contracts_u25 import DB as U25_DB

def load_latest_decontaminated_rows(root:Path):
    db=root/U25_DB
    if not db.exists():
        raise RuntimeError("U26_U25_DECONTAMINATION_DB_MISSING")
    con=sqlite3.connect(db);con.row_factory=sqlite3.Row
    run=con.execute("SELECT run_id,status,recorded_at,summary_json FROM runs ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if not run:
        con.close();raise RuntimeError("U26_U25_NO_RUN")
    rows=[dict(r) for r in con.execute("""
      SELECT observation_key,signature,text,content_path,content_class,source
      FROM recovered_anchor_content WHERE run_id=? ORDER BY signature,observation_key
    """,(run["run_id"],))]
    con.close()
    return rows,{"u25_run_id":run["run_id"],"u25_status":run["status"],"u25_recorded_at":run["recorded_at"]}

def build_matrix(texts):
    word=TfidfVectorizer(lowercase=True,ngram_range=(1,2),min_df=1,max_features=6000,sublinear_tf=True)
    char=TfidfVectorizer(lowercase=True,analyzer="char_wb",ngram_range=(3,5),min_df=1,max_features=4000,sublinear_tf=True)
    X=normalize(hstack([word.fit_transform(texts),char.fit_transform(texts)]).tocsr())
    return X,{"word_features":len(word.get_feature_names_out()),"char_features":len(char.get_feature_names_out())}

def _sim(X,i,j):
    return float(X[i].multiply(X[j]).sum())

def _pair_key(a,b):
    return tuple(sorted((a,b)))

def generate_candidates(rows,max_cases=16):
    if len(rows)<20:
        raise RuntimeError("U26_INSUFFICIENT_DECONTAMINATED_ROWS")
    texts=[r["text"] for r in rows]
    X,diag=build_matrix(texts)
    by=defaultdict(list)
    for i,r in enumerate(rows):by[r["signature"]].append(i)

    same_div=[]
    same_near=[]
    for sig,idxs in by.items():
        if len(idxs)<2:continue
        vals=[]
        for a in range(len(idxs)):
            for b in range(a+1,len(idxs)):
                i,j=idxs[a],idxs[b]
                vals.append((_sim(X,i,j),i,j,sig))
        vals.sort()
        same_div.append(vals[0])
        same_near.append(vals[-1])
    same_div.sort(key=lambda x:x[0])
    same_near.sort(key=lambda x:x[0],reverse=True)

    cross=[]
    for i,r in enumerate(rows):
        best=None
        for j,s in enumerate(rows):
            if i==j or s["signature"]==r["signature"]:continue
            v=_sim(X,i,j)
            if best is None or v>best[0]:
                best=(v,i,j,r["signature"],s["signature"])
        if best:cross.append(best)
    # unique highest-similarity cross-label pairs
    seen=set();cross_u=[]
    for x in sorted(cross,key=lambda z:z[0],reverse=True):
        pk=_pair_key(rows[x[1]]["observation_key"],rows[x[2]]["observation_key"])
        if pk in seen:continue
        seen.add(pk);cross_u.append(x)

    # Orthogonal cross-label cases give the judge easy controls.
    orth=[]
    all_cross=[]
    n=len(rows)
    # bounded deterministic scan: 219^2 is fine locally
    for i in range(n):
        for j in range(i+1,n):
            if rows[i]["signature"]==rows[j]["signature"]:continue
            all_cross.append((_sim(X,i,j),i,j,rows[i]["signature"],rows[j]["signature"]))
    all_cross.sort(key=lambda x:x[0])
    orth=all_cross[:4]

    target_same=max(4,max_cases//3)
    target_cross=max(6,max_cases//2)
    selected=[]
    used=set()
    def add(kind,rec,reason):
        sim,i,j,*rest=rec
        a=rows[i];b=rows[j];pk=_pair_key(a["observation_key"],b["observation_key"])
        if pk in used:return
        used.add(pk)
        selected.append({
          "case_id":stable_id("case",kind,a["observation_key"],b["observation_key"]),
          "candidate_kind":kind,
          "candidate_reason":reason,
          "candidate_similarity_proxy":round(float(sim),6),
          "left":{**a,"text_sha256":freeze_hash(a["text"])},
          "right":{**b,"text_sha256":freeze_hash(b["text"])},
          "weak_label_relation_hint":"SAME_LABEL" if a["signature"]==b["signature"] else "DIFFERENT_LABEL",
        })
    for rec in same_div[:target_same]:
        add("SAME_LABEL_DIVERGENT",rec,"Weak label matches but raw content is unusually far apart; tests hidden heterogeneity.")
    for rec in cross_u[:target_cross]:
        add("CROSS_LABEL_NEAR",rec,"Weak labels differ but raw content is unusually similar; tests label boundary ambiguity.")
    for rec in orth:
        if len(selected)>=max_cases:break
        add("CROSS_LABEL_ORTHOGONAL",rec,"Weak labels differ and content is far apart; easy control case.")
    # fill with same-label near controls if needed
    for rec in same_near:
        if len(selected)>=max_cases:break
        add("SAME_LABEL_NEAR",rec,"Weak label matches and content is close; easy same-label control candidate.")
    return selected[:max_cases],diag

def freeze_snapshot(root:Path,rows,lineage):
    # The benchmark uses copied text rows, not future reads from the live raw cache.
    obj=[{
      "observation_key":r["observation_key"],"signature":r["signature"],"text_sha256":freeze_hash(r["text"]),
      "content_path":r["content_path"],"content_class":r["content_class"],"source":r.get("source")
    } for r in rows]
    return {
      "lineage":lineage,
      "rows_frozen":len(rows),
      "content_manifest_sha256":hashlib.sha256(
          json.dumps(obj,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest(),
      "truth_boundary":"BENCHMARK_CONTENT_IS_COPIED_FROM_U25_DECONTAMINATED_ROWS_AND_DOES_NOT_REFRESH_FROM_RAW_CACHE",
    }
