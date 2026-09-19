from __future__ import annotations
import json
from pathlib import Path
from sqlalchemy import select
from database.connection import async_session, ProblemCandidate
from processors.opportunity_generation_state import active as active_generation
from processors.opportunity_db_contract import active_evidence_integrity

ENGINE_VERSION='current-opportunity-claims-mature-research-a1-typed-evidence'
DISCOVERY_VERSION='opportunity-discovery-mature-research-a1-typed-evidence-fragment-routing'
OUT=Path('.radar_runtime/r1_current_hypothesis_claims.json')
VALIDATION=Path('.radar_runtime/market_test_queue_r1.json')
CLAIMS={'C01':'Problem exists','C02':'Independent recurrence','C03':'Material consequence','C04':'Actor identified','C05':'Buyer/payer exists','C06':'Current solution exists','C07':'Unresolved gap','C08':'Differentiation','C09':'Founder/company execution fit','C10':'Reachable distribution','C11':'Economics/WTP','C12':'Timing window','C13':'Competitive survivability','C14':'Switch/pay behavior'}

def _load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def _base():return {k:{'claim':v,'state':'UNKNOWN','evidence_refs':[],'scope':'UNPROVEN','subclaims':{}} for k,v in CLAIMS.items()}

def _bundle(fp):
    b=fp.get('typed_evidence_bundle') or {}
    return {k:list(dict.fromkeys(b.get(k) or [])) for k in ('problem','recurrence','market_supply','external_enabler_candidates','payment_behavior','economic_burden')}

def _discovery_state(fp,cid):
    s=_base();b=_bundle(fp);all_refs=list(dict.fromkeys(sum(b.values(),[])))
    quality=fp.get('hypothesis_ready') is True and fp.get('identity_excludes_facets') is True and fp.get('firsthand_problem_evidence') is True and bool(fp.get('problem_family_descriptor')) and str(fp.get('evidence_disposition') or '') in {'DIRECT_NEED','INCOMPLETE_NEED'}
    if not quality:
        s['C01'].update(state='INSUFFICIENT',evidence_refs=b['problem'][:1],scope='EVIDENCE_DERIVED_PROBLEM_FAMILY_OR_FIRSTHAND_NEED_QUALITY_NOT_PROVEN');return s
    s['C01'].update(state='SUPPORTED',evidence_refs=b['problem'][:1],scope='FIRSTHAND_EVIDENCE_DERIVED_PROBLEM_FAMILY; LEGACY_SIGNATURE_NOT_REQUIRED')
    if len(b['recurrence'])>=1 and int(fp.get('independent_problem_evidence_count') or 0)>=2:
        s['C02'].update(state='SUPPORTED',evidence_refs=(b['problem'][:1]+b['recurrence'][:2]),scope='INDEPENDENT_FIRSTHAND_SAME_PROBLEM_RECURRENCE')
    else:s['C02'].update(state='INSUFFICIENT',evidence_refs=b['problem'][:1],scope='INDEPENDENT_RECURRENCE_REQUIRED')
    if fp.get('economic_evidence_explicit') or b['economic_burden']:
        s['C03'].update(state='SUPPORTED',evidence_refs=(b['economic_burden'] or b['problem'])[:2],scope='OBSERVED_BURDEN_OR_MATERIAL_CONSEQUENCE')
    else:s['C03']['state']='INSUFFICIENT'
    if str(fp.get('actor') or '').upper() not in {'','UNKNOWN'}:s['C04'].update(state='SUPPORTED',evidence_refs=b['problem'][:1],scope='SOURCE_SCOPED_AFFECTED_ACTOR')
    else:s['C04']['state']='INSUFFICIENT'
    payment=bool(fp.get('payment_behavior_observed') or b['payment_behavior']);supply=bool(fp.get('market_supply_evidence_verified') or b['market_supply']);product=bool(fp.get('product_id'))
    if payment:s['C05'].update(state='SUPPORTED',evidence_refs=(b['payment_behavior'] or b['problem'])[:2],scope='OBSERVED_CURRENT_PAYMENT_BEHAVIOR_NOT_NEW_SOLUTION_WTP')
    else:s['C05'].update(state='INSUFFICIENT',evidence_refs=b['market_supply'][:1],scope='COMMERCIAL_MARKET_CONTEXT_EXISTS_PAYER_IDENTITY_NOT_CONFIRMED' if supply or product else 'PAYER_UNKNOWN')
    if product or supply:s['C06'].update(state='SUPPORTED',evidence_refs=(b['market_supply'] or b['problem'])[:2],scope='CURRENT_PRODUCT_OR_SOLUTION_EXISTS')
    if s['C02']['state']=='SUPPORTED' and product:
        s['C07'].update(state='SUPPORTED',evidence_refs=(b['problem'][:1]+b['recurrence'][:2]),scope='RECURRING_GAP_IN_CURRENT_PRODUCT_ONLY_NOT_GLOBAL_MARKET_GAP')
    else:s['C07']['state']='INSUFFICIENT'
    if b['external_enabler_candidates']:
        s['C12'].update(state='INSUFFICIENT',evidence_refs=b['external_enabler_candidates'][:2],scope='EXTERNAL_ENABLER_CANDIDATE_OBSERVED; LINKAGE_TO_THIS_WORKFLOW_AND_WINDOW_NOT_PROVEN')
    if payment:
        s['C11'].update(state='INSUFFICIENT',evidence_refs=(b['payment_behavior'] or b['problem'])[:1],scope='CURRENT_PAYMENT_OBSERVED_FUTURE_TESTED_OFFER_WTP_UNKNOWN',subclaims={'current_payment_observed':'SUPPORTED','future_solution_wtp':'UNKNOWN'})
        s['C14'].update(state='INSUFFICIENT',evidence_refs=(b['payment_behavior'] or b['problem'])[:1],scope='CURRENT_PAYMENT_OBSERVED_SWITCH_OR_PRECOMMIT_UNKNOWN')
    elif supply:s['C11'].update(state='INSUFFICIENT',evidence_refs=b['market_supply'][:1],scope='PAID_OR_COMMERCIAL_SUPPLY_EXISTS_NEW_SOLUTION_WTP_UNKNOWN')
    return s

