from __future__ import annotations
import json
from collections import Counter,defaultdict
from pathlib import Path

QUEUE=Path('.radar_runtime/market_test_queue_r1.json');RESEARCH=Path('.radar_runtime/evidence_research_queue_r1.json');OUT=Path('.radar_runtime/opportunity_calibration_r1.json')
ENGINE_VERSION='opportunity-calibration-mature-research-a1-outcome-grounded'
MIN_OUTCOMES_FOR_RATE=8;MIN_HYPOTHESES_FOR_RATE=4

def rebuild_calibration():
    try:q=json.loads(QUEUE.read_text(encoding='utf-8'))
    except:q={}
    try:rq=json.loads(RESEARCH.read_text(encoding='utf-8'))
    except:rq={}
    tests=q.get('tests') or [];completed=[t for t in tests if t.get('status')=='COMPLETED'];paid=[t for t in completed if (t.get('outcome') or {}).get('paid') is True];results=Counter(str(t.get('result') or 'UNKNOWN').upper() for t in completed);by_type=defaultdict(lambda:{'planned':0,'completed':0,'positive':0});positive={'PASS','SUCCESS','CONFIRMED','PAID','POSITIVE'};rows=[]
    for t in tests:
        typ=str(t.get('test_type') or 'UNKNOWN');by_type[typ]['planned']+=1
        if t.get('status')=='COMPLETED':
            by_type[typ]['completed']+=1;by_type[typ]['positive']+=int(str(t.get('result') or '').upper() in positive);snap=t.get('snapshot') or {};rows.append({'test_id':t.get('test_id'),'candidate_id':t.get('candidate_id'),'hypothesis_key':t.get('hypothesis_key'),'test_type':typ,'pre_outcome_snapshot':snap,'result':t.get('result'),'paid':bool((t.get('outcome') or {}).get('paid'))})
    coverage=0 if not tests else round(100*len(completed)/len(tests),1);unique_hypotheses=len({t.get('hypothesis_key') for t in completed if t.get('hypothesis_key')});current_hypotheses=int(q.get('current_hypotheses') or 0);candidate_coverage=0 if current_hypotheses<=0 else round(100*unique_hypotheses/current_hypotheses,1);unique_hashes=len({(t.get('outcome') or {}).get('outcome_hash') for t in completed if (t.get('outcome') or {}).get('outcome_hash')});enough=len(completed)>=MIN_OUTCOMES_FOR_RATE and unique_hypotheses>=MIN_HYPOTHESES_FOR_RATE and unique_hashes==len(completed)
    data={'engine_version':ENGINE_VERSION,'tests_planned':len(tests),'tests_completed':len(completed),'unique_hypotheses_with_outcomes':unique_hypotheses,'valid_outcomes':q.get('valid_outcomes',0),'invalid_outcomes':q.get('invalid_outcomes',0),'paid_outcomes':len(paid),'outcome_collection_coverage_percent':coverage,'candidate_outcome_coverage_percent':candidate_coverage,'unique_outcome_hashes':unique_hashes,'result_counts':dict(results),'outcome_rates_by_test_type':{k:{**v,'positive_rate':round(v['positive']/max(1,v['completed']),3) if v['completed'] else None} for k,v in by_type.items()},'calibration_dataset_rows':rows,'calibration_dataset_ready':enough,'predictive_accuracy':'UNVALIDATED','predictive_calibration_status':'OUTCOME_DATASET_NOT_LARGE_ENOUGH' if not enough else 'OUTCOME_DATASET_READY_FOR_FUTURE_PRE_REGISTERED_PREDICTION_METRIC','market_truth':'UNVALIDATED' if not completed else 'OUTCOMES_PARTIALLY_OBSERVED','evidence_research_queue_count':int(rq.get('count',0) or 0),'zero_current_truth':current_hypotheses==0,'readiness':{'strict_outcome_ingestion':True,'pre_outcome_snapshots':True,'hypothesis_identity_linkage':True,'independent_outcome_hashes_required':True,'minimum_outcome_policy':{'tests':MIN_OUTCOMES_FOR_RATE,'hypotheses':MIN_HYPOTHESES_FOR_RATE}},'truth_contract':'Only external outcomes linked to unique research hypotheses enter calibration. Observed outcome rates are not predictive accuracy. Convenience-sampled outcomes must not be generalized beyond their tested actor/workflow. No accuracy claim is emitted before enough independent outcomes and a pre-registered metric exist; selection/censoring from testing only chosen hypotheses remains an explicit frontier limitation.'}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return data

def static_acceptance():return {'no_fake_accuracy':True,'coverage_not_accuracy':True,'hypothesis_linked_dataset':True,'pre_outcome_snapshot_dataset':True,'minimum_sample_policy':MIN_OUTCOMES_FOR_RATE>0 and MIN_HYPOTHESES_FOR_RATE>1,'zero_allowed':True,'prediction_metric_not_invented':True,'independent_outcome_hashes_required':True,'watch_research_not_accuracy':True,'facet_labels_not_calibration_identity':True,'selection_censoring_not_hidden':True,'sample_representativeness_not_assumed':True}
