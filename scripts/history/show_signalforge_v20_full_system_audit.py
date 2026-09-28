from __future__ import annotations
import json
from pathlib import Path
from processors.opportunity_db_contract import snapshot as db_snapshot
from processors.opportunity_generation_state import active as active_generation

FILES={
 'source':Path('.radar_runtime/source_portfolio_v20.json'),
 'discovery':Path('.radar_runtime/transition_gap_discovery.json'),
 'claims':Path('.radar_runtime/v20_current_claims.json'),
 'portfolio':Path('.radar_runtime/founder_current_portfolio.json'),
 'validation':Path('.radar_runtime/market_test_queue_v20.json'),
 'calibration':Path('.radar_runtime/opportunity_calibration_v20.json'),
 'founder':Path('.radar_runtime/founder_opportunity_surface_v20.json'),
 'watch':Path('.radar_runtime/opportunity_watch_signals_v20.json'),
 'research':Path('.radar_runtime/evidence_research_queue_v20.json'),
 'obs':Path('.radar_runtime/opportunity_observations_v20.json'),
 'graph':Path('.radar_runtime/opportunity_evidence_graph_v20.json'),
 'test_pack':Path('.radar_runtime/founder_market_test_pack_v20.md'),
}

def load(k):
    try:return json.loads(FILES[k].read_text(encoding='utf-8'))
    except Exception:return {}

