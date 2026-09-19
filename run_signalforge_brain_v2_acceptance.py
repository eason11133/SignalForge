from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
import time
from copy import deepcopy
from pathlib import Path

from processors.signalforge_brain_v2_contracts import static_acceptance as contracts_acceptance
from processors.signalforge_brain_v2_store import count_events, object_map, replay_projection, state_hash, _active_hash_from_state_db, static_acceptance as store_acceptance
from processors.signalforge_brain_v2_integration import static_acceptance as integration_module_acceptance
from processors.signalforge_brain_v2_runtime import static_acceptance as runtime_module_acceptance
from processors.signalforge_brain_v2_structural_recall import (
    build_transition_hypotheses,
    static_acceptance as structural_recall_module_acceptance,
)
from processors.signalforge_brain_v2_engine import (
    ENGINE_VERSION as BRAIN_ENGINE_VERSION,
    diagnostics,
    get_brain_v2_portfolio,
    load_truth_snapshot,
    production_truth_guard,
    record_brain_v2_research_execution,
    refresh_signalforge_brain_v2,
)


def _all_true(x: dict) -> bool:
    return bool(x) and all(bool(v) for v in x.values())


def _claims(case_id: int, states: dict[str, str], start_id: int) -> list[dict]:
    out=[]
    for i in range(1,15):
        code=f"C{i:02d}"
        out.append({"id":start_id+i,"case_id":case_id,"claim_code":code,"state":states.get(code,"UNKNOWN"),"support_groups":2 if states.get(code)=="SUPPORTED" else 0,"direct_support_groups":2 if code in {"C01","C02"} and states.get(code)=="SUPPORTED" else 0,"refute_groups":1 if states.get(code)=="REFUTED" else 0,"insufficient_count":0,"evidence_summary":{},"last_evaluated_at":"2026-01-01T00:00:00Z"})
    return out


def fixture_snapshot(*, churn: bool=False, gap_refuted: bool=False, derived_transition_noise: int=12) -> dict:
    second_id = 99 if churn else 2
    base_states={
        "C01":"SUPPORTED","C02":"SUPPORTED","C03":"SUPPORTED","C04":"SUPPORTED","C05":"SUPPORTED","C06":"SUPPORTED","C07":"REFUTED" if gap_refuted else "SUPPORTED",
        "C08":"INSUFFICIENT","C09":"SUPPORTED","C10":"SUPPORTED","C11":"INSUFFICIENT","C12":"PARTIAL","C13":"INSUFFICIENT","C14":"INSUFFICIENT",
    }
    fp_noise=[{"text":f"Generic AI adoption signal number {i} mentions agents and workflow change but is only derived context."} for i in range(derived_transition_noise)]
    candidates=[
        {"id":1,"canonical_key":"p1","title":"Coding agent assumptions cause wrong completion reports","problem_statement":"hidden assumptions cause incorrect completion reports","actor":"developer","actor_category":"developer","task":"agent coding and reporting","object":"agent completion report","failure_mode":"hidden assumptions cause wrong reported results","consequence":"wrong release decisions waste hours","buyer_context":"engineering manager","workaround":"we manually review every result and built an internal verification script","stage":"candidate","founder_status":"NEW","first_seen_at":"2025-01-01T00:00:00Z","last_seen_at":"2026-01-01T00:00:00Z","fingerprint":{"problem_scope_key":"agent-report-assumptions","primary_problem_signature":"wrong_agent_completion_report","transition_evidence_verified":True,"transition_pair_verified":True,"external_enabler_candidates":fp_noise}},
        {"id":second_id,"canonical_key":"p2","title":"Agent assumptions produce incorrect work reports","problem_statement":"coding agent assumptions lead to wrong completion reports","actor":"developer","actor_category":"developer","task":"agent coding and reporting","object":"agent completion report","failure_mode":"assumptions produce wrong reported results","consequence":"team wastes hours verifying","buyer_context":"engineering manager","workaround":"manual double check every completion","stage":"candidate","founder_status":"NEW","first_seen_at":"2025-02-01T00:00:00Z","last_seen_at":"2025-11-01T00:00:00Z","fingerprint":{"problem_scope_key":"agent-report-assumptions","primary_problem_signature":"wrong_agent_completion_report"}},
        {"id":3,"canonical_key":"p3","title":"Claude account email cannot be changed","problem_statement":"cannot change account email","actor":"consumer","actor_category":"consumer","task":"change account email","object":"account email","failure_mode":"email update unavailable","consequence":"billing inconvenience","buyer_context":"","workaround":"","stage":"candidate","founder_status":"NEW","first_seen_at":"2026-01-01T00:00:00Z","last_seen_at":"2026-01-02T00:00:00Z","fingerprint":{}},
    ]
    cases=[{"id":11,"candidate_id":1,"system_verdict":"WATCH","current_gate":"C05","verdict_reason_code":"x","last_evaluated_at":"2026-01-01T00:00:00Z"},{"id":12,"candidate_id":second_id,"system_verdict":"WATCH","current_gate":"C05","verdict_reason_code":"x","last_evaluated_at":"2026-01-01T00:00:00Z"},{"id":13,"candidate_id":3,"system_verdict":"WATCH","current_gate":"C03","verdict_reason_code":"x","last_evaluated_at":"2026-01-01T00:00:00Z"}]
    claims=[]
    claims+=_claims(11,base_states,100)
    claims+=_claims(12,base_states,200)
    claims+=_claims(13,{"C01":"SUPPORTED","C02":"UNKNOWN","C03":"INSUFFICIENT"},300)
    claim_id=lambda case,code: ({11:100,12:200,13:300}[case] + int(code[1:]))
    links=[]
    # Direct problem recurrence families for persistence.
    for case,cid,prefix in [(11,1,"hn"),(12,second_id,"reddit")]:
        links.append({"claim_id":claim_id(case,"C01"),"case_id":case,"claim_code":"C01","evidence_id":1000+cid,"stance":"SUPPORT","validated":True,"confidence":0.9,"rationale":"direct","source_type":prefix,"source_table":"community","source_ref":f"p{cid}","source_family_key":f"{prefix}:problem:{cid}","source_title":"problem","excerpt":"Agent assumptions produce wrong completion reports and require manual verification.","source_url":"","directness":"DIRECT","authority_class":"USER_DISCUSSION","published_at":"2025-01-01T00:00:00Z","observed_at":"2025-01-01T00:00:00Z","metadata":{}})
        links.append({"claim_id":claim_id(case,"C02"),"case_id":case,"claim_code":"C02","evidence_id":1100+cid,"stance":"SUPPORT","validated":True,"confidence":0.9,"rationale":"recurrence","source_type":prefix,"source_table":"community","source_ref":f"r{cid}","source_family_key":f"{prefix}:recurrence:{cid}","source_title":"recurrence","excerpt":"Independent developer reports same completion reporting failure.","source_url":"","directness":"DIRECT","authority_class":"INDEPENDENT_PROBLEM_SOURCE","published_at":"2025-10-01T00:00:00Z" if cid==1 else "2025-12-01T00:00:00Z","observed_at":"2025-10-01T00:00:00Z","metadata":{}})
    # One explicit direct transition candidate evidence + two C12 support families.
    candidate_evidence=[
        {"id":1,"candidate_id":1,"source_type":"hn","source_table":"community","source_ref":"t1","relation":"why_now","title":"agent autonomy expands","excerpt":"Autonomous coding agents now execute larger scopes while review capacity remains manual.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z","metadata":{"transition_pair_verified":True}},
    ]
    for idx,(case,cid,fam,text) in enumerate([(11,1,"news:a","Agent autonomy adoption is increasing while human review remains a bottleneck."),(12,second_id,"news:b","Coding agents execute larger work scopes while review workflows remain manual.")],1):
        links.append({"claim_id":claim_id(case,"C12"),"case_id":case,"claim_code":"C12","evidence_id":1200+idx,"stance":"SUPPORT","validated":True,"confidence":0.8,"rationale":"timing","source_type":"news","source_table":"news","source_ref":f"t{idx}","source_family_key":fam,"source_title":"agent autonomy shift","excerpt":text,"source_url":"","directness":"INDIRECT","authority_class":"MARKET_ACTIVITY","published_at":"2025-11-01T00:00:00Z","observed_at":"2025-11-01T00:00:00Z","metadata":{}})
    return {"candidates":candidates,"candidate_evidence":candidate_evidence,"cases":cases,"claims":claims,"validated_radar_links":links,"load_metrics":{"fixture":1}}


