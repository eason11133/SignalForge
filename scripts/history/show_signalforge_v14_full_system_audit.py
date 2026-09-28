from __future__ import annotations
import json
from pathlib import Path

DISC=Path('.radar_runtime/transition_gap_discovery.json');SRC=Path('.radar_runtime/source_portfolio_v14.json');CLAIMS=Path('.radar_runtime/v14_current_claims.json');PORT=Path('.radar_runtime/founder_current_portfolio.json');VAL=Path('.radar_runtime/market_test_queue_v14.json');CAL=Path('.radar_runtime/opportunity_calibration_v14.json');SURF=Path('.radar_runtime/founder_opportunity_surface_v14.json')
def load(p,d):
    try:return json.loads(p.read_text(encoding='utf-8'))
    except:return d

def pct(a,b):return round(100*a/max(1,b))
def main():
    d=load(DISC,{});s=load(SRC,{}).get('health') or {};c=load(CLAIMS,{});p=load(PORT,{});v=load(VAL,{});cal=load(CAL,{});surf=load(SURF,{})
    f=d.get('formation') or {};oa=f.get('observation_audit') or {};eg=f.get('evidence_graph') or {};screen=d.get('screening') or {}
    checks={
      'SOURCE_PORTFOLIO':[
        bool((s.get('family_counts') or {}).get('stackexchange')),bool((s.get('family_counts') or {}).get('app_store_reviews')),bool((s.get('adaptive_policy') or {}).get('gap_directed')),bool((s.get('scope_counts') or {}).get('consumer_physical')),s.get('status') in {'PASS','PARTIAL'}],
      'OBSERVATION_LAYER':[oa.get('linear_pass') is True,oa.get('cache_hits',0)>=0,'app_review_targets_listed_entity_not_app' in (oa.get('rejected_reasons') or {}),oa.get('usable_observations',0)>0],
      'EVIDENCE_GRAPH':[(eg.get('telemetry') or {}).get('recurrence_cluster_policy')=='RECURRENCE_EDGES_ONLY',eg.get('clusters',0)>=0,(eg.get('telemetry') or {}).get('pair_reduction_ratio',0)>0.9],
      'SIX_LANE_DISCOVERY':[all(k in (f.get('deduped_by_lane') or {}) for k in ['TRANSITION_GAP','PROVEN_MARKET_WEDGE','MICRO_FRICTION','DISTRIBUTION_MODEL_GAP','SECOND_ORDER_PAIN','BORING_OPS']),f.get('canonical_units',0)>=0,f.get('cross_lane_duplicates_collapsed',0)>=0,screen.get('malformed',99)==0],
      'CLAIM_TRUTH':[c.get('current_candidates',-1)==p.get('current_count',-2),c.get('predictive_credibility')=='UNVALIDATED'],
      'FOUNDER_SURFACE':[surf.get('current_count',-1)==p.get('current_count',-2),Path('.radar_runtime/founder_opportunity_surface_v14.md').exists()],
      'VALIDATION_PIPELINE':[v.get('tests_planned',0)>=p.get('current_count',0),v.get('truth_contract','').startswith('A plan is readiness'),v.get('outcome_ingest_path') is not None],
      'CALIBRATION_FOUNDATION':[bool((cal.get('readiness') or {}).get('queue_generation') or p.get('current_count',0)==0),(cal.get('readiness') or {}).get('outcome_ingestion') is True,cal.get('predictive_accuracy') in {'UNVALIDATED','CALIBRATION_DATA_AVAILABLE_NOT_AUTOMATICALLY_ACCURATE'}],
    }
    print('='*126);print('SIGNALFORGE V14 — FULL-SYSTEM PARALLEL UPGRADE AUDIT');print('='*126)
    print(f"Source: engine={s.get('engine_version')} cache={s.get('cache')} docs={s.get('total_docs')} families={s.get('family_counts')} scopes={s.get('scope_counts')}")
    print(f"Observation: docs={oa.get('documents')} usable={oa.get('usable_observations')} cache_hits={oa.get('cache_hits')} misses={oa.get('cache_misses')} seconds={oa.get('seconds')} targets={oa.get('problem_targets')}")
    print(f"Observation rejections: {oa.get('rejected_reasons')}")
    print(f"Graph: nodes={eg.get('nodes')} edges={eg.get('edges')} recurrence_clusters={eg.get('clusters')} telemetry={eg.get('telemetry')}")
    print('-'*126)
    print(f"Lane dedup units: {f.get('deduped_by_lane')} canonical_units={f.get('canonical_units')} cross_lane_duplicates_collapsed={f.get('cross_lane_duplicates_collapsed')}")
    print(f"Selected by lane: {f.get('selected_by_lane')} screen_pool={d.get('screen_pool')}")
    print(f"Screening: {screen}")
    print(f"Accepted primary lanes: {d.get('accepted_by_primary_lane')} | qualified lane counts: {d.get('accepted_qualified_lane_counts')}")
    for i,x in enumerate(d.get('accepted_summaries') or [],1):
        print(f"  #{i:02d} [{x.get('primary_lane')}] also={x.get('qualified_lanes')} product={x.get('product')} sig={x.get('problem_signatures')} target={x.get('target')} | {x.get('problem')}")
        print(f"       corroboration={x.get('corroboration')}")
    print('-'*126)
    print(f"Current portfolio={p.get('current_count')} legacy={p.get('legacy_archive_count')} ranking={p.get('ranking_contract')} predictive={p.get('predictive_credibility')}")
    print(f"Current claim truth={c.get('current_candidates')} predictive={c.get('predictive_credibility')}")
    print(f"Validation queue: planned={v.get('tests_planned')} completed={v.get('tests_completed')} paid_outcomes={v.get('paid_outcomes')}")
    print(f"Calibration: {cal}")
    print('-'*126)
    print('IMPLEMENTATION COVERAGE (checklist-derived, not market-success percentages):')
    for name,xs in checks.items():
        passed=sum(bool(x) for x in xs);print(f"  {name:24s} {passed}/{len(xs)} = {pct(passed,len(xs))}%")
    print('MARKET TRUTH: live paid/behavior outcomes remain actual recorded outcomes only. If none are ingested, market validation remains 0 / UNVALIDATED.')
    print('COVERAGE BOUNDARIES:',(s.get('coverage_boundaries') or {}))
    print('='*126)
if __name__=='__main__':main()
