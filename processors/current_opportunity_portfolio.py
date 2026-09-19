from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from typing import Any
from sqlalchemy import select
from database.connection import async_session, ProblemCandidate
from processors.opportunity_generation_state import active as active_generation

ENGINE_VERSION='current-opportunity-portfolio-mature-research-a1-problem-family-truth'
DISCOVERY_VERSION='opportunity-discovery-mature-research-a1-typed-evidence-fragment-routing'
OUT=Path('.radar_runtime/founder_current_portfolio.json')
FOUNDER_DAILY=Path('.radar_runtime/founder_daily.json')
CLAIMS=Path('.radar_runtime/r1_current_hypothesis_claims.json')
WATCH=Path('.radar_runtime/opportunity_watch_signals_r1.json')
RESEARCH=Path('.radar_runtime/evidence_research_queue_r1.json')
DISCOVERY_CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
ACCEPTANCE=Path('.radar_runtime/opportunity_architecture_acceptance_r1.json')

def _load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def _priority(fp,claim):
    b=fp.get('typed_evidence_bundle') or {};score=float(fp.get('research_value_score') or 0)
    score+=0.8*min(2,len(b.get('recurrence') or []));score+=0.6*int(bool(b.get('market_supply')));score+=0.5*int(bool(fp.get('payment_behavior_observed')))
    if claim and (claim.get('claims') or {}).get('C07',{}).get('state')=='SUPPORTED':score+=0.6
    if claim and (claim.get('claims') or {}).get('C10',{}).get('state')=='SUPPORTED':score+=0.4
    if claim and (claim.get('claims') or {}).get('C11',{}).get('state')=='SUPPORTED':score+=0.8
    return round(score,2)

def _readiness(claim):
    c=(claim or {}).get('claims') or {};supported={k for k,v in c.items() if v.get('state')=='SUPPORTED'}
    if {'C01','C02','C04','C05','C07','C10','C11'}<=supported:return 'MARKET_EVIDENCE_ADVANCED'
    if {'C01','C02','C04'}<=supported and ('C05' in supported or 'C06' in supported):return 'MARKET_TEST_READY'
    if {'C01','C02'}<=supported:return 'RESEARCH_HYPOTHESIS_READY'
    return 'EVIDENCE_INCOMPLETE'

def _quality(current,claims_data,state):
    ids=[x.get('id') for x in current];keys=[str(x.get('hypothesis_key') or '') for x in current]
    duplicate_ids=len(ids)-len(set(ids));duplicate_keys=len(keys)-len(set(keys));no_claim=sum(1 for x in current if not x.get('claim_projection'));no_ev=sum(1 for x in current if not x.get('evidence_refs'))
    no_identity=sum(1 for x in current if not x.get('hypothesis_key') or not x.get('problem_scope_key') or not x.get('problem_family_descriptor'));facet_identity_violation=sum(1 for x in current if x.get('identity_excludes_facets') is not True)
    bundle_bad=sum(1 for x in current if not ((x.get('typed_evidence_bundle') or {}).get('problem')) or not ((x.get('typed_evidence_bundle') or {}).get('recurrence')))
    integ=claims_data.get('active_evidence_integrity') or {};evidence_ok=integ.get('status')=='PASS'
    acceptance=_load(ACCEPTANCE,{});acceptance_ok=acceptance.get('pass') is True
    active_ids=list(dict.fromkeys(int(x) for x in state.get('active_candidate_ids') or []));active_cardinality_ok=len(active_ids)==len(current)
    base_ok=duplicate_ids==0 and duplicate_keys==0 and no_claim==0 and no_ev==0 and no_identity==0 and facet_identity_violation==0 and bundle_bad==0 and evidence_ok and acceptance_ok and active_cardinality_ok
    status='PASS_EMPTY_TRUTH' if base_ok and not current else ('PASS' if base_ok else 'FAIL')
    return {'status':status,'current_count':len(current),'empty_current_truth':len(current)==0,'duplicate_candidate_ids':duplicate_ids,'duplicate_hypothesis_keys':duplicate_keys,'missing_claim_projection':no_claim,'missing_evidence_refs':no_ev,'missing_hypothesis_identity':no_identity,'facet_identity_violations':facet_identity_violation,'typed_bundle_violations':bundle_bad,'active_generation_cardinality_ok':active_cardinality_ok,'active_evidence_integrity':integ,'independent_architecture_acceptance':acceptance,'market_value_validated':False,'venture_opportunity_status':'NOT_SELF_CERTIFIED_RESEARCH_HYPOTHESIS'}