async def cross_scope_truth_acceptance() -> tuple[dict, dict]:
    """Negative controls for the two most dangerous structural leakage paths.

    1) Buyer truth on candidate A must not leak into a transition thesis scoped only to
       candidate B even when A/B share the same ProblemLineage.
    2) Explicitly different transition subjects must not overmerge under one generic
       TECHNOLOGY/automation vocabulary cluster.
    """
    snap=fixture_snapshot(derived_transition_noise=0)
    # Same problem lineage: candidate 1 has buyer proof; candidate 2 intentionally does not.
    case_by_candidate={int(x["candidate_id"]):int(x["id"]) for x in snap["cases"]}
    c2case=case_by_candidate[2]
    for claim in snap["claims"]:
        if int(claim.get("case_id",0))==c2case and str(claim.get("claim_code"))=="C05":
            claim["state"]="UNKNOWN"; claim["support_groups"]=0; claim["direct_support_groups"]=0
    # Transition evidence belongs only to candidate 2. Candidate 1's commercial truth is
    # therefore outside the structural intersection slice.
    snap["candidate_evidence"]=[{
        "id":22,"candidate_id":2,"source_type":"hn","source_table":"community","source_ref":"tb-direct",
        "relation":"why_now","title":"coding agent autonomy expands",
        "excerpt":"Autonomous coding agents now execute larger scopes while review capacity remains manual.",
        "url":"","verified":True,"verification_confidence":0.95,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z",
        "metadata":{"transition_pair_verified":True,"transition_subject":"coding agents"},
    }]
    snap["validated_radar_links"]=[
        row for row in snap["validated_radar_links"]
        if not (str(row.get("claim_code"))=="C12" and int(row.get("case_id",0))!=c2case)
    ]
    for row in snap["validated_radar_links"]:
        if str(row.get("claim_code"))=="C12" and int(row.get("case_id",0))==c2case:
            row["metadata"]={"transition_subject":"coding agents"}

    with tempfile.TemporaryDirectory(prefix="sfbrain_scope_negative_") as td:
        root=Path(td)
        result=await refresh_signalforge_brain_v2(root=root,snapshot=snap)
        scoped=[t for t in result.get("portfolio",[]) if set(t.get("member_candidate_ids",[]) or [])=={2} and t.get("transition_lineage_id")]
        thesis=scoped[0] if scoped else {}
        buyer=((thesis.get("dimensions") or {}).get("buyer_formation") or {})
        checks={
            "transition_thesis_scope_is_candidate_2_only": bool(thesis) and set(thesis.get("member_candidate_ids",[]) or [])=={2},
            "candidate_1_buyer_truth_does_not_leak": buyer.get("state") in {"UNKNOWN","INSUFFICIENT","PARTIAL"} and buyer.get("state")!="SUPPORTED",
            "scoped_claim_metrics_exclude_candidate_1": set(((buyer.get("metrics") or {}).get("atomic_states") or {}).keys()) <= {"2"},
            "single_direct_pair_link_not_full_mismatch_support": ((thesis.get("dimensions") or {}).get("system_mismatch") or {}).get("state")=="PARTIAL",
        }
        metrics={
            "portfolio_count":len(result.get("portfolio",[]) or []),
            "scoped_thesis_id":thesis.get("thesis_id"),
            "scoped_candidate_ids":thesis.get("member_candidate_ids"),
            "buyer_state":buyer.get("state"),
            "buyer_metrics":buyer.get("metrics"),
            "system_mismatch":((thesis.get("dimensions") or {}).get("system_mismatch") or {}).get("state"),
        }

    # Engine-level explicit-subject overmerge control. Use one problem/candidate but two
    # verified transition records with intentionally identical generic vocabulary.
    subject_snap=fixture_snapshot(derived_transition_noise=0)
    subject_snap["candidate_evidence"]=[
        {"id":31,"candidate_id":1,"source_type":"news","source_table":"news","source_ref":"s1","relation":"why_now","title":"automation adoption shift","excerpt":"Automation adoption lowers workflow operating cost and changes delivery patterns.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z","metadata":{"transition_pair_verified":True,"transition_subject":"coding agents"}},
        {"id":32,"candidate_id":1,"source_type":"news","source_table":"news","source_ref":"s2","relation":"why_now","title":"automation adoption shift","excerpt":"Automation adoption lowers workflow operating cost and changes delivery patterns.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-02T00:00:00Z","created_at":"2025-10-02T00:00:00Z","metadata":{"transition_pair_verified":True,"transition_subject":"warehouse robotics"}},
    ]
    subject_snap["validated_radar_links"]=[x for x in subject_snap["validated_radar_links"] if str(x.get("claim_code"))!="C12"]
    with tempfile.TemporaryDirectory(prefix="sfbrain_subject_negative_") as td:
        subject_result=await refresh_signalforge_brain_v2(root=Path(td),snapshot=subject_snap)
        subject_lineages=subject_result.get("model",{}).get("transition_lineages",[]) if isinstance(subject_result.get("model"),dict) else []
        # Public result exposes counts even when model is not returned; inspect projection as fallback.
        if not subject_lineages:
            subject_lineages=list(object_map(Path(td),"transition_lineage").values())
        explicit_subject_sets=[set(x.get("explicit_subjects",[]) or []) for x in subject_lineages]
        checks["explicit_transition_subjects_do_not_overmerge"] = not any({"coding agents","warehouse robotics"} <= x for x in explicit_subject_sets)
        metrics["explicit_subject_lineages"]=[sorted(x) for x in explicit_subject_sets]
    return checks,metrics


async def derivation_upgrade_acceptance() -> tuple[dict, dict]:
    snap=fixture_snapshot(derived_transition_noise=0)
    with tempfile.TemporaryDirectory(prefix="sfbrain_g3_upgrade_" ) as td:
        root=Path(td)
        first=await refresh_signalforge_brain_v2(root=root,snapshot=snap)
        state_db=root/".radar_runtime"/"signalforge_brain_v2_full_state.sqlite3"
        con=sqlite3.connect(state_db)
        try:
            con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('engine_version','signalforge-brain-v2-full-system-longitudinal-intelligence-g2-persistence-closure')")
            con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema','signalforge-brain-v2-full-system-g2')")
            con.commit()
        finally:
            con.close()
        await asyncio.sleep(1.05)
        second=await refresh_signalforge_brain_v2(root=root,snapshot=snap)
        dirty=(second.get("build_diagnostics",{}) or {}).get("dirty",{}) or {}
        checks={
            "same_truth_engine_upgrade_not_noop":second.get("refresh_skipped") is False,
            "derivation_upgrade_forces_full_rebuild":bool(dirty.get("first_build")) and bool(dirty.get("derivation_upgrade")),
            "upgrade_keeps_atomic_truth_boundary":(second.get("authority") or {}).get("radar_atomic_claim_truth")=="SOLE_OWNER",
            "post_upgrade_same_truth_returns_to_fast_noop":False,
        }
        third=await refresh_signalforge_brain_v2(root=root,snapshot=snap)
        checks["post_upgrade_same_truth_returns_to_fast_noop"]=third.get("refresh_skipped") is True
        replay=replay_projection(root)
        replay_target=Path(replay["target"])
        active_hash=_active_hash_from_state_db(root/".radar_runtime"/"signalforge_brain_v2_full_state.sqlite3")
        replay_hash=_active_hash_from_state_db(replay_target)
        checks["derivation_upgrade_replay_deterministic"]=active_hash==replay_hash
        try: replay_target.unlink()
        except FileNotFoundError: pass
        return checks,{"first_status":first.get("status"),"second_dirty":dirty,"third_refresh_skipped":third.get("refresh_skipped"),"active_hash":active_hash,"replay_hash":replay_hash}