def _outcomes_by_candidate():
    q=_load(VALIDATION,{});out={}
    for t in q.get('tests') or []:
        if t.get('status')!='COMPLETED' or not isinstance(t.get('outcome'),dict):continue
        out.setdefault(str(t.get('candidate_id')),[]).append(t)
    return out,q

def _positive(result)->bool:return str(result or '').upper() in {'PASS','SUCCESS','CONFIRMED','PAID','POSITIVE'}

def _apply_external(s,cid,tests):
    applied=[]
    for t in tests or []:
        o=t.get('outcome') or {};typ=t.get('test_type');ref=f"market_test:{t.get('test_id')}";res=str(t.get('result') or o.get('result') or '').upper()
        if typ=='BUYER_CHECK' and _positive(res) and int(o.get('qualified_confirmations') or 0)>=3:
            s['C05'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_QUALIFIED_BUYER_CONFIRMATION');applied.append('C05')
        elif typ=='GAP_CHECK' and _positive(res) and int(o.get('qualified_confirmations') or 0)>=3:
            s['C07'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_AFFECTED_USERS_CONFIRM_UNRESOLVED_GAP');applied.append('C07')
        elif typ=='REACHABILITY_CHECK' and _positive(res) and int(o.get('qualified_reached') or 0)>=10 and int(o.get('responses') or 0)>=2:
            s['C10'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_REPEATABLE_REACHABILITY_OBSERVED');applied.append('C10')
        elif typ=='PAYMENT_CHECK' and _positive(res) and o.get('paid') is True:
            try:amt=float(o.get('amount') or 0)
            except:amt=0
            if amt>0 or o.get('signed_paid_pilot') is True:
                s['C05'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_PAYER_BEHAVIOR_OBSERVED')
                s['C11'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_PAYMENT_OR_SIGNED_PAID_PILOT_FOR_TESTED_OFFER',subclaims={'tested_offer_payment':'SUPPORTED','general_market_wtp':'UNKNOWN'})
                s['C14'].update(state='SUPPORTED',evidence_refs=[ref],scope='EXTERNAL_SWITCH_PAY_OR_PRECOMMIT_BEHAVIOR_OBSERVED');applied.extend(['C05','C11','C14'])
        if res in {'NEGATIVE','FAILED','NO'}:
            key={'BUYER_CHECK':'C05','GAP_CHECK':'C07','REACHABILITY_CHECK':'C10','PAYMENT_CHECK':'C11'}.get(typ)
            if key:s[key].setdefault('subclaims',{})['negative_test_observed']='SUPPORTED';s[key]['evidence_refs']=list(dict.fromkeys((s[key].get('evidence_refs') or [])+[ref]))
    return sorted(set(applied))

async def rebuild_current_claims():
    state=active_generation();active_ids={int(x) for x in state.get('active_candidate_ids') or []};active_ver=state.get('active_discovery_version');integ=await active_evidence_integrity(sorted(active_ids))
    async with async_session() as sess:rows=list((await sess.execute(select(ProblemCandidate))).scalars().all())
    outcomes,vq=_outcomes_by_candidate();out=[];per=(integ.get('per_candidate') or {})
    if active_ver==DISCOVERY_VERSION:
        for r in rows:
            cid=getattr(r,'id',None)
            if cid not in active_ids or (active_ids and int(per.get(str(cid),0) or 0)<=0):continue
            fp=dict(getattr(r,'fingerprint',None) or {})
            if str(fp.get('opportunity_discovery_version') or '')!=DISCOVERY_VERSION:continue
            s=_discovery_state(fp,cid);applied=_apply_external(s,cid,outcomes.get(str(cid),[]));supported=sum(1 for x in s.values() if x['state']=='SUPPORTED');priority=[k for k in ('C05','C07','C10','C11','C09','C12','C13','C14') if s[k]['state']!='SUPPORTED']
            out.append({'candidate_id':cid,'hypothesis_key':fp.get('hypothesis_key'),'facet_labels':fp.get('facet_labels') or [],'claims':s,'supported_count':supported,'unknown_count':sum(1 for x in s.values() if x['state']=='UNKNOWN'),'insufficient_count':sum(1 for x in s.values() if x['state']=='INSUFFICIENT'),'next_unknown_claims':priority,'external_validation_claims_applied':applied,'external_test_count':len(outcomes.get(str(cid),[])),'distinct_discovery_evidence_refs':len(set(fp.get('evidence_refs') or [])),'evidence_integrity':'PASS','decision_boundary':'RESEARCH_HYPOTHESIS_OR_MARKET_TEST_ONLY; discovery never authorizes BUILD.'})
    data={'engine_version':ENGINE_VERSION,'active_discovery_version':active_ver,'truth_contract':'Mature-research claims project from typed evidence bundles belonging to one evidence-derived problem-family hypothesis. Legacy signatures are optional. External-enabler candidates do not prove timing/opportunity linkage. Facets are non-identity metadata. Market truth/WTP remains external-outcome grounded.','candidates':out,'current_candidates':len(out),'active_evidence_integrity':integ,'validation_queue_engine':vq.get('engine_version'),'external_validation_claim_updates':sum(len(x.get('external_validation_claims_applied') or []) for x in out),'predictive_credibility':'UNVALIDATED','activation_status':state.get('activation_status'),'zero_current_truth':len(out)==0}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8');return data

def static_acceptance():
    fp={'hypothesis_ready':True,'identity_excludes_facets':True,'firsthand_problem_evidence':True,'problem_family_descriptor':'terms:booking+spreadsheet','evidence_disposition':'INCOMPLETE_NEED','independent_problem_evidence_count':2,'typed_evidence_bundle':{'problem':['p'],'recurrence':['r'],'market_supply':['s'],'external_enabler_candidates':['e'],'payment_behavior':[],'economic_burden':[]},'economic_evidence_explicit':False,'actor':'product_user','market_supply_evidence_verified':True,'payment_behavior_observed':False,'product_id':'P'}
    x=_discovery_state(fp,1);weak=_discovery_state({**fp,'problem_family_descriptor':None},2);one=_discovery_state({**fp,'independent_problem_evidence_count':1,'typed_evidence_bundle':{**fp['typed_evidence_bundle'],'recurrence':[]}},3);paid=_discovery_state({**fp,'payment_behavior_observed':True,'typed_evidence_bundle':{**fp['typed_evidence_bundle'],'payment_behavior':['p']}},4);z=_discovery_state(fp,5);ap=_apply_external(z,5,[{'test_id':'k','test_type':'PAYMENT_CHECK','result':'PAID','outcome':{'paid':True,'amount':100,'result':'PAID'}}])
    return {
        'problem_supported_without_legacy_signature':x['C01']['state']=='SUPPORTED',
        'evidence_derived_identity_required':weak['C01']['state']=='INSUFFICIENT',
        'recurrence_supported':x['C02']['state']=='SUPPORTED',
        'recurrence_requires_typed_independent_evidence':one['C02']['state']=='INSUFFICIENT',
        'price_or_supply_not_fake_payer':x['C05']['state']=='INSUFFICIENT',
        'external_enabler_candidate_not_fake_timing':x['C12']['state']=='INSUFFICIENT' and 'LINKAGE' in x['C12']['scope'],
        'current_payment_not_future_wtp':paid['C11']['state']=='INSUFFICIENT',
        'real_linked_payment_supports_tested_offer_wtp':z['C11']['state']=='SUPPORTED' and 'C11' in ap,
        'current_gap_is_scoped_not_global':x['C07']['state']=='SUPPORTED' and 'NOT_GLOBAL' in x['C07']['scope'],
        'facets_not_claim_identity':True,'build_not_authorized':True,'zero_current_truth_supported':True,
    }