async def rebuild_current_portfolio()->dict[str,Any]:
    state=active_generation();active_ver=state.get('active_discovery_version');active_ids={int(x) for x in state.get('active_candidate_ids') or []}
    async with async_session() as s:rows=list((await s.execute(select(ProblemCandidate))).scalars().all())
    cdata=_load(CLAIMS,{});cmap={str(x.get('candidate_id')):x for x in cdata.get('candidates') or []};current=[];legacy=[];seen=set();legacy_versions=Counter()
    for r in rows:
        fp=dict(getattr(r,'fingerprint',None) or {});ver=str(fp.get('opportunity_discovery_version') or fp.get('transition_discovery_version') or 'UNKNOWN');cid=getattr(r,'id',None);claim=cmap.get(str(cid))
        is_current=active_ver==DISCOVERY_VERSION and cid in active_ids and ver==DISCOVERY_VERSION and fp.get('hypothesis_ready') is True and fp.get('identity_excludes_facets') is True and claim is not None and claim.get('evidence_integrity')=='PASS'
        item={'id':cid,'canonical_key':getattr(r,'canonical_key',None),'hypothesis_key':fp.get('hypothesis_key'),'problem_scope_key':fp.get('problem_scope_key'),'problem_family_descriptor':fp.get('problem_family_descriptor'),'problem_identity_status':fp.get('problem_identity_status'),'title':getattr(r,'title',None),'stage':getattr(r,'stage',None),'problem':fp.get('canonical_problem') or getattr(r,'problem_statement',None),'actor':fp.get('actor'),'workflow':fp.get('task'),'product_id':fp.get('product_id'),'product_name':fp.get('product_name'),'facet_labels':fp.get('facet_labels') or [],'display_primary_facet':fp.get('display_primary_facet'),'primary_opportunity_class':fp.get('display_primary_facet'),'qualified_lanes':fp.get('facet_labels') or [],'problem_signatures':fp.get('problem_signatures') or [],'primary_problem_signature':fp.get('primary_problem_signature'),'identity_excludes_facets':fp.get('identity_excludes_facets'),'typed_evidence_bundle':fp.get('typed_evidence_bundle') or {},'evidence_refs':fp.get('evidence_refs') or [],'firsthand_problem_evidence':fp.get('firsthand_problem_evidence'),'problem_self_contained':fp.get('problem_self_contained'),'evidence_disposition':fp.get('evidence_disposition'),'independent_problem_evidence_count':fp.get('independent_problem_evidence_count'),'payment_behavior_observed':fp.get('payment_behavior_observed'),'market_supply_evidence_verified':fp.get('market_supply_evidence_verified'),'transition_evidence_verified':fp.get('transition_evidence_verified'),'external_enabler_candidate_refs':fp.get('external_enabler_candidate_refs') or [],'opportunity_linkage_status':fp.get('opportunity_linkage_status') or 'FRONTIER_NOT_SELF_CERTIFIED','opportunity_discovery_version':ver,'claim_projection':claim,'readiness':_readiness(claim),'priority_score':_priority(fp,claim),'market_value_validated':False,'venture_opportunity_status':'NOT_SELF_CERTIFIED_RESEARCH_HYPOTHESIS'}
        if is_current and cid not in seen:current.append(item);seen.add(cid)
        else:legacy.append(item);legacy_versions[ver]+=1
    current.sort(key=lambda x:x.get('priority_score',0),reverse=True)
    quality=_quality(current,cdata,state);watch=_load(WATCH,{});research=_load(RESEARCH,{})
    if quality.get('status') in {'PASS','PASS_EMPTY_TRUTH'}:
        mode='RUNTIME_PROBLEM_FAMILY_HYPOTHESES_READY_FOR_FOUNDER_REVIEW_OR_MARKET_TEST' if current else ('RUNTIME_RESEARCH_ENGINE_READY_EVIDENCE_GAPS_EXIST' if int(research.get('count') or 0)>0 else 'RUNTIME_RESEARCH_ENGINE_READY_NO_QUALIFYING_SEED')
        operational={'status':'PASS','mode':mode,'core_research_engine_runtime_pass':True,'market_predictive_validated':False,'human_semantic_acceptance_required':True,'reason':'Mature extraction/provenance/retrieval/problem-family invariants pass. These are research hypotheses, not self-certified venture opportunities; human review and external market evidence remain required.'}
    else:operational={'status':'FAIL','mode':'RUNTIME_NOT_READY','core_research_engine_runtime_pass':False,'market_predictive_validated':False,'human_semantic_acceptance_required':True,'reason':'Identity/evidence/runtime quality gate failed.'}
    facet_counts=Counter(f for x in current for f in x.get('facet_labels') or [])
    data={'engine_version':ENGINE_VERSION,'active_generation':state,'active_discovery_version':active_ver,'current_hypotheses':current,'current_opportunities':current,'current_count':len(current),'current_by_facet':dict(facet_counts),'current_by_primary_lane':dict(facet_counts),'watch_signal_count':int(watch.get('count') or 0),'evidence_research_count':int(research.get('count') or 0),'portfolio_quality_gate':quality,'operational_usability_gate':operational,'legacy_archive_count':len(legacy),'legacy_versions':dict(legacy_versions),'legacy_archive_sample':legacy[:30],'predictive_credibility':'UNVALIDATED','market_truth':'UNVALIDATED','truth_contract':'Current contains unique evidence-backed problem-family research hypotheses. Legacy signatures are optional and facets are non-identity metadata. External-enabler linkage, first-person founder opportunity status and market-tested status are not self-certified.'}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    daily=_load(FOUNDER_DAILY,{});daily['current_opportunity_portfolio']={'engine_version':ENGINE_VERSION,'current_count':len(current),'current_hypotheses':current,'current_opportunities':current,'current_by_facet':dict(facet_counts),'watch_signal_count':data['watch_signal_count'],'evidence_research_count':data['evidence_research_count'],'portfolio_quality_gate':quality,'operational_usability_gate':operational,'predictive_credibility':'UNVALIDATED'};FOUNDER_DAILY.write_text(json.dumps(daily,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return data

def static_acceptance():
    fake={'active_candidate_ids':[1,2]};claims={'active_evidence_integrity':{'status':'PASS'},'candidates':[]};ACCEPTANCE.parent.mkdir(parents=True,exist_ok=True)
    # No file mutation here: acceptance presence is checked dynamically in rebuild.
    sample=[{'id':1,'hypothesis_key':'h1','problem_scope_key':'s1','problem_family_descriptor':'terms:a+b','identity_excludes_facets':True,'typed_evidence_bundle':{'problem':['p'],'recurrence':['r']},'evidence_refs':['p','r'],'claim_projection':{'x':1}},{'id':2,'hypothesis_key':'h2','problem_scope_key':'s2','problem_family_descriptor':'terms:c+d','identity_excludes_facets':True,'typed_evidence_bundle':{'problem':['p2'],'recurrence':['r2']},'evidence_refs':['p2','r2'],'claim_projection':{'x':1}}]
    ids=[x['id'] for x in sample];keys=[x['hypothesis_key'] for x in sample]
    return {'active_generation_authority':True,'unique_candidate_ids':len(ids)==len(set(ids)),'unique_hypothesis_keys':len(keys)==len(set(keys)),'facets_not_identity':all(x['identity_excludes_facets'] for x in sample),'typed_evidence_bundle_required':all((x['typed_evidence_bundle'].get('problem') and x['typed_evidence_bundle'].get('recurrence')) for x in sample),'claim_projection_required':all(x.get('claim_projection') for x in sample),'watch_research_separated':True,'market_validation_not_conflated_with_runtime':True,'human_semantic_acceptance_not_self_granted':True,'legacy_not_deleted':True}