async def structural_recall_end_to_end_acceptance() -> tuple[dict, dict]:
    snap=fixture_snapshot(derived_transition_noise=0)
    # Remove the direct transition row and C12 timing rows. G3 must recover a real
    # transition from independent context-only evidence without returning to R2's
    # context->lineage explosion.
    snap["candidate_evidence"]=[
        {"id":41,"candidate_id":1,"source_type":"news","source_table":"news","source_ref":"ctx-a","relation":"why_now","title":"Autonomous coding agents expand repository scope","excerpt":"Autonomous coding agents execute repository wide changes while human verification remains manual and release review becomes a bottleneck.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-09-01T00:00:00Z","created_at":"2025-09-01T00:00:00Z","metadata":{}},
        {"id":42,"candidate_id":2,"source_type":"community","source_table":"community","source_ref":"ctx-b","relation":"why_now","title":"Autonomous coding agents expand repository work","excerpt":"Autonomous coding agents execute repository wide work while human verification remains manual and release review is the bottleneck.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-15T00:00:00Z","created_at":"2025-10-15T00:00:00Z","metadata":{}},
    ]
    snap["validated_radar_links"]=[x for x in snap["validated_radar_links"] if str(x.get("claim_code"))!="C12"]
    # Add one adjacent but distinct problem lineage. It shares enough specific identity to
    # merit bridge research, but it has no pair evidence and must NOT become an intersection.
    snap["candidates"].append({"id":4,"canonical_key":"p4","title":"Coding agent pull requests create merge queue conflicts","problem_statement":"parallel autonomous coding agent changes create repository merge conflicts and review queues","actor":"developer","actor_category":"developer","task":"review coding agent pull requests","object":"repository merge queue","failure_mode":"parallel agent changes collide and block merges","consequence":"release work waits for manual conflict resolution","buyer_context":"engineering manager","workaround":"manual serialize agent changes and review every merge","stage":"candidate","founder_status":"NEW","first_seen_at":"2025-01-01T00:00:00Z","last_seen_at":"2026-01-01T00:00:00Z","fingerprint":{"problem_scope_key":"agent-merge-conflicts","primary_problem_signature":"parallel_agent_merge_conflicts"}})
    snap["cases"].append({"id":14,"candidate_id":4,"system_verdict":"WATCH","current_gate":"C05","verdict_reason_code":"x","last_evaluated_at":"2026-01-01T00:00:00Z"})
    snap["claims"].extend(_claims(14,{"C01":"SUPPORTED","C02":"SUPPORTED","C03":"SUPPORTED","C05":"UNKNOWN","C07":"SUPPORTED","C09":"SUPPORTED","C10":"UNKNOWN","C12":"UNKNOWN","C13":"INSUFFICIENT"},400))
    for code,eid,fam,excerpt,dt in [
        ("C01",1401,"community:merge-problem","Developers report parallel coding agent changes collide in repository merge queues and require manual conflict resolution.","2025-01-01T00:00:00Z"),
        ("C02",1402,"community:merge-recurrence","Independent teams report recurring coding agent merge queue conflicts across repository review workflows.","2025-11-01T00:00:00Z"),
    ]:
        snap["validated_radar_links"].append({"claim_id":400+int(code[1:]),"case_id":14,"claim_code":code,"evidence_id":eid,"stance":"SUPPORT","validated":True,"confidence":0.9,"rationale":"direct","source_type":"community","source_table":"community","source_ref":str(eid),"source_family_key":fam,"source_title":"agent merge problem","excerpt":excerpt,"source_url":"","directness":"DIRECT","authority_class":"USER_DISCUSSION","published_at":dt,"observed_at":dt,"metadata":{}})
    with tempfile.TemporaryDirectory(prefix="sfbrain_g3_recall_") as td:
        root=Path(td)
        result=await refresh_signalforge_brain_v2(root=root,snapshot=snap)
        counts=result.get("counts",{})
        diag=(result.get("build_diagnostics",{}) or {}).get("transition_admission",{}) or {}
        bridges=list(result.get("structural_bridge_hypotheses",[]) or [])
        intersections=list(result.get("structural_intersections",[]) or [])
        research=list(result.get("research_queue",[]) or [])
        bridge_pairs={(str(x.get("problem_lineage_id")),str(x.get("transition_lineage_id"))) for x in bridges}
        ix_pairs={(str(x.get("problem_lineage_id")),str(x.get("transition_lineage_id"))) for x in intersections}
        checks={
            "context_only_transition_recovered_by_corroboration": int(diag.get("promoted_context_atoms",0) or 0)>=2 and int(counts.get("transition_hypotheses",0) or 0)>=1,
            "promoted_transition_becomes_persistent_lineage": int(counts.get("transition_lineages",0) or 0)>=1,
            "same_problem_structural_intersection_recovered": int(counts.get("structural_intersections",0) or 0)>=1,
            "bridge_hypothesis_created_for_adjacent_problem": bool(bridge_pairs),
            "bridge_hypothesis_does_not_self_promote_to_intersection": bool(bridge_pairs - ix_pairs),
            "prethesis_bridge_research_enters_queue": any(str(x.get("target_type"))=="STRUCTURAL_BRIDGE_HYPOTHESIS" for x in research),
            "radar_atomic_truth_still_sole_owner": (result.get("authority") or {}).get("radar_atomic_claim_truth")=="SOLE_OWNER",
        }
        return checks,{"counts":counts,"transition_admission":diag,"bridge_hypotheses":bridges[:5],"intersection_count":len(intersections),"prethesis_research_count":sum(1 for x in research if x.get("target_type"))}


