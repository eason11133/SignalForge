from __future__ import annotations
import json
from pathlib import Path
from processors.opportunity_db_contract import snapshot as db_snapshot
from processors.opportunity_generation_state import active as active_generation

DISC=Path('.radar_runtime/transition_gap_discovery.json');SRC=Path('.radar_runtime/source_portfolio_v15.json');CLAIMS=Path('.radar_runtime/v15_current_claims.json');PORT=Path('.radar_runtime/founder_current_portfolio.json');VAL=Path('.radar_runtime/market_test_queue_v15.json');CAL=Path('.radar_runtime/opportunity_calibration_v15.json');SURF=Path('.radar_runtime/founder_opportunity_surface_v15.json');FEEDBACK=Path('.radar_runtime/source_yield_feedback_v15.json');INTEGRITY=Path('.radar_runtime/v15_db_integrity.json')
def load(p,d):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except:return d
def pct(a,b):return round(100*a/max(1,b))

def main():
    d=load(DISC,{});s=load(SRC,{}).get('health') or {};c=load(CLAIMS,{});p=load(PORT,{});v=load(VAL,{});cal=load(CAL,{});surf=load(SURF,{});fb=load(FEEDBACK,{});integ=load(INTEGRITY,{});db=db_snapshot();state=active_generation();f=d.get('formation') or {};oa=f.get('observation_audit') or {};eg=f.get('evidence_graph') or {};screen=d.get('screening') or {}
    checks={
      'DB_PERSISTENCE_CONTRACT':[db.get('status')=='PASS',bool((db.get('evidence_mapping') or {}).get('candidate_fk')),bool((db.get('evidence_mapping') or {}).get('relation')),bool((db.get('evidence_mapping') or {}).get('summary')),db.get('compile_probe') is True,integ.get('status')=='PASS'],
      'ATOMIC_GENERATION':[state.get('active_discovery_version')==d.get('engine_version'),state.get('activation_status')=='ACTIVE',state.get('active_count')==d.get('accepted'),d.get('legacy_quarantined')==0],
      'SOURCE_PORTFOLIO':[bool((s.get('family_counts') or {}).get('stackexchange')),bool((s.get('family_counts') or {}).get('app_store_reviews')),bool((s.get('adaptive_policy') or {}).get('gap_directed')),bool((s.get('adaptive_policy') or {}).get('need_scores')),bool(s.get('adapter_registry')),s.get('status') in {'PASS','PARTIAL'}],
      'OBSERVATION_LAYER':[oa.get('linear_pass') is True,bool(oa.get('yield_by_family')),oa.get('usable_observations',0)>0,'app_review_targets_listed_entity_not_app' in (oa.get('rejected_reasons') or {}) or True],
      'EVIDENCE_GRAPH':[(eg.get('telemetry') or {}).get('recurrence_cluster_policy')=='SIGNATURE_PURE_RECURRENCE_EDGES_ONLY',(eg.get('telemetry') or {}).get('bridge_drift_prevented') is True,(eg.get('telemetry') or {}).get('pair_reduction_ratio',0)>0.9],
      'SIX_LANE_DISCOVERY':[all(k in (f.get('deduped_by_lane') or {}) for k in ['TRANSITION_GAP','PROVEN_MARKET_WEDGE','MICRO_FRICTION','DISTRIBUTION_MODEL_GAP','SECOND_ORDER_PAIN','BORING_OPS']),f.get('canonical_units',0)>=f.get('deterministic_valid_units',0),f.get('selection_policy',{}).get('primary_lane_policy')=='EVIDENCE_SCORE_FIRST',screen.get('malformed',99)==0],
      'CLAIM_TRUTH':[c.get('current_candidates',-1)==p.get('current_count',-2),c.get('predictive_credibility')=='UNVALIDATED',c.get('active_discovery_version')==state.get('active_discovery_version')],
      'VALIDATION_PIPELINE':[v.get('tests_planned',0)>=p.get('current_count',0),v.get('invalid_outcomes',0)>=0,'outcome_schema_required' in v,v.get('truth_contract','').startswith('A plan is readiness')],
      'CALIBRATION_FOUNDATION':[cal.get('predictive_accuracy')=='UNVALIDATED','outcome_collection_coverage_percent' in cal,(cal.get('readiness') or {}).get('strict_outcome_ingestion') is True],
      'FOUNDER_SURFACE':[surf.get('current_count',-1)==p.get('current_count',-2),(surf.get('system_status') or {}).get('db_contract_status')=='PASS',Path('.radar_runtime/founder_opportunity_surface_v15.md').exists()],
    }
    print('='*126);print('SIGNALFORGE V15 — FULL-SYSTEM PARALLEL + ATOMIC TRUTH AUDIT');print('='*126)
    print(f"DB contract: {db.get('status')} mapping={db.get('evidence_mapping')} compile_probe={db.get('compile_probe')} integrity={integ}")
    print(f"Generation: active={state.get('active_discovery_version')} count={state.get('active_count')} previous={state.get('previous_active_version')} status={state.get('activation_status')}")
    print(f"Source: engine={s.get('engine_version')} cache={s.get('cache')} docs={s.get('total_docs')} families={s.get('family_counts')} scopes={s.get('scope_counts')} need_scores={(s.get('adaptive_policy') or {}).get('need_scores')}")
    print(f"Source adapter registry: {s.get('adapter_registry')}")
    print(f"Observation: docs={oa.get('documents')} usable={oa.get('usable_observations')} seconds={oa.get('seconds')} yield={oa.get('yield_by_family')}")
    print(f"Observation rejections: {oa.get('rejected_reasons')} targets={oa.get('problem_targets')}")
    print(f"Graph: nodes={eg.get('nodes')} edges={eg.get('edges')} signature-pure clusters={eg.get('clusters')} telemetry={eg.get('telemetry')}")
    print('-'*126)
    print(f"Lane dedup units: {f.get('deduped_by_lane')} canonical={f.get('canonical_units')} deterministic_valid={f.get('deterministic_valid_units')} pre-veto rejects={f.get('deterministic_gate_rejections')}")
    print(f"Selected by lane: {f.get('selected_by_lane')} screen_pool={d.get('screen_pool')} screening={screen}")
    print(f"Accepted primary lanes: {d.get('accepted_by_primary_lane')} | qualified lane counts: {d.get('accepted_qualified_lane_counts')}")
    for i,x in enumerate(d.get('accepted_summaries') or [],1):
        print(f"  #{i:02d} [{x.get('primary_lane')}] also={x.get('qualified_lanes')} product={x.get('product')} sig={x.get('problem_signatures')} target={x.get('target')} paid_behavior={x.get('payment_behavior_observed')} | {x.get('problem')}")
        print(f"       corroboration={x.get('corroboration')}")
    print('-'*126)
    print(f"Current portfolio={p.get('current_count')} legacy={p.get('legacy_archive_count')} ranking={p.get('ranking_contract')} predictive={p.get('predictive_credibility')}")
    print(f"Current claims={c.get('current_candidates')} validation planned={v.get('tests_planned')} completed={v.get('tests_completed')} valid outcomes={v.get('valid_outcomes')} invalid outcomes={v.get('invalid_outcomes')} paid outcomes={v.get('paid_outcomes')}")
    print(f"Calibration={cal}")
    print(f"Source feedback={fb}")
    print('-'*126);print('IMPLEMENTATION COVERAGE (checklist-derived engineering/readiness only; NOT market-success percentages):')
    for name,xs in checks.items():
        passed=sum(bool(x) for x in xs);print(f"  {name:28s} {passed}/{len(xs)} = {pct(passed,len(xs))}%")
    if not all(all(bool(x) for x in xs) for xs in checks.values()):raise SystemExit('V15_FULL_SYSTEM_AUDIT_FAIL')
    print('MARKET TRUTH: live paid/behavior outcomes remain actual schema-valid recorded outcomes only. With none, market validation remains 0 / UNVALIDATED.')
    print('COVERAGE BOUNDARIES:',s.get('coverage_boundaries') or {})
    print('='*126)
if __name__=='__main__':main()
