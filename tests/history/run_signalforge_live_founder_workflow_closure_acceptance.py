#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent


def _stub_database() -> None:
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")

    class Field:
        def in_(self, *_): return self
        def is_(self, *_): return self

    class Dummy:
        id=Field(); candidate_id=Field(); claim_id=Field(); evidence_id=Field(); case_id=Field()

    for name in ("ProblemCandidate","RadarCase","RadarClaim","RadarClaimEvidence","RadarEvidence"):
        setattr(conn,name,Dummy)
    conn.async_session = None
    sys.modules["database.connection"] = conn
    setattr(db_pkg,"connection",conn)


def check(name, ok, detail=""):
    return (name, bool(ok), str(detail))


def main() -> int:
    _stub_database()
    money = importlib.import_module("processors.signalforge_money_trail")
    loop = importlib.import_module("processors.signalforge_founder_idea_loop")
    trust = importlib.import_module("processors.signalforge_trust_falsification")
    decision = importlib.import_module("processors.signalforge_opportunity_decision_closure")
    registry = importlib.import_module("processors.signalforge_founder_hypothesis_registry")
    contracts = importlib.import_module("processors.signalforge_founder_query_contracts")
    results=[]

    rfq_title="RFQ Quote Comparator"
    rfq_desc="小型採購團隊收到多家供應商的 PDF、Email、Excel 報價後，必須手動整理規格、價格、交期與條款才能比較，耗時且容易漏掉重要差異。"
    rfq=f"{rfq_title} {rfq_desc}"
    unrelated=[
        {"title":"medical clinic fax automation","problem_statement":"clinics manually process patient faxes","actor":"clinic staff","buyer_context":"healthcare clinical operations","task":"extract patient records","failure_mode":"manual processing","consequence":"staff time","workaround":"manual review"},
        {"title":"AI code review QA","problem_statement":"engineering teams manually review generated code","actor":"engineering team","buyer_context":"CTO platform QA security","task":"review code","failure_mode":"bugs","consequence":"rework","workaround":"manual QA"},
        {"title":"LinkedIn content tooling","problem_statement":"marketing teams produce LinkedIn content","actor":"marketing lead","buyer_context":"content marketing","task":"write social posts","failure_mode":"slow content","consequence":"content delay","workaround":"manual editing"},
    ]
    for row in unrelated:
        b=money.assess_founder_published_binding(rfq,row)
        results.append(check(f"RFQ rejects unrelated Published binding: {row['title']}", b.get("status")=="REJECTED" and b.get("confidence",1)<0.5, b))
    related={"title":"Supplier RFQ quote normalization","problem_statement":"procurement teams compare supplier quotes from PDF and email","actor":"procurement manager","buyer_context":"purchasing sourcing","task":"normalize quote specification terms delivery","failure_mode":"missed differences","consequence":"purchasing errors","workaround":"Excel comparison"}
    rb=money.assess_founder_published_binding(rfq,related)
    results.append(check("same RFQ problem can pass binding gate", rb.get("status")=="MATCHED", rb))

    unknown=money._unknown_direction_probe(query=rfq,title=rfq_title,binding_candidates=[])
    results.append(check("no compatible binding keeps buyer UNKNOWN", unknown.get("buyer_segment",{}).get("state")=="UNKNOWN", unknown.get("buyer_segment")))
    results.append(check("no compatible binding keeps spend UNKNOWN", unknown.get("current_spend",{}).get("status")=="UNKNOWN", unknown.get("current_spend")))
    results.append(check("no compatible binding keeps paid dissatisfaction UNKNOWN", unknown.get("paid_dissatisfaction",{}).get("status")=="UNKNOWN", unknown.get("paid_dissatisfaction")))
    results.append(check("no compatible binding cannot emit engineering next action", "engineering" not in json.dumps(unknown.get("founder_playbook") or {}).lower() and "qa" not in json.dumps(unknown.get("founder_playbook") or {}).lower(), unknown.get("founder_playbook")))

    empty_summary={"problem_discussions":0,"existing_solutions":0,"paid_signals":0,"post_purchase_complaints":0,"coverage":"COMPLETE_FOR_CONFIGURED_FAST_SOURCES","source_fit":contracts.source_fit_for_problem_class(rfq)}
    frontier=loop.build_decision_frontier(published_money_trail=unknown,fresh_summary=empty_summary)
    results.append(check("RFQ complete generic fast probe routes targeted not generic machine research", frontier.get("next_mode")=="SOURCE_FIT_RESEARCH", frontier))
    results.append(check("RFQ zero traces does not claim Published thesis kill", frontier.get("published_thesis_disposition_changed") is False and frontier.get("founder_hypothesis_disposition")=="WAIT_FOR_SOURCE_FIT" and frontier.get("unknown_resolution_state")=="SOURCE_FIT_INSUFFICIENT", frontier))
    tech_summary={**empty_summary,"source_fit":{"fit":"SUFFICIENT_FOR_BOUNDED_TECH_PROBE","problem_domains":["SOFTWARE_ENGINEERING"]}}
    tech_frontier=loop.build_decision_frontier(published_money_trail=unknown,fresh_summary=tech_summary)
    results.append(check("tech complete bounded zero probe parks Founder hypothesis", tech_frontier.get("next_mode")=="PARK_FOUNDER_HYPOTHESIS" and tech_frontier.get("founder_hypothesis_disposition")=="PARK", tech_frontier))

    # Query -> actual adapter parameter contract for all falsification lenses.
    seen=[]
    def accepted_request(url: str, **kwargs):
        u=urlparse(url); qs=parse_qs(u.query); host=u.netloc
        if "hn.algolia.com" in host:
            q=(qs.get("query") or [""])[0]
            assert q and len(q.encode("utf-8")) < 512
            assert "tags" not in qs
            seen.append(("HN",q))
            return {"hits":[]},{"status_code":200}
        if "api.github.com" in host:
            q=(qs.get("q") or [""])[0]
            base=q.replace(" is:issue","")
            assert base and len(base) < 256
            assert sum(base.upper().split().count(x) for x in ("AND","OR","NOT")) <= 5
            kind="GITHUB_ISSUES" if "/search/issues" in u.path else "GITHUB_REPOSITORIES"
            seen.append((kind,base))
            return {"items":[]},{"status_code":200,"rate_remaining":"9"}
        if "api.stackexchange.com" in host:
            seen.append(("STACK",(qs.get("q") or [""])[0]))
            return {"items":[],"quota_remaining":300},{"status_code":200}
        raise AssertionError(url)
    old=loop._request_json; loop._request_json=accepted_request
    try:
        for qrow in trust.build_falsification_queries(rfq_title,rfq_desc):
            run=trust.run_fresh_fast_probe(qrow["query"],preserve_query=True)
            results.append(check(f"all source adapters accept falsification lens {qrow['theme']}", run.get("status")=="PASS" and all(x.get("status")=="SUCCESS" for x in run.get("sources") or []), run.get("sources")))
            for src in run.get("sources") or []:
                if src.get("source") in {"HACKER_NEWS_ALGOLIA","GITHUB_ISSUES","GITHUB_REPOSITORIES"}:
                    results.append(check(f"{qrow['theme']} exposes final query for {src.get('source')}", bool(src.get("final_search_query_used")), src.get("final_search_query_used")))
    finally:
        loop._request_json=old
    results.append(check("three HN + six GitHub source requests exercised", sum(1 for x in seen if x[0]=="HN")==3 and sum(1 for x in seen if x[0].startswith("GITHUB"))==6, seen))

    # Durable Part1 -> Part4 handoff without market authority.
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        probe={"status":"PASS","fast_probe":empty_summary,"published_money_trail":unknown,"decision_frontier":frontier,"today":{"next_mode":frontier["next_mode"]},"market_truth_writes":0}
        rec=registry.record_founder_hypothesis_probe(title=rfq_title,description=rfq_desc,probe=probe,root=root)
        rows=registry.list_founder_hypotheses(root=root)
        projection=decision.founder_hypothesis_decision_projection(rows[0])
        results.append(check("Founder hypothesis durable registry round-trip", rec.get("status")=="RECORDED" and len(rows)==1 and rows[0].get("hypothesis_id")==rec.get("hypothesis_id"), rows))
        results.append(check("Part4 sees same Founder hypothesis", projection.get("title")==rfq_title and projection.get("source_kind")=="FOUNDER_HYPOTHESIS", projection))
        results.append(check("Founder hypothesis handoff preserves provenance and zero recurrence", projection.get("provenance_type")=="FOUNDER_HYPOTHESIS" and projection.get("market_authority")=="NONE" and projection.get("independent_market_recurrence_count")==0, projection))
        results.append(check("Founder hypothesis remains unvalidated market track", projection.get("market_track")=="UNVALIDATED" and projection.get("rankable_market_thesis") is False, projection))
        results.append(check("RFQ handoff route follows targeted research without wrong buyer", projection.get("decision_route")=="RESEARCH" and projection.get("existing_spend")=="UNKNOWN", projection))

    source_loop=(ROOT/'processors/signalforge_founder_idea_loop.py').read_text(encoding='utf-8')
    source_money=(ROOT/'processors/signalforge_money_trail.py').read_text(encoding='utf-8')
    source_decision=(ROOT/'processors/signalforge_opportunity_decision_closure.py').read_text(encoding='utf-8')
    results.append(check("HN adapter no longer sends OR tags filter", '"tags": "(story,comment)"' not in source_loop))
    results.append(check("GitHub adapter uses current bounded query compiler", 'compile_source_query(query, "GITHUB_ISSUES")' in source_loop and '2026-03-10' in source_loop))
    results.append(check("Published binding exposes four explicit compatibility axes", all(x in source_money for x in ('problem_semantic_compatibility','workflow_compatibility','actor_buyer_compatibility','economic_job_compatibility'))))
    results.append(check("Part4 reads durable Founder hypothesis registry", 'list_founder_hypotheses' in source_decision and 'FOUNDER_HYPOTHESIS' in source_decision))

    failed=[x for x in results if not x[1]]
    print('='*110)
    print('SIGNALFORGE LIVE FOUNDER WORKFLOW CLOSURE — ADVERSARIAL ACCEPTANCE')
    print('='*110)
    for name,ok,detail in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}" + (f" — {detail}" if (detail and not ok) else ''))
    print('-'*110)
    print(f"RESULT: {len(results)-len(failed)}/{len(results)} PASS")
    print('Market Truth writes: 0 | Founder hypothesis recurrence authority: 0')
    return 1 if failed else 0

if __name__=='__main__':
    raise SystemExit(main())