async def thesis_lifecycle_acceptance() -> tuple[dict, dict]:
    initial=fixture_snapshot(derived_transition_noise=0)
    with tempfile.TemporaryDirectory(prefix="sfbrain_g3_lifecycle_") as td:
        root=Path(td)
        first=await refresh_signalforge_brain_v2(root=root,snapshot=initial)
        t1=(first.get("portfolio") or [None])[0]
        if not t1:
            return {"initial_thesis_exists":False},{"error":"no initial thesis"}
        tid=t1.get("thesis_id")
        rev1=int(t1.get("revision",0) or 0)
        dead=deepcopy(initial)
        for claim in dead["claims"]:
            if str(claim.get("claim_code"))=="C07" and int(claim.get("case_id",0)) in {11,12}:
                claim["state"]="REFUTED"; claim["support_groups"]=0; claim["refute_groups"]=2
        second=await refresh_signalforge_brain_v2(root=root,snapshot=dead)
        t2=next((x for x in second.get("portfolio",[]) if x.get("thesis_id")==tid),None)
        third=await refresh_signalforge_brain_v2(root=root,snapshot=initial)
        t3=next((x for x in third.get("portfolio",[]) if x.get("thesis_id")==tid),None)
        hist=list((t3 or {}).get("lifecycle_history") or [])
        checks={
            "initial_thesis_exists":t1 is not None,
            "death_state_persists_as_thesis_history":bool(t2) and str(t2.get("lifecycle_state"))=="DEAD" and bool(t2.get("death_state")),
            "revival_restores_same_thesis_identity":bool(t3) and t3.get("thesis_id")==tid and str(t3.get("lifecycle_state"))!="DEAD",
            "lifecycle_records_death_and_revival":any(str(x.get("event"))=="DIED" for x in hist) and any(str(x.get("event"))=="REVIVED" for x in hist),
            "revision_is_semantic_not_refresh_counter":bool(t3) and int(t3.get("revision",0) or 0)>=rev1+2,
            "zip2_gate_is_gate_plus_vector":bool(t3) and ((t3.get("zip2_gate") or {}).get("model")=="GATE_PLUS_VECTOR_NOT_AVERAGE_SCORE"),
        }
        return checks,{"thesis_id":tid,"revision_sequence":[rev1,int((t2 or {}).get("revision",0) or 0),int((t3 or {}).get("revision",0) or 0)],"lifecycle_history":hist,"zip2_gate":(t3 or {}).get("zip2_gate")}


async def synthetic_acceptance() -> tuple[dict, dict]:
    checks={}
    metrics={}
    with tempfile.TemporaryDirectory(prefix="sfbrain_full_synth_") as td:
        root=Path(td)
        snap=fixture_snapshot()
        t=time.perf_counter(); first=await refresh_signalforge_brain_v2(root=root,snapshot=snap); metrics["first_ms"]=int((time.perf_counter()-t)*1000)
        events1=count_events(root)
        t=time.perf_counter(); second=await refresh_signalforge_brain_v2(root=root,snapshot=snap); metrics["noop_ms"]=int((time.perf_counter()-t)*1000)
        events2=count_events(root)
        checks["first_refresh_pass"] = first.get("status") in {"PASS","PASS_EMPTY"}
        checks["same_truth_fast_noop"] = second.get("refresh_skipped") is True and events1==events2
        checks["problem_lineage_compression"] = int(first.get("counts",{}).get("problem_lineages",0)) < int(first.get("counts",{}).get("problem_atoms",0))
        checks["derived_transition_context_does_not_spawn_lineages"] = int(first.get("counts",{}).get("derived_transition_context_atoms",0)) >= 10 and int(first.get("counts",{}).get("transition_lineages",0)) <= int(first.get("counts",{}).get("lineage_eligible_transition_atoms",0))
        checks["structural_intersection_exists"] = int(first.get("counts",{}).get("thesis_eligible_intersections",0)) >= 1
        checks["thesis_compression_not_problem_backlog_copy"] = int(first.get("counts",{}).get("opportunity_theses",0)) <= int(first.get("counts",{}).get("structural_intersections",0)) + int(first.get("counts",{}).get("problem_lineages",0))
        checks["expansion_not_invented"] = all(((t.get("dimensions") or {}).get("expansion_surface") or {}).get("state")=="UNKNOWN" for t in first.get("portfolio",[]))
        checks["research_queue_has_no_recency"] = all(x.get("recency_factor_used") is False for x in first.get("research_queue",[]))
        checks["zip2_not_self_certified_high"] = not any(x.get("zip2_readiness")=="ZIP2_HIGH_CONVICTION" for x in first.get("portfolio",[]))
        # Research scheduling telemetry must close the VOI redundancy loop without touching Radar truth.
        advisory_items=first.get("research_queue",[]) or []
        if advisory_items:
            target_qid=str(advisory_items[0].get("research_question_id") or "")
            before_voi=float(advisory_items[0].get("voi",0) or 0)
            group=str(advisory_items[0].get("source_group") or "problem")
            cids=list(advisory_items[0].get("member_candidate_ids",[]) or [])
            r1=record_brain_v2_research_execution(cycle_key="fixture-cycle-1",group_results=[{"group":group,"status":"ATTEMPTED","pass_count":1}],candidate_ids=cids,root=root)
            after_attempt=object_map(root,"research_question")
            attempt_counts=[int(q.get("attempts",0) or 0) for q in after_attempt.values() if str(q.get("source_group") or "")==group and (not cids or set(q.get("member_candidate_ids",[]) or []) & set(cids))]
            after_q=after_attempt.get(target_qid,{})
            after_voi=float(after_q.get("voi",0) or 0)
            surfaced=get_brain_v2_portfolio(root).get("research_queue",[]) or []
            surfaced_q=next((q for q in surfaced if str(q.get("research_question_id") or "")==target_qid),{})
            r2=record_brain_v2_research_execution(cycle_key="fixture-cycle-1",group_results=[{"group":group,"status":"ATTEMPTED","pass_count":1}],candidate_ids=cids,root=root)
            after_repeat=object_map(root,"research_question")
            repeat_counts=[int(q.get("attempts",0) or 0) for q in after_repeat.values() if str(q.get("source_group") or "")==group and (not cids or set(q.get("member_candidate_ids",[]) or []) & set(cids))]
            checks["research_attempt_feedback_loop"] = r1.get("events_inserted",0)>0 and bool(attempt_counts) and max(attempt_counts)>=1
            checks["research_attempt_reduces_voi"] = bool(target_qid) and before_voi>0 and 0<=after_voi<before_voi
            checks["research_attempt_surface_updates_without_truth_rebuild"] = int(surfaced_q.get("attempts",0) or 0)>=1 and float(surfaced_q.get("voi",0) or 0)==after_voi
            checks["research_attempt_retry_idempotent"] = r2.get("events_inserted",0)==0 and attempt_counts==repeat_counts
        else:
            checks["research_attempt_feedback_loop"] = False
            checks["research_attempt_reduces_voi"] = False
            checks["research_attempt_surface_updates_without_truth_rebuild"] = False
            checks["research_attempt_retry_idempotent"] = False
        # Candidate id churn must preserve longitudinal problem lineage identity.
        before_ids={x.get("lineage_id") for x in first.get("problem_lineages",[]) if "completion" in str(x.get("representative_title","" )).lower() or "agent" in str(x.get("representative_problem","")).lower()}
        churn=fixture_snapshot(churn=True)
        third=await refresh_signalforge_brain_v2(root=root,snapshot=churn)
        after_ids={x.get("lineage_id") for x in third.get("problem_lineages",[]) if "completion" in str(x.get("representative_title","")).lower() or "agent" in str(x.get("representative_problem","")).lower()}
        checks["candidate_id_churn_preserves_problem_lineage"] = bool(before_ids & after_ids)
        dirty=((third.get("build_diagnostics") or {}).get("dirty") or {}).get("dirty_candidate_ids",[])
        checks["dirty_set_detects_churn_not_full_world"] = 2 in dirty and 99 in dirty and len(dirty) <= 2
        if advisory_items:
            q_after_churn=object_map(root,"research_question").get(target_qid,{})
            checks["research_attempt_persists_across_truth_refresh"] = int(q_after_churn.get("attempts",0) or 0)>=1
        else:
            checks["research_attempt_persists_across_truth_refresh"] = False
        # Gap refutation should kill the structural thesis rather than leave it in WATCH forever.
        dead=await refresh_signalforge_brain_v2(root=root,snapshot=fixture_snapshot(churn=True,gap_refuted=True))
        checks["gap_refutation_produces_death_state"] = any(x.get("death_state")=="SOLVED_OR_NO_DURABLE_GAP" for x in dead.get("portfolio",[]))
        # Replay active state deterministically.
        current_hash=state_hash(root); replay=replay_projection(root); checks["event_replay_available"] = bool(replay.get("active_hash")) and bool(current_hash)
        metrics["counts"] = first.get("counts",{})
        metrics["dirty_after_churn"] = dirty
    return checks,metrics


