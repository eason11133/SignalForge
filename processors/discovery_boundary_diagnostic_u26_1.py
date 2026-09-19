from __future__ import annotations
import json, sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ENGINE_VERSION="signalforge-boundary-diagnostic-u26-1-v1"
DB=Path(".radar_runtime/discovery_boundary_sentinel_v1.sqlite3")
ASPECTS=("WORKFLOW","FRICTION","MECHANISM","CONSTRAINT","CONSEQUENCE")

def _latest_run(con):
    row=con.execute("SELECT run_id,status,recorded_at FROM runs ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if not row: raise RuntimeError("U26_1_NO_U26_RUN")
    return dict(row)

def _pair_class(fwd,rev):
    if fwd==rev:
        return "STABLE_UNKNOWN" if fwd=="UNKNOWN" else "STABLE_INFORMATIVE"
    if fwd=="UNKNOWN" or rev=="UNKNOWN": return "UNKNOWN_ASYMMETRY"
    return "ORDER_FLIP"

def analyze(root=Path(".")):
    path=root/DB
    if not path.exists():
        return {"engine_version":ENGINE_VERSION,"status":"BLOCKED_U26_DB_MISSING"}
    con=sqlite3.connect(path);con.row_factory=sqlite3.Row
    run=_latest_run(con)
    rows=[dict(r) for r in con.execute("""
      SELECT case_id,candidate_kind,candidate_similarity,status,
             weak_label_metadata_json,adjudication_json
      FROM cases WHERE run_id=? ORDER BY case_id
    """,(run["run_id"],))]
    con.close()

    aspect_counts={a:Counter() for a in ASPECTS}
    kind_counts=defaultdict(Counter)
    root_causes=Counter()
    case_summaries=[]

    for r in rows:
        adj=json.loads(r["adjudication_json"])
        labels=json.loads(r["weak_label_metadata_json"])
        per={}; informative=unstable=stable_unknown=0
        for a in ASPECTS:
            z=(adj.get("aspects") or {}).get(a) or {}
            f=str(z.get("forward") or "UNKNOWN").upper()
            rv=str(z.get("reverse") or "UNKNOWN").upper()
            cls=_pair_class(f,rv)
            aspect_counts[a][cls]+=1
            kind_counts[r["candidate_kind"]][cls]+=1
            per[a]={"forward":f,"reverse":rv,"class":cls}
            if cls=="STABLE_INFORMATIVE": informative+=1
            elif cls in ("UNKNOWN_ASYMMETRY","ORDER_FLIP"): unstable+=1
            else: stable_unknown+=1

        if unstable:
            root="ORDER_SENSITIVITY"
        elif informative==0:
            root="TRUE_INFORMATION_GAP"
        else:
            root="STABLE_PARTIAL_INFORMATION"
        root_causes[root]+=1
        case_summaries.append({
          "case_id":r["case_id"],"candidate_kind":r["candidate_kind"],
          "similarity_proxy":r["candidate_similarity"],"stored_status":r["status"],
          "weak_labels":[labels.get("left_signature"),labels.get("right_signature")],
          "diagnostic_root":root,"stable_informative_aspects":informative,
          "unstable_aspects":unstable,"stable_unknown_aspects":stable_unknown,"aspects":per
        })

    n=max(1,len(rows))
    aspect_summary={}
    for a,c in aspect_counts.items():
        aspect_summary[a]={
          "stable_informative":c["STABLE_INFORMATIVE"],
          "stable_unknown":c["STABLE_UNKNOWN"],
          "unknown_asymmetry":c["UNKNOWN_ASYMMETRY"],
          "order_flip":c["ORDER_FLIP"],
          "symmetry_rate":round((c["STABLE_INFORMATIVE"]+c["STABLE_UNKNOWN"])/n,6),
          "informative_stable_rate":round(c["STABLE_INFORMATIVE"]/n,6),
          "order_instability_rate":round((c["UNKNOWN_ASYMMETRY"]+c["ORDER_FLIP"])/n,6),
        }

    insuff=[x for x in case_summaries if x["stored_status"]=="INSUFFICIENT"]
    insuff_breakdown=dict(Counter(x["diagnostic_root"] for x in insuff))
    kind_summary={}
    for kind,c in kind_counts.items():
        total=sum(c.values())
        kind_summary[kind]={
          "aspect_judgments":total,
          "stable_informative":c["STABLE_INFORMATIVE"],
          "stable_unknown":c["STABLE_UNKNOWN"],
          "unknown_asymmetry":c["UNKNOWN_ASYMMETRY"],
          "order_flip":c["ORDER_FLIP"],
          "order_instability_rate":round((c["UNKNOWN_ASYMMETRY"]+c["ORDER_FLIP"])/max(1,total),6),
        }

    if root_causes["ORDER_SENSITIVITY"] >= max(2,len(rows)//4):
        next_protocol="CRITERIA_FIRST_SYMMETRIC_JUDGE"
        reason="ORDER_SENSITIVITY_IS_MATERIAL"
    elif root_causes["TRUE_INFORMATION_GAP"] >= max(2,len(rows)//3):
        next_protocol="IMPROVE_CASE_SELECTION_OR_POINTWISE_COVERAGE"
        reason="TRUE_INFORMATION_GAPS_DOMINATE"
    else:
        next_protocol="SECOND_JUDGE_REVIEW_OF_CHALLENGE_CASES"
        reason="MIXED_FAILURE_MODES"

    examples=sorted(case_summaries,key=lambda x:(
        x["diagnostic_root"]!="ORDER_SENSITIVITY",
        x["diagnostic_root"]!="TRUE_INFORMATION_GAP",x["case_id"]))[:16]

    return {
      "engine_version":ENGINE_VERSION,"status":"PASS_READ_ONLY_DIAGNOSTIC",
      "u26_run_id":run["run_id"],"u26_status":run["status"],"cases":len(rows),
      "root_cause_counts":dict(root_causes),"insufficient_breakdown":insuff_breakdown,
      "aspect_summary":aspect_summary,"candidate_kind_summary":kind_summary,
      "examples":examples,
      "decision":{"next_protocol":next_protocol,"reason":reason,
                  "production_authority":0,"u26_data_modified":False},
      "truth_boundary":"READ_ONLY_DIAGNOSTIC_ONLY; NO_GOLD_LABELS, NO_PROMOTION, NO_FOUNDER_TRUTH_CHANGE",
      "product_ideation":0
    }
