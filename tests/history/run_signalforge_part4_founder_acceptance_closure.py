#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from processors.signalforge_opportunity_decision import build_decision_item
from processors.signalforge_opportunity_decision_closure import (
    ask_signalforge_composite,
    benchmark_batch_ingest,
    decorate_item,
    distribution_fit_gate,
    normalize_synthetic_batch,
    rerank_closure,
    structural_relationship_mapper,
    wedge_expansion_ladder,
)

ROOT=Path(__file__).resolve().parent


def thesis(tid:str,title:str,strategic:str,*,right="SUPPORTED",buyer_access="SUPPORTED",trust="LOW",distribution="SUPPORTED",zip2="NOT_ZIP2_CLASS",expansion=None):
    return {
        "thesis_id":tid,"representative_title":title,"representative_problem":title+" problem","strategic_track":strategic,
        "classification":"FIXTURE","zip2_readiness":zip2,"claim_states":{"C03":"SUPPORTED","C05":"SUPPORTED","C07":"SUPPORTED","C10":"SUPPORTED"},
        "dimensions":{
            "problem_persistence":{"state":"SUPPORTED"},"transition_strength":{"state":"SUPPORTED" if zip2!="NOT_ZIP2_CLASS" else "UNKNOWN"},
            "system_mismatch":{"state":"SUPPORTED" if zip2!="NOT_ZIP2_CLASS" else "UNKNOWN"},"economic_materiality":{"state":"SUPPORTED"},
            "workaround_intensity":{"state":"SUPPORTED"},"buyer_formation":{"state":"SUPPORTED"},"gap_durability":{"state":"SUPPORTED"},
            "asset_accessibility":{"state":"PARTIAL"},"distribution_leverage":{"state":distribution},"incumbent_response_power":{"state":"SUPPORTED"},
            "captureability":{"state":"SUPPORTED"},"expansion_surface":{"state":"SUPPORTED" if expansion else "UNKNOWN","metrics":{"candidate_wedges": expansion or []}},
        },
        "structural_thesis":{"problem":title+" problem","transition":"Agent purchasing becomes autonomous" if zip2!="NOT_ZIP2_CLASS" else None,"transition_driver":"TECHNOLOGY","system_mismatch":"Authority controls lag autonomy","wedge_type":"STRUCTURAL_TRANSITION" if zip2!="NOT_ZIP2_CLASS" else "PROVEN_MARKET_WEDGE"},
        "founder_addressability":{"trust_burden":trust,"learning_distance":"LOW","dimensions":{
            "task_capability":{"state":"SUPPORTED"},"domain_knowledge":{"state":"SUPPORTED"},"buyer_access":{"state":buyer_access},"legitimacy":{"state":"SUPPORTED"},"bridgeability":{"state":"SUPPORTED"},"right_to_win":{"state":right},
        }},
        "problem_lineage_id":"pl-"+tid,"transition_lineage_id":"tl-"+tid if zip2!="NOT_ZIP2_CLASS" else None,
        "problem_lineage_snapshot":{"lineage_id":"pl-"+tid,"representative_title":title+" lineage","representative_problem":title+" recurring problem","persistence_state":"SUPPORTED","trajectory":"PERSISTENT"},
        "transition_lineage_snapshot":{"transition_lineage_id":"tl-"+tid,"representative_text":"Agent purchasing becomes autonomous","driver":"TECHNOLOGY","state":"SUPPORTED"} if zip2!="NOT_ZIP2_CLASS" else {},
        "best_next_evidence":{"dimension":"economic_materiality","action":"FIND_DIRECT_EVIDENCE"},"market_validation":{"status":"UNVALIDATED"},
    }


def trail(tid:str,title:str,*,decision="TRY_NOW",spend="STRONG",pd=2,reach="STRONG"):
    return {
        "thesis_id":tid,"title":title,"problem":title+" problem","published_evidence_count":8,
        "claim_states":{"C03":"SUPPORTED","C05":"SUPPORTED","C07":"SUPPORTED"},
        "revenue_wedge":{"decision":decision,"existing_spend":spend,"buyer_reachability":reach},
        "paid_dissatisfaction":{"count":pd},
        "possible_revenue_wedge":{"status":"HYPOTHESIS","statement":f"Narrow paid {title} wedge"},
        "cheapest_test":{"instruction":"Show narrow prototype to 10 buyers","sample":10,"success":">=2 paid pilots","failure":"0/10 material pain"},
        "decision_frontier":{"question":"Will reachable buyers pay for the narrow wedge?"},
    }