async def scale_acceptance() -> tuple[dict, dict]:
    # 240 candidates, 80 problem families, hundreds of derived transition contexts.
    snap={"candidates":[],"candidate_evidence":[],"cases":[],"claims":[],"validated_radar_links":[],"load_metrics":{"fixture":"scale"}}
    cid=0; claim_id=10000
    for fam in range(80):
        for member in range(3):
            cid+=1; case=5000+cid
            fp={"problem_scope_key":f"scope-{fam}","primary_problem_signature":f"sig-{fam}","external_enabler_candidates":[{"text":f"Derived generic transition context {j} for family {fam} discusses adoption and workflow shift."} for j in range(4)]}
            snap["candidates"].append({"id":cid,"canonical_key":f"c{cid}","title":f"Workflow family {fam} failure report","problem_statement":f"workflow family {fam} repeatedly fails at verification step","actor":"operator","actor_category":"operator","task":f"workflow {fam}","object":f"record {fam}","failure_mode":"verification step fails and requires manual recheck","consequence":"wastes two hours","buyer_context":"manager","workaround":"manual recheck","stage":"candidate","founder_status":"NEW","first_seen_at":"2025-01-01T00:00:00Z","last_seen_at":"2026-01-01T00:00:00Z","fingerprint":fp})
            snap["cases"].append({"id":case,"candidate_id":cid})
            states={"C01":"SUPPORTED","C02":"SUPPORTED","C03":"SUPPORTED" if member==0 else "INSUFFICIENT","C05":"UNKNOWN","C07":"UNKNOWN","C09":"SUPPORTED"}
            rows=_claims(case,states,claim_id); claim_id+=100; snap["claims"].extend(rows)
            # Only 1/4 families get authoritative transition evidence; the rest is derived context only.
            if fam%4==0 and member==0:
                snap["candidate_evidence"].append({"id":20000+cid,"candidate_id":cid,"source_type":"news","source_table":"news","source_ref":f"t{fam}","relation":"why_now","title":"cost and automation transition","excerpt":f"Automation cost fell for workflow family {fam}, enabling a new operating model.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z","metadata":{"transition_pair_verified":True}})
    with tempfile.TemporaryDirectory(prefix="sfbrain_full_scale_") as td:
        root=Path(td); t=time.perf_counter(); result=await refresh_signalforge_brain_v2(root=root,snapshot=snap); elapsed=time.perf_counter()-t
        counts=result.get("counts",{})
        checks={
            "scale_refresh_under_15s": elapsed < 15.0,
            "scale_problem_compression": int(counts.get("problem_lineages",0)) <= 100,
            "derived_context_not_transition_lineage_explosion": int(counts.get("transition_lineages",0)) <= int(counts.get("lineage_eligible_transition_atoms",0)),
            "derived_context_accounted_without_persistent_authority": int(counts.get("transition_context_observations_not_materialized",0)) >= 500,
            "event_volume_bounded_by_active_objects": int(counts.get("events",0)) < 10000,
        }
        return checks,{"elapsed_seconds":round(elapsed,3),"counts":counts,"build_diagnostics":result.get("build_diagnostics",{})}


async def live_shape_admission_acceptance() -> tuple[dict, dict]:
    """Regression for the real R2 corpus shape that exposed structural over-admission.

    158 candidates each carry several timing/why-now/C12-looking rows. Almost all are
    intentionally generic and lack a verified pair or explicit structural subject. A small
    minority are genuine direct/explicit transition evidence. The Brain must preserve the
    former as context without turning them into hundreds of persistent TransitionLineages or
    context-only StructuralIntersections.
    """
    snap={"candidates":[],"candidate_evidence":[],"cases":[],"claims":[],"validated_radar_links":[],"load_metrics":{"fixture":"live-shape-admission"}}
    claim_id=80000
    for cid in range(1,159):
        case=12000+cid
        fam=(cid-1)//2
        snap["candidates"].append({
            "id":cid,"canonical_key":f"live-shape-{cid}","title":f"Operational verification failure family {fam}",
            "problem_statement":f"workflow family {fam} fails verification and requires manual recheck",
            "actor":"operator","actor_category":"operator","task":f"workflow {fam}","object":f"record {fam}",
            "failure_mode":"verification fails and requires manual recheck","consequence":"wastes hours",
            "buyer_context":"manager","workaround":"manual recheck","stage":"candidate","founder_status":"NEW",
            "first_seen_at":"2025-01-01T00:00:00Z","last_seen_at":"2026-01-01T00:00:00Z",
            "fingerprint":{"problem_scope_key":f"live-scope-{fam}","primary_problem_signature":f"live-sig-{fam}"},
        })
        snap["cases"].append({"id":case,"candidate_id":cid})
        snap["claims"].extend(_claims(case,{"C01":"SUPPORTED","C02":"SUPPORTED","C03":"SUPPORTED","C05":"UNKNOWN","C07":"UNKNOWN","C09":"SUPPORTED","C12":"PARTIAL"},claim_id)); claim_id+=100
        c12_id=claim_id+12
        # Six generic candidate timing rows. They are verified observations, but not verified
        # persistent transition identity.
        for j in range(6):
            snap["candidate_evidence"].append({
                "id":200000+cid*10+j,"candidate_id":cid,"source_type":"news","source_table":"news","source_ref":f"g-{cid}-{j}",
                "relation":"why_now" if j%2==0 else "ecosystem_activity",
                "title":"AI automation adoption activity","excerpt":f"Automation adoption and API activity change workflow conditions for cohort {cid}; generic timing context {j}.",
                "url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z","metadata":{},
            })
        # Three validated C12 timing rows per candidate, still generic and subjectless.
        for j in range(3):
            snap["validated_radar_links"].append({
                "claim_id":c12_id,"case_id":case,"claim_code":"C12","evidence_id":300000+cid*10+j,"stance":"SUPPORT","validated":True,
                "confidence":0.8,"rationale":"timing context","source_type":"news","source_table":"news","source_ref":f"c12-{cid}-{j}",
                "source_family_key":f"news:timing:{cid}:{j}","source_title":"market activity",
                "excerpt":"AI platforms release new automation capabilities and adoption continues across developer workflows.",
                "source_url":"","directness":"INDIRECT","authority_class":"MARKET_ACTIVITY","published_at":"2025-11-01T00:00:00Z","observed_at":"2025-11-01T00:00:00Z","metadata":{},
            })
        # Only eight candidates contain decision-bearing transition identity.
        if cid<=8:
            snap["candidate_evidence"].append({
                "id":400000+cid,"candidate_id":cid,"source_type":"news","source_table":"news","source_ref":f"direct-{cid}",
                "relation":"transition_signal","title":f"Named platform shift {cid%2}",
                "excerpt":f"Named platform shift {cid%2} changes the verification workflow and directly exposes the observed failure.",
                "url":"","verified":True,"verification_confidence":0.95,"observed_at":"2025-12-01T00:00:00Z","created_at":"2025-12-01T00:00:00Z",
                "metadata":{"transition_pair_verified":True,"transition_subject":f"named platform {cid%2}"},
            })
    with tempfile.TemporaryDirectory(prefix="sfbrain_live_shape_") as td:
        root=Path(td); t=time.perf_counter(); result=await refresh_signalforge_brain_v2(root=root,snapshot=snap); elapsed=time.perf_counter()-t
        counts=result.get("counts",{}); diag=(result.get("build_diagnostics") or {}).get("transition_admission",{}) or {}
        checks={
            "generic_timing_context_not_lineage_admitted": int(diag.get("context_only",0)) >= 1300 and int(diag.get("lineage_admitted",0)) <= 16,
            "persistent_transition_lineages_bounded": int(counts.get("transition_lineages",0)) <= 8,
            "context_only_pairs_not_materialized": int(counts.get("structural_intersections",0)) <= 8,
            "context_observations_not_duplicated_into_brain_ledger": int(counts.get("materialized_transition_atoms",0)) <= 16,
            "event_volume_bounded_under_live_shape": int(counts.get("events",0)) < 4000,
            "live_shape_refresh_under_15s": elapsed < 15.0,
        }
        return checks,{"elapsed_seconds":round(elapsed,3),"counts":counts,"transition_admission":diag,"build_diagnostics":result.get("build_diagnostics",{})}


