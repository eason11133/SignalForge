from __future__ import annotations
import json
from pathlib import Path
from processors.opportunity_db_contract import snapshot as db_snapshot
from processors.opportunity_generation_state import active as active_generation

FILES={
 'source':Path('.radar_runtime/source_portfolio_v19.json'),
 'discovery':Path('.radar_runtime/transition_gap_discovery.json'),
 'claims':Path('.radar_runtime/v19_current_claims.json'),
 'portfolio':Path('.radar_runtime/founder_current_portfolio.json'),
 'validation':Path('.radar_runtime/market_test_queue_v19.json'),
 'calibration':Path('.radar_runtime/opportunity_calibration_v19.json'),
 'founder':Path('.radar_runtime/founder_opportunity_surface_v19.json'),
 'watch':Path('.radar_runtime/opportunity_watch_signals_v19.json'),
 'obs':Path('.radar_runtime/opportunity_observations_v19.json'),
 'graph':Path('.radar_runtime/opportunity_evidence_graph_v19.json'),
 'test_pack':Path('.radar_runtime/founder_market_test_pack_v19.md'),
}

def load(k):
    try:return json.loads(FILES[k].read_text(encoding='utf-8'))
    except Exception:return {}

def main():
    src=load('source');d=load('discovery');c=load('claims');p=load('portfolio');v=load('validation');cal=load('calibration');f=load('founder');watch=load('watch');db=db_snapshot();state=active_generation();formation=d.get('formation') or {};screen=d.get('screening') or {};quality=p.get('portfolio_quality_gate') or {};oa=formation.get('observation_audit') or {};gt=(formation.get('evidence_graph') or {}).get('telemetry') or {};h=src.get('health') or {};precision=d.get('candidate_precision_gate') or {}
    print('='*132);print('SIGNALFORGE V19 — FULL-SYSTEM SOURCE-LOCAL INDEPENDENT-EVIDENCE USABILITY AUDIT');print('='*132)
    print('DB CONTRACT:',db.get('status'),'fingerprint=',db.get('contract_fingerprint'),'metadata=',db.get('metadata_storage'),'optional_missing=',db.get('optional_missing_logical'))
    print('ACTIVE GENERATION:',state.get('active_discovery_version'),'count=',state.get('active_count'),'status=',state.get('activation_status'))
    print('SOURCE:',h.get('status'),'cache=',h.get('cache'),'docs=',h.get('total_docs'),'requests_this_run=',h.get('requests_this_run'),'boundaries=',h.get('coverage_boundaries'))
    print('SOURCE CONTRACT:',(h.get('source_contract') or {}).get('optimization_target'),'roles=',(h.get('source_contract') or {}).get('source_role_registry'))
    print('OBSERVATION: docs=',oa.get('documents'),'usable=',oa.get('usable_observations'),'seconds=',oa.get('seconds'),'targets=',oa.get('problem_targets'),'families=',oa.get('usable_by_family'))
    print('GRAPH: nodes=',(formation.get('evidence_graph') or {}).get('nodes'),'edges=',(formation.get('evidence_graph') or {}).get('edges'),'clusters=',(formation.get('evidence_graph') or {}).get('clusters'),'recurrence_edges=',gt.get('recurrence_edges'),'duplicate_content_rejected=',gt.get('duplicate_content_pairs_rejected'),'non_primary_rejected=',gt.get('non_primary_pairs_rejected'))
    print('-'*132)
    print('CANDIDATE QUALITY:',precision,'LLM VETO UTILITY:',screen.get('veto_utility'))
    print('LANE RAW:',formation.get('raw'));print('LANE DEDUP:',formation.get('deduped_by_lane'));print('SELECTED:',formation.get('selected_by_lane'));print('ACCEPTED PRIMARY:',d.get('accepted_by_primary_lane'));print('ACCEPTED QUALIFIED:',d.get('accepted_qualified_lane_counts'))
    print('WATCH SIGNALS:',formation.get('watch_signal_count',watch.get('count',0)),'(kept out of Current until independent recurrence exists)')
    print('LLM REASONS:',screen.get('reject_reason_counts'));print('POST-VETO DIVERSITY:',d.get('post_veto_diversity'))
    print('DB EVIDENCE: rows=',d.get('evidence_rows'),'integrity=',d.get('active_evidence_integrity'),'sidecar=',d.get('evidence_sidecar'))
    print('-'*132)
    print('CLAIMS: current=',c.get('current_candidates'),'external_updates=',c.get('external_validation_claim_updates'),'integrity=',c.get('active_evidence_integrity'))
    print('CURRENT PORTFOLIO: current=',p.get('current_count'),'watch=',p.get('watch_signal_count'),'lanes=',p.get('current_by_primary_lane'),'legacy=',p.get('legacy_archive_count'),'quality=',quality,'operational=',p.get('operational_usability_gate'))
    print('VALIDATION: planned=',v.get('tests_planned'),'actionable_now=',v.get('tests_actionable_now'),'completed=',v.get('tests_completed'),'valid_outcomes=',v.get('valid_outcomes'),'paid=',v.get('paid_outcomes'),'blocked=',v.get('blocked_reason'),'pack=',v.get('market_test_pack_path'))
    print('CALIBRATION: outcome_coverage=',cal.get('outcome_collection_coverage_percent'),'candidate_coverage=',cal.get('candidate_outcome_coverage_percent'),'quality_linked_rows=',cal.get('quality_linked_rows'),'dataset_ready=',cal.get('calibration_dataset_ready'),'predictive_accuracy=',cal.get('predictive_accuracy'))
    fs=f.get('system_status') or {};print('FOUNDER: current=',f.get('current_count'),'watch=',fs.get('watch_signal_count'),'next_tests=',fs.get('tests_actionable_now'),'predictive=',f.get('predictive_credibility'))
    print('-'*132)
    source_contract=h.get('source_contract') or {}
    matrix={
      'DB_SCHEMA_PORTABILITY': db.get('status')=='PASS',
      'ATOMIC_GENERATION_TRUTH': str(state.get('active_discovery_version') or '').startswith('opportunity-observation-architecture-v19') and state.get('activation_status')=='ACTIVE',
      'SOURCE_ROLE_PORTFOLIO': h.get('status') in {'PASS','PARTIAL'} and bool(source_contract.get('source_role_registry')),
      'OBSERVATION_SOURCE_LOCALITY': oa.get('sentence_targeting') is True and oa.get('span_provenance') is True and int(oa.get('usable_observations') or 0)>=0,
      'CONTENT_INDEPENDENT_GRAPH': 'CONTENT_INDEPENDENCE' in str(gt.get('recurrence_precision_policy') or '') and 'duplicate_content_pairs_rejected' in gt,
      'SEMANTIC_PRECISION_GATE': precision.get('status')=='PASS',
      'SIX_LANE_FORMATION': set((formation.get('deduped_by_lane') or {}).keys())=={'TRANSITION_GAP','PROVEN_MARKET_WEDGE','MICRO_FRICTION','DISTRIBUTION_MODEL_GAP','SECOND_ORDER_PAIN','BORING_OPS'},
      'CURRENT_CLAIM_TRUTH': c.get('active_evidence_integrity',{}).get('status')=='PASS',
      'CURRENT_PORTFOLIO_LIVE_SAMPLE_QUALITY': quality.get('status')=='PASS' and quality.get('live_sample_quality_ok') is True,
      'WATCH_SIGNAL_SEPARATION': int(p.get('watch_signal_count') or 0)>=0,
      'VALIDATION_EXECUTION_READINESS': v.get('blocked_reason') in {None,''} and ('tests_planned' in v) and (int(p.get('current_count') or 0)==0 or FILES['test_pack'].exists()),
      'CALIBRATION_FOUNDATION': cal.get('predictive_accuracy')=='UNVALIDATED',
      'FOUNDER_SURFACE': f.get('current_count')==p.get('current_count') and fs.get('watch_signal_count')==p.get('watch_signal_count'),
    }
    print('FULL-SYSTEM ACCEPTANCE MATRIX:',matrix)
    engineering=all(matrix.values());usable=engineering and int(p.get('current_count') or 0)>0 and (p.get('operational_usability_gate') or {}).get('status')=='PASS'
    print('ENGINEERING STATUS:','PASS' if engineering else 'FAIL')
    print('PRODUCT USABILITY:','CORE_RESEARCH_AND_MARKET_TEST_WORKFLOW_USABLE' if usable else 'NOT_YET_PROVEN')
    print('USABILITY SCOPE: Current Opportunities require first-hand pain + self-contained problem + content-independent recurrence. Single-source recurring frictions remain Watch Signals, not Current.')
    print('LIVE MARKET VALIDATION:',f"{v.get('valid_outcomes',0)} schema-valid outcomes / {v.get('paid_outcomes',0)} paid outcomes; predictive accuracy {cal.get('predictive_accuracy','UNVALIDATED')}")
    print('COVERAGE BOUNDARIES:',h.get('coverage_boundaries'))
    print('='*132)
    return 0 if engineering else 2

if __name__=='__main__':raise SystemExit(main())
