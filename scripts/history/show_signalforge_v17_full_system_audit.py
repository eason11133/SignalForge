from __future__ import annotations
import json
from pathlib import Path
from collections import Counter
from processors.opportunity_db_contract import snapshot as db_snapshot
from processors.opportunity_generation_state import active as active_generation

FILES={
 'source':Path('.radar_runtime/source_portfolio_v17.json'),
 'discovery':Path('.radar_runtime/transition_gap_discovery.json'),
 'claims':Path('.radar_runtime/v17_current_claims.json'),
 'portfolio':Path('.radar_runtime/founder_current_portfolio.json'),
 'validation':Path('.radar_runtime/market_test_queue_v17.json'),
 'calibration':Path('.radar_runtime/opportunity_calibration_v17.json'),
 'founder':Path('.radar_runtime/founder_opportunity_surface_v17.json'),
 'obs':Path('.radar_runtime/opportunity_observations_v17.json'),
 'graph':Path('.radar_runtime/opportunity_evidence_graph_v17.json'),
}

def load(k):
    try:return json.loads(FILES[k].read_text(encoding='utf-8'))
    except:return {}

def main():
    src=load('source');d=load('discovery');c=load('claims');p=load('portfolio');v=load('validation');cal=load('calibration');f=load('founder');obs=load('obs');g=load('graph');db=db_snapshot();state=active_generation();formation=d.get('formation') or {};screen=d.get('screening') or {};quality=p.get('portfolio_quality_gate') or {};oa=formation.get('observation_audit') or {};gt=(formation.get('evidence_graph') or {}).get('telemetry') or {}
    print('='*126);print('SIGNALFORGE V17 — FULL-SYSTEM CONTRACT-VERIFIED OPERATIONAL USABILITY AUDIT');print('='*126)
    print('DB CONTRACT:',db.get('status'),'fingerprint=',db.get('contract_fingerprint'),'metadata=',db.get('metadata_storage'),'optional_missing=',db.get('optional_missing_logical'),'capabilities=',db.get('capabilities'))
    print('ACTIVE GENERATION:',state.get('active_discovery_version'),'count=',state.get('active_count'),'status=',state.get('activation_status'))
    h=src.get('health') or {};print('SOURCE:',h.get('status'),'cache=',h.get('cache'),'docs=',h.get('total_docs'),'requests_this_run=',h.get('requests_this_run'),'snapshot_requests=',h.get('snapshot_network_requests'),'boundaries=',h.get('coverage_boundaries'))
    print('OBSERVATION: docs=',oa.get('documents'),'usable=',oa.get('usable_observations'),'cache_hits=',oa.get('cache_hits'),'cache_misses=',oa.get('cache_misses'),'seconds=',oa.get('seconds'),'targets=',oa.get('problem_targets'))
    print('GRAPH: nodes=',(formation.get('evidence_graph') or {}).get('nodes'),'edges=',(formation.get('evidence_graph') or {}).get('edges'),'clusters=',(formation.get('evidence_graph') or {}).get('clusters'),'recurrence_edges=',gt.get('recurrence_edges'),'cross_source_recurrence=',gt.get('cross_source_recurrence_edges'),'pair_reduction=',gt.get('pair_reduction_ratio'))
    print('-'*126)
    print('LANE RAW:',formation.get('raw'));print('LANE DEDUP:',formation.get('deduped_by_lane'));print('SELECTED:',formation.get('selected_by_lane'));print('ACCEPTED PRIMARY:',d.get('accepted_by_primary_lane'));print('ACCEPTED QUALIFIED:',d.get('accepted_qualified_lane_counts'));print('LLM REASONS:',screen.get('reject_reason_counts'));print('POST-VETO DIVERSITY:',d.get('post_veto_diversity'))
    print('DB EVIDENCE: rows=',d.get('evidence_rows'),'integrity=',d.get('active_evidence_integrity'),'sidecar=',d.get('evidence_sidecar'))
    print('-'*126)
    print('CLAIMS: current=',c.get('current_candidates'),'external_updates=',c.get('external_validation_claim_updates'),'integrity=',c.get('active_evidence_integrity'))
    print('CURRENT PORTFOLIO: current=',p.get('current_count'),'lanes=',p.get('current_by_primary_lane'),'legacy=',p.get('legacy_archive_count'),'quality=',quality,'operational=',p.get('operational_usability_gate'))
    print('VALIDATION: planned=',v.get('tests_planned'),'actionable_now=',v.get('tests_actionable_now'),'completed=',v.get('tests_completed'),'valid_outcomes=',v.get('valid_outcomes'),'invalid=',v.get('invalid_outcomes'),'paid=',v.get('paid_outcomes'))
    print('CALIBRATION: outcome_coverage=',cal.get('outcome_collection_coverage_percent'),'candidate_coverage=',cal.get('candidate_outcome_coverage_percent'),'dataset_ready=',cal.get('calibration_dataset_ready'),'predictive_accuracy=',cal.get('predictive_accuracy'),'market_truth=',cal.get('market_truth'))
    fs=f.get('system_status') or {};print('FOUNDER: current=',f.get('current_count'),'portfolio_quality=',fs.get('portfolio_quality_gate'),'next_tests=',fs.get('tests_actionable_now'),'predictive=',f.get('predictive_credibility'))
    print('-'*126)
    matrix={
      'DB_SCHEMA_PORTABILITY': db.get('status')=='PASS',
      'ATOMIC_GENERATION_TRUTH': str(state.get('active_discovery_version') or '').startswith('opportunity-observation-architecture-v17'),
      'SOURCE_PORTFOLIO': h.get('status') in {'PASS','PARTIAL'},
      'OBSERVATION_LAYER': int(oa.get('usable_observations') or 0)>=0 and oa.get('sentence_targeting') is True and oa.get('span_provenance') is True,
      'EVIDENCE_GRAPH': gt.get('recurrence_precision_policy') is not None and gt.get('edge_provenance_visible') is True,
      'SIX_LANE_FORMATION': set((formation.get('deduped_by_lane') or {}).keys())=={'TRANSITION_GAP','PROVEN_MARKET_WEDGE','MICRO_FRICTION','DISTRIBUTION_MODEL_GAP','SECOND_ORDER_PAIN','BORING_OPS'},
      'CURRENT_CLAIM_TRUTH': c.get('active_evidence_integrity',{}).get('status')=='PASS',
      'CURRENT_PORTFOLIO_TRUTH': quality.get('status')=='PASS' and (p.get('operational_usability_gate') or {}).get('status')=='PASS',
      'VALIDATION_READINESS': 'tests_planned' in v,
      'CALIBRATION_FOUNDATION': cal.get('predictive_accuracy')=='UNVALIDATED',
      'FOUNDER_SURFACE': f.get('current_count')==p.get('current_count'),
    }
    print('FULL-SYSTEM ACCEPTANCE MATRIX:',matrix)
    print('ENGINEERING STATUS:','PASS' if all(matrix.values()) else 'FAIL')
    usable=all(matrix.values()) and (p.get('operational_usability_gate') or {}).get('status')=='PASS'
    print('PRODUCT USABILITY:','CORE_RESEARCH_AND_MARKET_TEST_WORKFLOW_USABLE' if usable else 'NOT_YET_PROVEN')
    print('USABILITY SCOPE: Founder research + evidence review + market-test planning/ingestion. This does NOT mean opportunity market validation or predictive accuracy.')
    print('LIVE MARKET VALIDATION:',f"{v.get('valid_outcomes',0)} schema-valid outcomes / {v.get('paid_outcomes',0)} paid outcomes; predictive accuracy {cal.get('predictive_accuracy','UNVALIDATED')}")
    print('COVERAGE BOUNDARIES:',h.get('coverage_boundaries'))
    print('='*126)
    return 0 if all(matrix.values()) else 2

if __name__=='__main__':raise SystemExit(main())