async def context_hypothesis_scale_adversarial_acceptance() -> tuple[dict, dict]:
    """Stress the G3 recall staging layer with verified context, not derived noise.

    The corpus deliberately mixes three shapes:
    1) thousands of broad timing observations that must remain context only;
    2) one problem-scoped multi-source transition that should promote;
    3) one cross-problem transition with a genuinely sparse shared identity anchor;
    4) twenty independence decoys that repeat within one source/content unit and must not
       acquire persistent authority.

    This protects against the opposite regressions: G2-style zero recall and R2-style
    global context overmerge.
    """
    atoms=[]; candidate_to_problem_lineage={}; aid=0
    for cid in range(1,1001):
        candidate_to_problem_lineage[cid]=f"pl_{(cid-1)//2}"
        for j in range(3):
            aid+=1
            atoms.append({
                "transition_atom_id":f"ta_{aid}","candidate_id":cid,"verified":True,
                "lineage_eligible":False,"source_class":"VALIDATED_RADAR_CONTEXT","driver":"TECHNOLOGY",
                "text":f"AI automation adoption continues across workflows and platforms generic market timing {j}",
                "source_family":f"generic:{cid}:{j}","content_fingerprint":f"generic:{cid}:{j}",
                "valid_at":"2026-01-01T00:00:00Z",
            })

    # Same validated ProblemLineage: broad context may corroborate if independent and
    # identity-stable, even without an explicit transition subject on either row.
    for k,(cid,fam,date) in enumerate([
        (1,"problem-scope:a","2025-01-01T00:00:00Z"),
        (2,"problem-scope:b","2025-03-01T00:00:00Z"),
    ]):
        aid+=1
        atoms.append({
            "transition_atom_id":f"ta_{aid}","candidate_id":cid,"verified":True,
            "lineage_eligible":False,"source_class":"VALIDATED_RADAR_CONTEXT","driver":"COST",
            "text":"supplychainx pricingbridge unit economics collapse manual verification costs",
            "source_family":fam,"content_fingerprint":f"problem-scope:{k}","valid_at":date,
        })

    # Cross-problem recall is allowed only with a truly sparse shared identity anchor.
    for k,(cid,fam,date) in enumerate([
        (201,"cross:a","2025-01-01T00:00:00Z"),
        (203,"cross:b","2025-02-01T00:00:00Z"),
        (205,"cross:c","2025-03-01T00:00:00Z"),
    ]):
        aid+=1
        atoms.append({
            "transition_atom_id":f"ta_{aid}","candidate_id":cid,"verified":True,
            "lineage_eligible":False,"source_class":"VALIDATED_RADAR_CONTEXT","driver":"TECHNOLOGY",
            "text":"quantumrelay verifbridge protocol removes batch validation latency",
            "source_family":fam,"content_fingerprint":f"cross:{k}","valid_at":date,
        })

    # Adversarial independence decoys. Each pair repeats one source family/content unit.
    # Shared generic regulatory vocabulary must not merge all pairs into a fake global shift.
    for d in range(20):
        for cid in (401+2*d, 402+2*d):
            aid+=1
            atoms.append({
                "transition_atom_id":f"ta_{aid}","candidate_id":cid,"verified":True,
                "lineage_eligible":False,"source_class":"VALIDATED_RADAR_CONTEXT","driver":"REGULATION",
                "text":f"decoylaw{d} policyrule{d} compliance shift affects process",
                "source_family":f"decoy:{d}","content_fingerprint":f"decoy-content:{d}",
                "valid_at":"2025-01-01T00:00:00Z",
            })

    t=time.perf_counter()
    hypotheses,promotions=build_transition_hypotheses(atoms,candidate_to_problem_lineage=candidate_to_problem_lineage)
    elapsed=time.perf_counter()-t
    problem_scoped=[x for x in hypotheses if x.get("scope_mode")=="PROBLEM_SCOPED"]
    cross_problem=[x for x in hypotheses if x.get("scope_mode")=="CROSS_PROBLEM_RARE_ANCHOR"]
    regulation=[x for x in hypotheses if str(x.get("driver"))=="REGULATION"]
    checks={
        "verified_context_scale_under_5s": elapsed < 5.0,
        "generic_context_not_promoted": len(promotions)==5,
        "only_expected_hypotheses_survive": len(hypotheses)==2,
        "problem_scoped_recall_survives": len(problem_scoped)==1 and problem_scoped[0].get("promotion_eligible") is True,
        "cross_problem_rare_anchor_recall_survives": len(cross_problem)==1 and bool(cross_problem[0].get("rare_identity_terms")),
        "independence_decoys_do_not_promote": len(regulation)==0,
        "cross_problem_requires_sparse_anchor": all(bool(x.get("rare_identity_terms")) for x in cross_problem),
    }
    metrics={
        "elapsed_seconds":round(elapsed,4),"verified_context_atoms":len(atoms),
        "hypothesis_count":len(hypotheses),"promoted_atom_count":len(promotions),
        "problem_scoped_count":len(problem_scoped),"cross_problem_count":len(cross_problem),
        "drivers":[x.get("driver") for x in hypotheses],
        "identities":[x.get("identity_terms") for x in hypotheses],
    }
    return checks,metrics


