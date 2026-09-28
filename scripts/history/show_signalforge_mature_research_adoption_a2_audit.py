from __future__ import annotations
import json
from pathlib import Path

P=Path('.radar_runtime')

def load(name,default):
    try:return json.loads((P/name).read_text(encoding='utf-8'))
    except Exception:return default

def main():
    d=load('opportunity_hypothesis_discovery_r1.json',{})
    obs=load('opportunity_observations_r1.json',{})
    port=load('founder_current_portfolio.json',{})
    rq=load('evidence_research_queue_r1.json',{})
    watch=load('opportunity_watch_signals_r1.json',{})
    robj=load('opportunity_research_objects_a1.json',{})
    val=load('market_test_queue_r1.json',{})
    cal=load('opportunity_calibration_r1.json',{})
    oa=d.get('observation_audit') or obs.get('audit') or {};hm=d.get('hypothesis_formation') or {}
    ret=hm.get('retrieval') or {};recovery=d.get('evidence_recovery_funnel') or {};sel=recovery.get('recovery_selection') or {}
    print('='*144)
    print('SIGNALFORGE — MATURE RESEARCH ADOPTION A2 LIVE AUDIT')
    print('='*144)
    print('DISCOVERY ENGINE:',d.get('engine_version'))
    print('DOCS / USABLE:',d.get('docs',0),'/',d.get('usable_observations',obs.get('count',0)))
    print('EVIDENCE DISPOSITIONS:',oa.get('evidence_dispositions') or {})
    print('SIGNATURE-MISSING NEED FRAGMENTS RETAINED:',oa.get('signature_missing_need_fragments_retained',0))
    print('HARD PRIMARY-SIGNATURE GATE REMOVED:',bool(hm.get('hard_primary_signature_gate_removed')))
    print('PROBLEM FAMILY FORMATION:',{
        'seeds':hm.get('seed_count',0),'stable_identity':hm.get('stable_identity_seed_count',0),'incomplete_identity':hm.get('incomplete_identity_seed_count',0),
        'multi_evidence':hm.get('multi_evidence_seed_count',0),'single_evidence':hm.get('single_evidence_seed_count',0),'high_medium':hm.get('high_medium_seed_count',0),'misc':hm.get('misc_seed_count',0),
        'current_ready':hm.get('current_ready_hypotheses',0),'watch':hm.get('watch_count',0),'research':hm.get('research_queue_count',0),'misc_backlog':hm.get('misc_backlog_count',0),
    })
    print('BALANCED RETRIEVAL:',{
        'eligible':ret.get('eligible'),'candidate_pairs':ret.get('candidate_pairs'),'coverage':ret.get('coverage'),'anchors_with_candidates':ret.get('anchors_with_candidates'),
        'same_problem_candidates':ret.get('same_problem_candidates'),'relations':ret.get('relations'),'per_anchor_cap':ret.get('per_anchor_cap'),
    })
    samples=ret.get('top_related_samples') or []
    if samples:print('TOP RELATED-BUT-NOT-CORROBORATED SAMPLES:',samples[:5])
    print('RESEARCH OBJECTS:',robj.get('counts') or {})
    print('FRONTIER BOUNDARY:',robj.get('frontier_boundary'))
    print('RECOVERY SELECTION:',sel)
    print('RECOVERY RESULT:',recovery.get('recovery') or {})
    print('RELATIONSHIP AUDIT:',d.get('relationship_audit') or {})
    print('CURRENT / WATCH / RESEARCH_TOTAL / RESEARCH_MATERIALIZED:',port.get('current_count',0),'/',watch.get('count',0),'/',rq.get('count',0),'/',rq.get('materialized_count',len(rq.get('items') or [])))
    print('PHASE SECONDS:',d.get('phase_seconds') or {})
    print('PORTFOLIO QUALITY:',(port.get('portfolio_quality_gate') or {}).get('status'))
    print('RUNTIME MODE:',(port.get('operational_usability_gate') or {}).get('mode'))
    print('VALIDATION:',{'planned':val.get('tests_planned',0),'actionable':val.get('tests_actionable_now',0),'completed':val.get('tests_completed',0),'paid':val.get('paid_outcomes',0)})
    print('CALIBRATION:',{'dataset_ready':cal.get('calibration_dataset_ready',False),'predictive':cal.get('predictive_accuracy','UNVALIDATED')})
    print('-'*144)
    expected='opportunity-discovery-mature-research-a2-balanced-corroboration-recovery'
    print('ENGINEERING ADOPTION STATUS:','PASS' if d.get('engine_version')==expected else 'NOT_RUN_OR_WRONG_ENGINE')
    print('LIVE EVIDENCE FLOW:','FLOWING' if hm.get('seed_count',0) else 'BLOCKED_ZERO_NEED_SEEDS')
    multi=int(hm.get('multi_evidence_seed_count') or 0);accepted=int(d.get('accepted') or 0)
    if accepted>0:
        usability='REQUIRES HUMAN LIVE RESEARCH-HYPOTHESIS REVIEW'
    elif multi>0:
        usability='BLOCKED_AFTER_CORROBORATION — REVIEW WHY MULTI-EVIDENCE FAMILIES DID NOT BECOME RESEARCH HYPOTHESES'
    else:
        usability='BLOCKED_NO_CORROBORATED_PROBLEM_FAMILIES — DO NOT CLAIM PRODUCT USABILITY'
    print('VENTURE OPPORTUNITY RECOGNITION: FRONTIER_NOT_SELF_CERTIFIED')
    print('FINAL PRODUCT USABILITY:',usability)
    print('LIVE MARKET VALIDATION:',cal.get('valid_outcomes',0),'valid outcomes /',cal.get('paid_outcomes',0),'paid outcomes; predictive',cal.get('predictive_accuracy','UNVALIDATED'))
    print('='*144)

if __name__=='__main__':main()