async def fake_probe(*,title:str,description:str=""):
    return {"status":"PASS","target":{"title":title},"fast_probe":{"problem_discussions":3,"paid_signals":1},"market_truth_writes":0,"truth_boundary":"FIXTURE_UNVALIDATED_SEARCH_TRACE"}


def main()->int:
    checks=[]
    def check(name,ok,detail=None):
        checks.append((name,bool(ok),detail));print(("PASS" if ok else "FAIL").ljust(6),name,(f"— {detail}" if detail is not None else ""))

    print("="*112);print("SIGNALFORGE PART 4 — FOUNDER ACCEPTANCE CLOSURE");print("="*112)

    # 1) Distribution / Founder Fit true gate, separate from market track.
    high_trust=thesis("trust","Healthcare AI workflow","BOTH",trust="HIGH")
    high_trust_item=decorate_item(high_trust,trail("trust","Healthcare AI workflow"),build_decision_item(high_trust,trail("trust","Healthcare AI workflow")))
    check("market track remains BOTH under high trust burden", high_trust_item.get("market_track")=="BOTH", high_trust_item.get("market_track"))
    check("HIGH trust burden blocks ACTION_NOW", high_trust_item.get("founder_action")!="ACTION_NOW" and high_trust_item.get("founder_action")=="VALIDATE_DISTRIBUTION", high_trust_item.get("founder_action"))
    refuted=thesis("refuted","Regulated clinical workflow","BOTH",right="REFUTED")
    refuted_item=decorate_item(refuted,trail("refuted","Regulated clinical workflow"),build_decision_item(refuted,trail("refuted","Regulated clinical workflow")))
    check("Founder Fit REFUTED yields PARK_OR_PARTNER without rewriting BOTH", refuted_item.get("market_track")=="BOTH" and refuted_item.get("founder_action")=="PARK_OR_PARTNER", (refuted_item.get("market_track"),refuted_item.get("founder_action")))

    # 2) Real relationship mapper.
    z=thesis("agent","Agent Authority","ZIP2_STRUCTURAL",zip2="ZIP2_CANDIDATE",expansion=["Agent budget-control workspace"])
    zt=trail("agent","Agent Authority",decision="INVESTIGATE",spend="PARTIAL",pd=1)
    rel=structural_relationship_mapper(z,zt)
    node_types=[x.get("type") for x in rel.get("nodes") or []]
    check("relationship mapper has Problem→Lineage→Wedge→Structural→Transition nodes", node_types==["PROBLEM","PROBLEM_LINEAGE","SELLABLE_WEDGE","STRUCTURAL_THESIS","UNDERLYING_TRANSITION"], node_types)
    check("relationship mapper preserves lineage ids and transition evidence", any(x.get("type")=="PROBLEM_LINEAGE" and x.get("id")=="pl-agent" for x in rel["nodes"]) and any(x.get("type")=="UNDERLYING_TRANSITION" and x.get("id")=="tl-agent" for x in rel["nodes"]))

    # 3) Validation Ladder preserved + separate Wedge Expansion Ladder.
    base=build_decision_item(z,zt); dec=decorate_item(z,zt,base)
    check("existing Wedge Ladder is preserved as Validation Ladder", dec.get("validation_ladder")==dec.get("wedge_ladder") and bool(dec.get("validation_ladder")), None)
    exp=wedge_expansion_ladder(z,zt)
    check("Wedge Expansion Ladder has current/evidence/unlock/next", bool(exp.get("current_wedge")) and bool(exp.get("evidence_to_collect")) and bool(exp.get("unlock_condition")) and exp.get("possible_next_wedges",[{}])[0].get("wedge")=="Agent budget-control workspace")
    noexp=wedge_expansion_ladder(thesis("noexp","No Expansion","FAST_VALIDATION"),trail("noexp","No Expansion"))
    check("missing expansion evidence stays UNKNOWN instead of invented", noexp.get("next_wedge_status")=="UNKNOWN" and not noexp.get("possible_next_wedges"), noexp.get("next_wedge_status"))

    # 4) Synthetic provenance.
    raw=[
        {"title":"Agent Authority","provenance_type":"MODEL_HYPOTHESIS","source_model":"GPT","source_ref":"g1"},
        {"title":"Agent Authority","provenance_type":"MODEL_HYPOTHESIS","source_model":"Claude","source_ref":"c1"},
        {"title":"Agent Authority","provenance_type":"MODEL_HYPOTHESIS","source_model":"Gemini","source_ref":"m1"},
    ]
    norm=normalize_synthetic_batch(raw)
    check("multi-model same hypothesis dedupes to one synthetic hypothesis", len(norm)==1 and norm[0].get("synthetic_contributor_count")==3, (len(norm),norm[0].get("synthetic_contributor_count")))
    check("synthetic convergence never counts as market recurrence", norm[0].get("independent_market_recurrence_count")==0 and norm[0].get("market_authority")=="NONE", norm[0].get("independent_market_recurrence_count"))

    # 5) Raw benchmark batch ingestion: provenance → dedupe → probe → lineage → route.
    portfolio=[z,{"thesis_id":"rfq","representative_title":"RFQ Comparator","representative_problem":"Normalize supplier quotes"}]
    batch=asyncio.run(benchmark_batch_ingest(raw+[{"title":"RFQ Comparator","description":"Normalize supplier quotes","provenance_type":"FOUNDER_HYPOTHESIS","source_ref":"f1"}],run_probe=True,probe_runner=fake_probe,portfolio_items=portfolio))
    check("benchmark batch dedupes raw hypotheses and probes every deduped item", batch.get("input_count")==4 and batch.get("deduped_count")==2 and all(x.get("probe") for x in batch.get("items") or []), (batch.get("input_count"),batch.get("deduped_count")))
    check("benchmark batch attaches lineage candidate and bounded route", all(x.get("route") in {"EXISTING_THESIS_REVIEW","PROBE_REVIEW"} for x in batch.get("items") or []) and any(x.get("possible_lineage_match") for x in batch.get("items") or []))
    check("benchmark batch creates zero Market Truth writes", batch.get("market_truth_writes")==0 and all(x.get("independent_market_recurrence_count")==0 for x in batch.get("items") or []))

    # 6) Ask composite filtering reproduces independent review bug: B must be excluded if buyer unreachable.
    a=thesis("a","A","FAST_VALIDATION",buyer_access="SUPPORTED")
    b=thesis("b","B","FAST_VALIDATION",buyer_access="REFUTED")
    ia=decorate_item(a,trail("a","A",pd=2),build_decision_item(a,trail("a","A",pd=2)))
    ib=decorate_item(b,trail("b","B",pd=2),build_decision_item(b,trail("b","B",pd=2)))
    comp=rerank_closure([ia,ib])
    ask=ask_signalforge_composite("哪些方向同時有 existing spend、paid dissatisfaction、reachable buyer？",comp)
    ids=[x.get("thesis_id") for x in ask.get("matches") or []]
    check("Ask uses logical AND for composite predicates", ask.get("composite") is True and set(ask.get("predicates") or []) >= {"EXISTING_SPEND","PAID_DISSATISFACTION","REACHABLE_BUYER"}, ask.get("predicates"))
    check("Ask excludes spend-positive but unreachable buyer", ids==["a"], ids)

    # 7) UI separates Market Track vs Founder Actionability and exposes closure features.
    page=(ROOT/'dashboard/src/pages/DecisionSystem.tsx').read_text(encoding='utf-8')
    api=(ROOT/'api/routes/signalforge.py').read_text(encoding='utf-8')
    client=(ROOT/'dashboard/src/api/client.ts').read_text(encoding='utf-8')
    check("UI separates Market Track from Founder Action", 'Market ·' in page and 'Founder ·' in page and 'Founder Actionability Gate' in page)
    check("UI names Validation Ladder and separate Wedge Expansion Ladder", 'Validation Ladder' in page and 'Wedge Expansion Ladder' in page)
    check("UI exposes Problem↔Structural Thesis relationship mapper", 'Problem ↔ Structural Thesis Mapper' in page)
    check("UI exposes raw Benchmark Batch with synthetic provenance warning", 'Benchmark Batch · Synthetic provenance' in page and 'independent market recurrence' in page)
    check("API exposes bounded benchmark batch endpoint", "/decision/benchmark-batch" in api and "bounded to 60" in api)
    check("client exposes benchmark batch workflow", 'signalforgeBenchmarkBatch' in client)
    check("all closure decision projections keep Market Truth writes zero", all(x.get("market_truth_writes")==0 for x in [high_trust_item,refuted_item,dec,ask,batch]))

    failed=[x for x in checks if not x[1]]
    print('-'*112);print(f"RESULT: {len(checks)-len(failed)}/{len(checks)} PASS")
    if failed:
        for name,_,detail in failed: print('FAILED:',name,detail)
        return 1
    print('FINAL_STATUS: SIGNALFORGE_PART4_FOUNDER_ACCEPTANCE_CLOSURE_PASS')
    return 0


if __name__=='__main__': raise SystemExit(main())
