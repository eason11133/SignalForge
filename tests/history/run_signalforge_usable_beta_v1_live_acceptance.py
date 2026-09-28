from __future__ import annotations
import argparse, json, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8000/api"

def repo_root() -> Path | None:
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p/"api").is_dir() and (p/"dashboard").is_dir() and (p/"processors").is_dir():
            return p
    p = Path(__file__).resolve().parent
    return p if p.exists() else None

def call(base:str,path:str,method:str="GET",timeout:int=30)->Any:
    req=urllib.request.Request(base.rstrip("/")+path,method=method,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            raw=resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body=exc.read().decode("utf-8",errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {body[:1000]}") from exc
    except Exception as exc:
        raise RuntimeError(f"REQUEST_FAILED {method} {path}: {type(exc).__name__}: {exc}") from exc

def norm_claims(v:Any)->dict[str,str]:
    return {str(k):str(x or "UNKNOWN").upper() for k,x in v.items()} if isinstance(v,dict) else {}

def truth_snapshot(claims:dict[str,str])->dict[str,list[str]]:
    return {
        "KNOWN":sorted(k for k,v in claims.items() if v=="SUPPORTED"),
        "CONTRADICTED":sorted(k for k,v in claims.items() if v=="REFUTED"),
        "UNKNOWN":sorted(k for k,v in claims.items() if v not in {"SUPPORTED","REFUTED"}),
    }

def card_for(daily:dict,cid:int)->dict:
    for row in daily.get("cards") or []:
        try:
            if int(row.get("candidate_id"))==cid:return row
        except Exception: pass
    return {}

def stable_evidence(rows:Any)->list[dict]:
    out=[]
    for r in rows or []:
        if not isinstance(r,dict):continue
        out.append({
            "claim_code":str(r.get("claim_code") or ""),
            "claim_state":str(r.get("claim_state") or ""),
            "stance":str(r.get("stance") or ""),
            "validated":bool(r.get("validated")),
            "source_type":str(r.get("source_type") or ""),
            "source_title":str(r.get("source_title") or ""),
            "excerpt":str(r.get("excerpt") or ""),
            "source_url":r.get("source_url"),
            "source_family_key":str(r.get("source_family_key") or ""),
        })
    return out

def projection(daily:dict,detail:dict,candidate:dict,cid:int)->dict:
    card=card_for(daily,cid)
    return {
        "candidate_id":cid,
        "case_id":detail.get("case_id"),
        "detail_claim_states":norm_claims(detail.get("claim_states")),
        "current_solutions":list(detail.get("current_solutions") or []),
        "competitive_context":list(detail.get("competitive_context") or []),
        "failure_reasons":list(detail.get("failure_reasons") or []),
        "published_evidence":stable_evidence(detail.get("published_evidence")),
        "truth_boundary":detail.get("truth_boundary"),
        "candidate_stage":candidate.get("stage"),
        "candidate_founder_status":candidate.get("founder_status"),
        "daily_card_present":bool(card),
        "daily_claims":norm_claims(card.get("claims")) if card else {},
        "verdict":card.get("verdict") if card else None,
        "decision_reason":card.get("decision_reason") if card else None,
        "biggest_unknown":card.get("biggest_unknown") if card else None,
        "market_validation_boundary":card.get("market_validation_boundary") if card else None,
    }

def source_boundary(root:Path|None)->tuple[bool,str]:
    if root is None:return False,"repo root unavailable"
    p=root/"dashboard/src/pages/CandidateDetail.tsx"
    if not p.exists():return False,"CandidateDetail.tsx missing"
    t=p.read_text(encoding="utf-8")
    checks=[
        "forgeDetail?.published_evidence" in t,
        ".filter((item: any) => item.validated)" in t,
        "...evidence.map((item: any)" not in t,
        "evidenceSolutions" not in t,
        "evidenceCompetition" not in t,
        "unvalidated candidate evidence 不會混進 handoff" in t,
    ]
    return all(checks),"validated ledger evidence only" if all(checks) else "handoff source boundary markers incomplete"

def ids_from_candidates(base:str)->list[int]:
    try: payload=call(base,"/candidates?limit=100")
    except Exception:return []
    rows=payload
    if isinstance(payload,dict):
        rows=payload.get("items") or payload.get("candidates") or payload.get("rows") or []
    if not isinstance(rows,list):return []
    out=[]
    for row in rows:
        if not isinstance(row,dict):continue
        try:cid=int(row.get("id"))
        except Exception:continue
        if cid not in out:out.append(cid)
    return out

def discover_ids(base:str,daily:dict,forced:int|None)->tuple[list[int],str]:
    if forced is not None:return [forced],"forced_candidate_id"
    ids=[]
    for row in daily.get("cards") or []:
        try:cid=int(row.get("candidate_id"))
        except Exception:continue
        if cid not in ids:ids.append(cid)
    if ids:return ids,"published_daily"
    ids=ids_from_candidates(base)
    return (ids,"problem_candidates_api") if ids else ([],"none")

def choose_candidate(base:str,daily:dict,forced:int|None):
    ids,source=discover_ids(base,daily,forced)
    if not ids:raise RuntimeError("NO_REAL_CANDIDATE_DISCOVERABLE_FROM_DAILY_OR_CANDIDATES_API")
    fallback=None
    for cid in ids[:100]:
        try:
            detail=call(base,f"/signalforge/opportunity/{cid}")
            if detail.get("status")!="OK":continue
            candidate=call(base,f"/signalforge/opportunity/{cid}/candidate")
            if candidate.get("status")=="NOT_FOUND":continue
            state=call(base,f"/signalforge/opportunity/{cid}/research-state")
        except Exception:continue
        if fallback is None:fallback=(cid,detail,candidate,state,source)
        if state.get("status")=="NOT_REGISTERED":return cid,detail,candidate,state,source
        best=state.get("best_next_research") or {}
        if state.get("status")=="OK" and (best.get("action") or best.get("gap")):
            return cid,detail,candidate,state,source
    if fallback:return fallback
    raise RuntimeError("NO_CANDIDATE_WITH_REAL_RADAR_CASE_AVAILABLE")

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-url",default=DEFAULT_BASE)
    ap.add_argument("--candidate-id",type=int)
    ap.add_argument("--research-timeout",type=int,default=900)
    ap.add_argument("--skip-research",action="store_true")
    args=ap.parse_args()
    base=args.base_url.rstrip("/")
    root=repo_root()
    report={"contract":"signalforge-usable-beta-v1.1-live-product-acceptance-fixed",
            "started_at":datetime.now(timezone.utc).isoformat(),"base_url":base,"checks":{}}
    def rec(name,passed,detail=None,required=True):
        report["checks"][name]={"pass":bool(passed),"detail":detail,"required":required}
        tag="PASS" if passed else ("INFO" if not required else "FAIL")
        print(f"{name}: {tag}"+(f" | {detail}" if detail is not None else ""))
    try:
        status=call(base,"/signalforge/status")
        rec("API_REACHABLE",isinstance(status,dict),status.get("status") if isinstance(status,dict) else None)

        daily_before=call(base,"/signalforge/daily")
        rec("PUBLISHED_DAILY_CONTEXT",isinstance(daily_before,dict),
            {"cards":len(daily_before.get("cards") or []),"status":daily_before.get("status"),"published":daily_before.get("published")},
            required=False)

        cid,detail_before,candidate_before,research_before,source=choose_candidate(base,daily_before,args.candidate_id)
        rec("REAL_OPPORTUNITY_DISCOVERED",True,{"candidate_id":cid,"source":source})
        report["candidate_id"]=cid;report["candidate_title"]=candidate_before.get("title")
        print(f"SELECTED_CANDIDATE: {cid} | {candidate_before.get('title')} | source={source}")

        claims_before=norm_claims(detail_before.get("claim_states"))
        truth=truth_snapshot(claims_before)
        rec("TRUTH_SNAPSHOT_CLASSIFICATION",
            bool(claims_before) and set(truth["KNOWN"]+truth["CONTRADICTED"]+truth["UNKNOWN"])==set(claims_before),
            {k:len(v) for k,v in truth.items()})
        report["truth_snapshot_before"]=truth

        pe=detail_before.get("published_evidence") or []
        rec("PUBLISHED_EVIDENCE_VALIDATED_ONLY",
            all(bool(r.get("validated")) for r in pe),
            {"rows":len(pe),"truth_boundary":detail_before.get("truth_boundary")})

        ok,note=source_boundary(root)
        rec("HANDOFF_SOURCE_EXCLUDES_UNVALIDATED_CANDIDATES",ok,note)

        before=projection(daily_before,detail_before,candidate_before,cid)
        report["published_before"]=before;report["shadow_before"]=research_before
        boundary=(research_before.get("published_truth_changed") is False and
                  str(research_before.get("truth_boundary") or "").startswith("SHADOW_RESEARCH"))
        rec("SHADOW_BOUNDARY_BEFORE",boundary,research_before.get("status"))

        if args.skip_research:
            rec("RESEARCH_MORE_EXECUTED",False,"SKIPPED_BY_FLAG",required=False)
            report["final_status"]="READ_ONLY_PREFLIGHT_ONLY"
        else:
            before_requests=list(research_before.get("recent_requests") or [])
            before_ids={str(x.get("request_id")) for x in before_requests if x.get("request_id")}
            print("RESEARCH_MORE: running exactly one bounded Founder-directed request; this may access live external sources...")
            rrsp=call(base,f"/signalforge/opportunity/{cid}/research-more",method="POST",timeout=args.research_timeout)
            report["research_more_response"]=rrsp
            rr=rrsp.get("request_result") or {}
            fr=rr.get("founder_requests")
            rec("RESEARCH_MORE_BOUNDED_TO_ONE",fr in {0,1} and len(rr.get("requests") or [])<=1,
                {"status":rrsp.get("status"),"founder_requests":fr})
            rec("RESEARCH_MORE_RESPONSE_SHADOW_ONLY",
                rrsp.get("published_truth_changed") is False and str(rrsp.get("truth_boundary") or "").startswith("SHADOW_RESEARCH"),
                rrsp.get("truth_boundary"))

            research_after=call(base,f"/signalforge/opportunity/{cid}/research-state")
            report["shadow_after"]=research_after
            after_requests=list(research_after.get("recent_requests") or [])
            after_ids={str(x.get("request_id")) for x in after_requests if x.get("request_id")}
            new_ids=sorted(after_ids-before_ids)
            if fr==1:
                rec("SHADOW_RESULT_VISIBLE",len(new_ids)>=1 or len(after_requests)>len(before_requests),
                    {"new_request_ids":new_ids,"recent_requests":len(after_requests)})
            else:
                best=research_after.get("best_next_research") or {}
                no_gap=not(best.get("action") or best.get("gap"))
                rec("SHADOW_RESULT_VISIBLE",no_gap,
                    "0 requests because no positive-MVOI open gap" if no_gap else "0 requests despite open gap")

            time.sleep(0.25)
            daily_after=call(base,"/signalforge/daily")
            detail_after=call(base,f"/signalforge/opportunity/{cid}")
            candidate_after=call(base,f"/signalforge/opportunity/{cid}/candidate")
            after=projection(daily_after,detail_after,candidate_after,cid)
            report["published_after"]=after
            unchanged=before==after
            delta={} if unchanged else {k:{"before":before.get(k),"after":after.get(k)} for k in before if before.get(k)!=after.get(k)}
            rec("PUBLISHED_TRUTH_UNCHANGED_AFTER_RESEARCH_MORE",unchanged,delta or "no published-field changes")

            claims_after=norm_claims(detail_after.get("claim_states"))
            high={
                "C05_BUYER_REALITY":(claims_before.get("C05"),claims_after.get("C05")),
                "C11_WTP":(claims_before.get("C11"),claims_after.get("C11")),
                "C07_UNRESOLVED_GAP":(claims_before.get("C07"),claims_after.get("C07")),
            }
            rec("HIGH_RISK_CLAIMS_NOT_AUTO_PROMOTED",all(a==b for a,b in high.values()),high)

            required=["API_REACHABLE","REAL_OPPORTUNITY_DISCOVERED","TRUTH_SNAPSHOT_CLASSIFICATION",
                      "PUBLISHED_EVIDENCE_VALIDATED_ONLY","HANDOFF_SOURCE_EXCLUDES_UNVALIDATED_CANDIDATES",
                      "SHADOW_BOUNDARY_BEFORE","RESEARCH_MORE_BOUNDED_TO_ONE","RESEARCH_MORE_RESPONSE_SHADOW_ONLY",
                      "SHADOW_RESULT_VISIBLE","PUBLISHED_TRUTH_UNCHANGED_AFTER_RESEARCH_MORE","HIGH_RISK_CLAIMS_NOT_AUTO_PROMOTED"]
            report["final_status"]="PRODUCT_ACCEPTANCE_AUTOMATED_PASS" if all(report["checks"].get(x,{}).get("pass") for x in required) else "PRODUCT_ACCEPTANCE_AUTOMATED_FAIL"
    except Exception as exc:
        report["error"]=f"{type(exc).__name__}: {exc}"
        report["final_status"]="PRODUCT_ACCEPTANCE_AUTOMATED_FAIL"
        print("ACCEPTANCE_ERROR:",report["error"])

    report["finished_at"]=datetime.now(timezone.utc).isoformat()
    outdir=root/".radar_runtime" if root is not None else Path.cwd()
    outdir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    jp=outdir/f"signalforge_usable_beta_v1_1_live_acceptance_fixed_{stamp}.json"
    mp=outdir/f"signalforge_usable_beta_v1_1_live_acceptance_fixed_{stamp}.md"
    jp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    lines=["# SignalForge Usable Beta v1.1 — Live Product Acceptance (fixed harness)","",
           f"- Final status: **{report.get('final_status')}**",f"- Candidate: `{report.get('candidate_id','?')}` — {report.get('candidate_title','')}",
           "","## Checks",""]
    for name,row in report.get("checks",{}).items():
        tag="PASS" if row.get("pass") else ("INFO" if not row.get("required",True) else "FAIL")
        lines.append(f"- {tag} — `{name}` — {row.get('detail')}")
    if report.get("error"):lines+=["","## Error","",report["error"]]
    lines+=["","## Boundary","",
            "Founder Daily snapshot absence is not a failure when a real ProblemCandidate with a RadarCase is available through the product candidate path.",
            "One Research More action must remain SHADOW and must not mutate published truth.",
            "Live Market Calibration remains 0 / UNVALIDATED."]
    mp.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("REPORT_JSON:",jp);print("REPORT_MD:  ",mp);print("FINAL_STATUS:",report.get("final_status"))
    return 0 if report.get("final_status")=="PRODUCT_ACCEPTANCE_AUTOMATED_PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