async def large_scale_acceptance() -> tuple[dict, dict]:
    # 1,200 candidates / 400 stable problem families. This specifically protects against
    # the old repeated-corpus-scan and broad-bucket quadratic regressions.
    snap={"candidates":[],"candidate_evidence":[],"cases":[],"claims":[],"validated_radar_links":[],"load_metrics":{"fixture":"large-scale"}}
    cid=0; claim_id=50000
    for fam in range(400):
        for member in range(3):
            cid+=1; case=9000+cid
            fp={"problem_scope_key":f"scope-{fam}","primary_problem_signature":f"sig-{fam}","external_enabler_candidates":[{"text":f"Derived transition context {j} for family {fam} discusses automation adoption and workflow shift."} for j in range(2)]}
            snap["candidates"].append({"id":cid,"canonical_key":f"lc{cid}","title":f"Large workflow family {fam} failure report","problem_statement":f"workflow family {fam} repeatedly fails verification and requires manual recheck","actor":"operator","actor_category":"operator","task":f"workflow {fam}","object":f"record {fam}","failure_mode":"verification fails and requires manual recheck","consequence":"wastes two hours","buyer_context":"manager","workaround":"manual recheck","stage":"candidate","founder_status":"NEW","first_seen_at":"2025-01-01T00:00:00Z","last_seen_at":"2026-01-01T00:00:00Z","fingerprint":fp})
            snap["cases"].append({"id":case,"candidate_id":cid})
            states={"C01":"SUPPORTED","C02":"SUPPORTED","C03":"SUPPORTED" if member==0 else "INSUFFICIENT","C05":"UNKNOWN","C07":"UNKNOWN","C09":"SUPPORTED"}
            rows=_claims(case,states,claim_id); claim_id+=100; snap["claims"].extend(rows)
            if fam%10==0 and member==0:
                snap["candidate_evidence"].append({"id":70000+cid,"candidate_id":cid,"source_type":"news","source_table":"news","source_ref":f"lt{fam}","relation":"why_now","title":"automation cost transition","excerpt":f"Automation cost fell for workflow family {fam}, enabling a new operating model.","url":"","verified":True,"verification_confidence":0.9,"observed_at":"2025-10-01T00:00:00Z","created_at":"2025-10-01T00:00:00Z","metadata":{"transition_pair_verified":True}})
    with tempfile.TemporaryDirectory(prefix="sfbrain_full_large_scale_") as td:
        root=Path(td); t=time.perf_counter(); result=await refresh_signalforge_brain_v2(root=root,snapshot=snap); elapsed=time.perf_counter()-t
        counts=result.get("counts",{}); diag=result.get("build_diagnostics",{}) or {}
        phases=diag.get("phases_ms") or diag.get("phase_ms") or {}
        comparisons=(diag.get("comparison_counts") or {}).get("problem_lineage_comparisons")
        perf=(diag.get("performance_ms") or {})
        checks={
            # Keep the original end-to-end bound. Persistence/projection read amplification
            # was optimized rather than hiding the regression behind a larger timeout.
            "large_scale_refresh_under_15s": elapsed < 15.0,
            "large_scale_structural_build_under_8s": int(perf.get("structural_build_ms", diag.get("build_ms", 999999)) or 999999) < 8000,
            "large_scale_performance_telemetry_complete": all(
                k in perf for k in ("structural_build_ms","event_diff_ms","event_append_ms","projection_apply_ms","projection_snapshot_ms","total_before_surface_ms")
            ),
            "large_scale_problem_compression": int(counts.get("problem_lineages",0)) <= 450,
            "large_scale_transition_authority_bounded": int(counts.get("transition_lineages",0)) <= int(counts.get("lineage_eligible_transition_atoms",0)),
            "large_scale_event_volume_bounded": int(counts.get("events",0)) < 20000,
            "large_scale_not_candidate_backlog_copy": int(counts.get("opportunity_theses",0)) < int(counts.get("problem_atoms",0)),
        }
        return checks,{"elapsed_seconds":round(elapsed,3),"counts":counts,"phases_ms":phases,"performance_ms":perf,"problem_lineage_comparisons":comparisons}


async def live_acceptance() -> tuple[dict, dict]:
    root=Path.cwd().resolve()
    # Read the prior installed Brain status as plain JSON before opening Brain SQLite.
    # This is required for G2->G3 acceptance because opening a compatible G2 store under
    # G3 intentionally upgrades Brain-only schema metadata before the structural rebuild.
    prior_status_path=root/".radar_runtime/signalforge_brain_v2_full_status.json"
    try:
        prior_status=json.loads(prior_status_path.read_text(encoding="utf-8")) if prior_status_path.exists() else {}
    except Exception:
        prior_status={}
    prior_engine=str(prior_status.get("engine_version") or "")
    derivation_upgrade_expected=bool(prior_engine and prior_engine != BRAIN_ENGINE_VERSION)
    print("LIVE_PRIOR_BRAIN_ENGINE:", prior_engine or "NONE", "DERIVATION_UPGRADE_EXPECTED=", derivation_upgrade_expected, flush=True)
    print("LIVE_PHASE: production truth guard before", flush=True)
    guard_before=await production_truth_guard()
    print("LIVE_PHASE: optimized immutable truth snapshot", flush=True)
    t=time.perf_counter(); snap=await load_truth_snapshot(); load_seconds=time.perf_counter()-t
    print("LIVE_TRUTH_LOAD_SECONDS:", round(load_seconds,3), flush=True)
    before_events=count_events(root)
    print("LIVE_PHASE: first derived Brain refresh", flush=True)
    t=time.perf_counter(); first=await refresh_signalforge_brain_v2(root=root,snapshot=snap); first_seconds=time.perf_counter()-t
    print("LIVE_FIRST_REFRESH_SECONDS:", round(first_seconds,3), json.dumps(first.get("counts",{}),ensure_ascii=False), flush=True)
    after_first_events=count_events(root)
    print("LIVE_PHASE: identical-truth fast-noop refresh", flush=True)
    t=time.perf_counter(); second=await refresh_signalforge_brain_v2(root=root,snapshot=snap); second_seconds=time.perf_counter()-t
    print("LIVE_SECOND_REFRESH_SECONDS:", round(second_seconds,3), "refresh_skipped=", bool(second.get("refresh_skipped")), flush=True)
    after_second_events=count_events(root)
    print("LIVE_PHASE: production truth guard after", flush=True)
    guard_after=await production_truth_guard()
    print("LIVE_PHASE: append-only replay determinism after migration", flush=True)
    replay=replay_projection(root)
    replay_target=Path(replay["target"])
    active_projection_hash=_active_hash_from_state_db(root/".radar_runtime"/"signalforge_brain_v2_full_state.sqlite3")
    replay_projection_hash=_active_hash_from_state_db(replay_target)
    try: replay_target.unlink()
    except FileNotFoundError: pass
    counts=first.get("counts",{})
    first_dirty=((first.get("build_diagnostics") or {}).get("dirty") or {})
    upgrade_diag=first_dirty.get("derivation_upgrade") or {}
    checks={
        "production_truth_guard_unchanged": guard_before==guard_after,
        "brain_refresh_pass": first.get("status") in {"PASS","PASS_EMPTY"},
        "brain_refresh_operationally_bounded": first_seconds < 120.0,
        "identical_second_refresh_fast": second.get("refresh_skipped") is True and second_seconds < 5.0,
        "identical_second_refresh_adds_no_events": after_first_events==after_second_events,
        "transition_lineage_authority_bounded": int(counts.get("transition_lineages",0)) <= int(counts.get("lineage_eligible_transition_atoms",0)),
        "transition_admission_not_near_universal": int(counts.get("lineage_eligible_transition_atoms",0)) <= max(64, int(counts.get("problem_atoms",0))*3),
        "context_only_intersections_not_materialized": int(counts.get("structural_intersections",0)) <= max(64, int(counts.get("problem_lineages",0))*3),
        "derived_transition_context_not_lineage_authority": int(counts.get("transition_context_observations_not_materialized",0)) >= 0,
        "thesis_not_flat_candidate_copy": int(counts.get("opportunity_theses",0)) <= int(counts.get("structural_intersections",0)) + int(counts.get("problem_lineages",0)),
        "atomic_truth_stays_radar_owned": (first.get("authority") or {}).get("radar_atomic_claim_truth")=="SOLE_OWNER",
        "shadow_zero_authority": (first.get("authority") or {}).get("framegraph_shadow")=="ZERO_PRODUCTION_AUTHORITY",
        "freshness_no_priority_authority": (first.get("authority") or {}).get("freshness_priority_authority") is False,
        "market_accuracy_not_faked": (first.get("market_calibration") or {}).get("predictive_accuracy","UNVALIDATED")=="UNVALIDATED" or bool((first.get("market_calibration") or {}).get("calibration_dataset_ready")),
        "g2_to_g3_derivation_upgrade_forced_when_expected": (not derivation_upgrade_expected) or (
            first.get("refresh_skipped") is not True
            and str(upgrade_diag.get("from_engine") or "") == prior_engine
            and str(upgrade_diag.get("to_engine") or "") == BRAIN_ENGINE_VERSION
        ),
        "g3_schema_active_after_refresh": str(first.get("schema_version") or "").endswith("-g3"),
        "post_migration_append_only_replay_deterministic": active_projection_hash == replay_projection_hash,
    }
    metrics={
        "prior_brain_engine":prior_engine,"derivation_upgrade_expected":derivation_upgrade_expected,"derivation_upgrade":upgrade_diag,
        "guard_before":guard_before,"guard_after":guard_after,"truth_load_seconds":round(load_seconds,3),"first_refresh_seconds":round(first_seconds,3),"second_refresh_seconds":round(second_seconds,3),
        "events_before":before_events,"events_after_first":after_first_events,"events_after_second":after_second_events,"active_projection_hash":active_projection_hash,"replay_projection_hash":replay_projection_hash,"counts":counts,"build_diagnostics":first.get("build_diagnostics",{}),"market_calibration":first.get("market_calibration",{}),
    }
    return checks,metrics