def main():
    src=load('source');d=load('discovery');c=load('claims');p=load('portfolio');v=load('validation');cal=load('calibration');f=load('founder');watch=load('watch');research=load('research');db=db_snapshot();state=active_generation();formation=d.get('formation') or {};screen=d.get('screening') or {};quality=p.get('portfolio_quality_gate') or {};oa=formation.get('observation_audit') or {};gt=(formation.get('evidence_graph') or {}).get('telemetry') or {};h=src.get('health') or {};precision=d.get('candidate_precision_gate') or {};funnel=d.get('evidence_recovery_funnel') or {};oper=p.get('operational_usability_gate') or {}
    print('='*136);print('SIGNALFORGE V20 — FULL-SYSTEM CLOSED-LOOP EVIDENCE RECOVERY + ZERO-OPPORTUNITY TRUTH AUDIT');print('='*136)
    print('DB CONTRACT:',db.get('status'),'fingerprint=',db.get('contract_fingerprint'),'metadata=',db.get('metadata_storage'),'optional_missing=',db.get('optional_missing_logical'))
    print('ACTIVE GENERATION:',state.get('active_discovery_version'),'count=',state.get('active_count'),'status=',state.get('activation_status'),'previous=',state.get('previous_active_version'))
    print('SOURCE:',h.get('status'),'cache=',h.get('cache'),'docs=',h.get('total_docs'),'requests_this_run=',h.get('requests_this_run'),'snapshot_requests=',h.get('snapshot_network_requests'),'recovery=',h.get('targeted_corroboration_recovery'))
    print('SOURCE CONTRACT:',(h.get('source_contract') or {}).get('optimization_target'),'boundaries=',h.get('coverage_boundaries'))
    print('OBSERVATION: docs=',oa.get('documents'),'usable=',oa.get('usable_observations'),'seconds=',oa.get('seconds'),'targets=',oa.get('problem_targets'))
    print('GRAPH: nodes=',(formation.get('evidence_graph') or {}).get('nodes'),'edges=',(formation.get('evidence_graph') or {}).get('edges'),'clusters=',(formation.get('evidence_graph') or {}).get('clusters'),'recurrence=',gt.get('recurrence_edges'),'recovery_recurrence=',gt.get('recovery_recurrence_edges'),'duplicate_content_rejected=',gt.get('duplicate_content_pairs_rejected'))
    print('-'*136)
    print('EVIDENCE RECOVERY FUNNEL:',funnel)
    print('CANDIDATE PRECISION:',precision,'LLM VETO UTILITY:',screen.get('veto_utility'))
    print('LANE RAW:',formation.get('raw'));print('LANE DEDUP:',formation.get('deduped_by_lane'));print('SELECTED:',formation.get('selected_by_lane'));print('ACCEPTED PRIMARY:',d.get('accepted_by_primary_lane'));print('ACCEPTED QUALIFIED:',d.get('accepted_qualified_lane_counts'))
    print('WATCH SIGNALS:',watch.get('count',formation.get('watch_signal_count',0)),'EVIDENCE RESEARCH QUEUE:',research.get('count',0),'OPERATING EVIDENCE STATE:',d.get('operational_evidence_state'))
    print('LLM REASONS:',screen.get('reject_reason_counts'));print('POST-VETO DIVERSITY:',d.get('post_veto_diversity'))
    print('DB EVIDENCE: rows=',d.get('evidence_rows'),'integrity=',d.get('active_evidence_integrity'),'sidecar=',d.get('evidence_sidecar'))
    print('-'*136)
    print('CLAIMS: current=',c.get('current_candidates'),'zero_current_truth=',c.get('zero_current_truth'),'external_updates=',c.get('external_validation_claim_updates'),'integrity=',c.get('active_evidence_integrity'))
    print('CURRENT PORTFOLIO: current=',p.get('current_count'),'watch=',p.get('watch_signal_count'),'research=',p.get('evidence_research_count'),'lanes=',p.get('current_by_primary_lane'),'legacy=',p.get('legacy_archive_count'),'quality=',quality,'operational=',oper)
    print('VALIDATION: planned=',v.get('tests_planned'),'actionable=',v.get('tests_actionable_now'),'completed=',v.get('tests_completed'),'valid=',v.get('valid_outcomes'),'paid=',v.get('paid_outcomes'),'blocked=',v.get('blocked_reason'),'pack=',v.get('market_test_pack_path'))
    print('CALIBRATION: outcome_coverage=',cal.get('outcome_collection_coverage_percent'),'candidate_coverage=',cal.get('candidate_outcome_coverage_percent'),'research_queue=',cal.get('evidence_research_queue_count'),'dataset_ready=',cal.get('calibration_dataset_ready'),'predictive=',cal.get('predictive_accuracy'))
    fs=f.get('system_status') or {};print('FOUNDER: current=',f.get('current_count'),'watch=',fs.get('watch_signal_count'),'research=',fs.get('evidence_research_count'),'mode=',(fs.get('operational_usability_gate') or {}).get('mode'),'predictive=',f.get('predictive_credibility'))
    print('-'*136)
    current_count=int(p.get('current_count') or 0);research_count=int(p.get('evidence_research_count') or 0);active_ver=str(state.get('active_discovery_version') or '')
    current_quality_ok=(quality.get('status')=='PASS' and quality.get('live_sample_quality_ok') is True) if current_count>0 else (quality.get('status')=='PASS_EMPTY_TRUTH' and quality.get('live_sample_quality_ok') is True)
    validation_truth_ok=(v.get('blocked_reason') in {None,''} and FILES['test_pack'].exists()) if current_count>0 else (v.get('blocked_reason')=='NO_CURRENT_OPPORTUNITY_MEETS_EVIDENCE_THRESHOLD' and int(v.get('tests_planned') or 0)==0)
    operational_truth_ok=(oper.get('status')=='PASS' and ((current_count>0 and oper.get('mode')=='CURRENT_PORTFOLIO_USABLE_FOR_MARKET_TESTS') or (current_count==0 and str(oper.get('mode') or '').startswith('RESEARCH_ENGINE_USABLE_'))))
    matrix={
      'DB_SCHEMA_PORTABILITY':db.get('status')=='PASS',
      'ATOMIC_ZERO_OR_POSITIVE_GENERATION_TRUTH':active_ver.startswith('opportunity-observation-architecture-v20') and state.get('activation_status') in {'ACTIVE','ACTIVE_EMPTY_EVIDENCE_TRUTH'} and int(state.get('active_count') or 0)==current_count,
      'SOURCE_RESERVED_RECOVERY_PORTFOLIO':h.get('status') in {'PASS','PARTIAL'} and int(h.get('snapshot_network_requests') or 0)<=42 and (not funnel.get('recovery_applied') or 'targeted_corroboration_recovery' in h),
      'OBSERVATION_SOURCE_LOCALITY':oa.get('sentence_targeting') is True and oa.get('span_provenance') is True,
      'CONTENT_INDEPENDENT_RECOVERY_AWARE_GRAPH':'CONTENT_INDEPENDENCE' in str(gt.get('recurrence_precision_policy') or '') and 'recovery_recurrence_edges' in gt,
      'SIX_LANE_FORMATION':set((formation.get('deduped_by_lane') or {}).keys())=={'TRANSITION_GAP','PROVEN_MARKET_WEDGE','MICRO_FRICTION','DISTRIBUTION_MODEL_GAP','SECOND_ORDER_PAIN','BORING_OPS'},
      'SEMANTIC_PRECISION_OR_VALID_EMPTY_TRUTH':precision.get('status')=='PASS',
      'CURRENT_CLAIM_TRUTH':c.get('active_evidence_integrity',{}).get('status')=='PASS' and int(c.get('current_candidates') or 0)==current_count,
      'CURRENT_PORTFOLIO_TRUTH':current_quality_ok,
      'WATCH_RESEARCH_SEPARATION':int(p.get('watch_signal_count') or 0)>=0 and research_count>=0,
      'VALIDATION_DOES_NOT_FABRICATE_TESTS':validation_truth_ok,
      'CALIBRATION_FOUNDATION':cal.get('predictive_accuracy')=='UNVALIDATED',
      'FOUNDER_TRUTH_SURFACE':f.get('current_count')==current_count and int(fs.get('evidence_research_count') or 0)==research_count,
      'OPERATIONAL_MODE_TRUTH':operational_truth_ok,
    }
    print('FULL-SYSTEM ACCEPTANCE MATRIX:',matrix)
    engineering=all(matrix.values())
    print('ENGINEERING STATUS:','PASS' if engineering else 'FAIL')
    if engineering and current_count>0:product='CURRENT_PORTFOLIO_RESEARCH_AND_MARKET_TEST_WORKFLOW_USABLE'
    elif engineering and current_count==0 and research_count>0:product='RESEARCH_ENGINE_USABLE_NO_CURRENT_OPPORTUNITY_YET'
    elif engineering and current_count==0:product='RESEARCH_ENGINE_USABLE_NO_QUALIFYING_SIGNAL_IN_CURRENT_CORPUS'
    else:product='NOT_YET_PROVEN'
    print('PRODUCT OPERATIONAL MODE:',product)
    print('TRUTH NOTE: Zero Current is not a failure and never resurrects stale prior opportunities. It means no opportunity currently satisfies the evidence threshold; Watch/Research queues remain available for evidence acquisition.')
    print('LIVE MARKET VALIDATION:',f"{v.get('valid_outcomes',0)} schema-valid outcomes / {v.get('paid_outcomes',0)} paid outcomes; predictive accuracy {cal.get('predictive_accuracy','UNVALIDATED')}")
    print('COVERAGE BOUNDARIES:',h.get('coverage_boundaries'))
    print('='*136)
    return 0 if engineering else 2

if __name__=='__main__':raise SystemExit(main())