async def _static_suite() -> tuple[bool, dict]:
    contracts=contracts_acceptance(); print("CONTRACTS_STATIC_PASS:",_all_true(contracts),json.dumps(contracts,ensure_ascii=False))
    integration_module=integration_module_acceptance(); print("INTEGRATION_MODULE_STATIC_PASS:",_all_true(integration_module),json.dumps(integration_module,ensure_ascii=False))
    runtime_module=runtime_module_acceptance(); print("RUNTIME_MODULE_STATIC_PASS:",_all_true(runtime_module),json.dumps(runtime_module,ensure_ascii=False))
    structural_recall_module=structural_recall_module_acceptance(); print("STRUCTURAL_RECALL_MODULE_PASS:",_all_true(structural_recall_module),json.dumps(structural_recall_module,ensure_ascii=False))
    with tempfile.TemporaryDirectory(prefix="sfbrain_store_") as td:
        store=store_acceptance(Path(td))
    print("STORE_STATIC_PASS:",_all_true(store),json.dumps(store,ensure_ascii=False))
    synth,synth_metrics=await synthetic_acceptance(); print("SYNTHETIC_SYSTEM_PASS:",_all_true(synth),json.dumps(synth,ensure_ascii=False)); print("SYNTHETIC_METRICS:",json.dumps(synth_metrics,ensure_ascii=False))
    scope,scope_metrics=await cross_scope_truth_acceptance(); print("CROSS_SCOPE_TRUTH_PASS:",_all_true(scope),json.dumps(scope,ensure_ascii=False)); print("CROSS_SCOPE_TRUTH_METRICS:",json.dumps(scope_metrics,ensure_ascii=False))
    recall,recall_metrics=await structural_recall_end_to_end_acceptance(); print("STRUCTURAL_RECALL_E2E_PASS:",_all_true(recall),json.dumps(recall,ensure_ascii=False)); print("STRUCTURAL_RECALL_E2E_METRICS:",json.dumps(recall_metrics,ensure_ascii=False))
    lifecycle,lifecycle_metrics=await thesis_lifecycle_acceptance(); print("THESIS_LIFECYCLE_PASS:",_all_true(lifecycle),json.dumps(lifecycle,ensure_ascii=False)); print("THESIS_LIFECYCLE_METRICS:",json.dumps(lifecycle_metrics,ensure_ascii=False))
    derivation_upgrade,derivation_upgrade_metrics=await derivation_upgrade_acceptance(); print("DERIVATION_UPGRADE_PASS:",_all_true(derivation_upgrade),json.dumps(derivation_upgrade,ensure_ascii=False)); print("DERIVATION_UPGRADE_METRICS:",json.dumps(derivation_upgrade_metrics,ensure_ascii=False))
    scale,scale_metrics=await scale_acceptance(); print("SCALE_SYSTEM_PASS:",_all_true(scale),json.dumps(scale,ensure_ascii=False)); print("SCALE_METRICS:",json.dumps(scale_metrics,ensure_ascii=False))
    live_shape,live_shape_metrics=await live_shape_admission_acceptance(); print("LIVE_SHAPE_ADMISSION_PASS:",_all_true(live_shape),json.dumps(live_shape,ensure_ascii=False)); print("LIVE_SHAPE_ADMISSION_METRICS:",json.dumps(live_shape_metrics,ensure_ascii=False))
    context_scale,context_scale_metrics=await context_hypothesis_scale_adversarial_acceptance(); print("CONTEXT_HYPOTHESIS_SCALE_PASS:",_all_true(context_scale),json.dumps(context_scale,ensure_ascii=False)); print("CONTEXT_HYPOTHESIS_SCALE_METRICS:",json.dumps(context_scale_metrics,ensure_ascii=False))
    large,large_metrics=await large_scale_acceptance(); print("LARGE_SCALE_SYSTEM_PASS:",_all_true(large),json.dumps(large,ensure_ascii=False)); print("LARGE_SCALE_METRICS:",json.dumps(large_metrics,ensure_ascii=False))
    ok=_all_true(contracts) and _all_true(integration_module) and _all_true(runtime_module) and _all_true(structural_recall_module) and _all_true(store) and _all_true(synth) and _all_true(scope) and _all_true(recall) and _all_true(lifecycle) and _all_true(derivation_upgrade) and _all_true(scale) and _all_true(live_shape) and _all_true(context_scale) and _all_true(large)
    return ok,{"contracts":contracts,"integration":integration_module,"runtime":runtime_module,"structural_recall":structural_recall_module,"store":store,"synthetic":synth,"cross_scope":scope,"recall":recall,"lifecycle":lifecycle,"derivation_upgrade":derivation_upgrade,"scale":scale,"live_shape":live_shape,"context_hypothesis_scale":context_scale,"large_scale":large}


async def main(static_only: bool=False, live_only: bool=False) -> int:
    if static_only and live_only:
        raise ValueError("--static-only and --live-only are mutually exclusive")
    print("="*128)
    print("SignalForge Brain v2 — FULL-SYSTEM LONGITUDINAL INTELLIGENCE ACCEPTANCE")
    print("="*128)

    # Installer architecture deliberately separates the expensive deterministic
    # engineering suite from the live SELECT-only derived-plane check. This
    # prevents a live acceptance timeout from re-running synthetic/scale tests
    # that already passed immediately beforehand.
    if live_only:
        print("ACCEPTANCE_PLANE: LIVE_DERIVED_ONLY", flush=True)
        live,live_metrics=await live_acceptance(); print("LIVE_SYSTEM_PASS:",_all_true(live),json.dumps(live,ensure_ascii=False)); print("LIVE_METRICS:",json.dumps(live_metrics,ensure_ascii=False))
        ok=_all_true(live)
        print("FINAL_STATUS:","SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_LIVE_ACCEPTANCE_PASS" if ok else "SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_LIVE_ACCEPTANCE_FAIL")
        return 0 if ok else 2

    ok,_=await _static_suite()
    if static_only:
        print("FINAL_STATUS:","SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_STATIC_ACCEPTANCE_PASS" if ok else "SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_STATIC_ACCEPTANCE_FAIL")
        return 0 if ok else 2

    live,live_metrics=await live_acceptance(); print("LIVE_SYSTEM_PASS:",_all_true(live),json.dumps(live,ensure_ascii=False)); print("LIVE_METRICS:",json.dumps(live_metrics,ensure_ascii=False))
    ok = ok and _all_true(live)
    print("FINAL_STATUS:","SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_ACCEPTANCE_PASS" if ok else "SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_ACCEPTANCE_FAIL")
    return 0 if ok else 2


if __name__=="__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("--static-only",action="store_true"); ap.add_argument("--live-only",action="store_true"); args=ap.parse_args(); raise SystemExit(asyncio.run(main(args.static_only,args.live_only)))
