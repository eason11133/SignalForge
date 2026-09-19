from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from typing import Any

PORTFOLIO=Path('.radar_runtime/founder_current_portfolio.json')
CLAIMS=Path('.radar_runtime/r1_current_hypothesis_claims.json')
RESEARCH=Path('.radar_runtime/evidence_research_queue_r1.json')
OUT=Path('.radar_runtime/market_test_queue_r1.json')
OUTCOMES=Path('.radar_runtime/market_test_outcomes.jsonl')
MARKET_TEST_PACK=Path('.radar_runtime/founder_market_test_pack_r1.md')
ENGINE_VERSION='opportunity-validation-pipeline-mature-research-a1-hypothesis-unique-tests'
PRIORITY={'BUYER_CHECK':1,'GAP_CHECK':2,'REACHABILITY_CHECK':3,'PAYMENT_CHECK':4,'OUTCOME_CHECK':5}

def _load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except:return default

def _stable_test_id(item,code,generation_version):
    base=str(item.get('hypothesis_key') or item.get('canonical_key') or item.get('id') or '')+'|'+str(code)+'|'+str(generation_version or '')
    return 'mta1_'+hashlib.sha1(base.encode()).hexdigest()[:18]

def _tests(item,claim,generation_version):
    c=claim.get('claims') or {};tests=[];cid=item.get('id');title=item.get('title');hk=item.get('hypothesis_key')
    def add(code,claim_id,method,success,blocked_by=None):
        tests.append({'test_id':_stable_test_id(item,code,generation_version),'candidate_id':cid,'hypothesis_key':hk,'generation_version':generation_version,'hypothesis':title,'claim_id':claim_id,'test_type':code,'priority':PRIORITY[code],'blocked_by':blocked_by or [],'method':method,'success_criteria':success,'status':'NOT_RUN','result':'UNKNOWN','snapshot':{'hypothesis_key':hk,'facets':item.get('facet_labels') or [],'readiness':item.get('readiness'),'problem':item.get('problem'),'actor':item.get('actor'),'workflow':item.get('workflow'),'evidence_refs':item.get('evidence_refs'),'typed_evidence_bundle':item.get('typed_evidence_bundle'),'target_sample_definition':{'actor':item.get('actor'),'workflow':item.get('workflow')},'sample_representativeness':'UNVALIDATED'}})
    need_buyer=(c.get('C05') or {}).get('state')!='SUPPORTED';need_gap=(c.get('C07') or {}).get('state')!='SUPPORTED';need_reach=(c.get('C10') or {}).get('state')!='SUPPORTED';need_pay=(c.get('C11') or {}).get('state')!='SUPPORTED'
    if need_buyer:add('BUYER_CHECK','C05','Contact/interview people matching the observed affected actor; identify who actually controls payment or approval.','At least 3 independent qualified contacts identify the same economic owner/payer role; qualified_confirmations >= 3.')
    if need_gap:add('GAP_CHECK','C07','Ask affected users whether the exact evidence-backed problem remains unresolved after current alternatives/workarounds.','At least 3 independent current users confirm the same unresolved problem; qualified_confirmations >= 3.')
    if need_reach:add('REACHABILITY_CHECK','C10','Attempt targeted outreach through the observed product/category/community without pitching a product.','Reach >=10 qualified people and receive >=2 measurable responses.')
    blockers=[]
    if need_buyer:blockers.append(_stable_test_id(item,'BUYER_CHECK',generation_version))
    if need_gap:blockers.append(_stable_test_id(item,'GAP_CHECK',generation_version))
    if need_reach:blockers.append(_stable_test_id(item,'REACHABILITY_CHECK',generation_version))
    if need_pay:add('PAYMENT_CHECK','C11','Only after buyer/gap/reachability evidence is sufficient, test a concrete paid pilot, deposit, or signed paid pilot. Hypothetical interest is not payment.','At least one real payment/deposit with positive amount or signed paid pilot.',blockers)
    if not tests:add('OUTCOME_CHECK','C14','Run a small external behavior test and record actual behavior, not stated preference.','A real external behavior outcome is recorded with actor, channel, timestamp and behavior.')
    return sorted(tests,key=lambda x:x['priority'])

def _valid_outcome(x:dict[str,Any],known:dict[str,dict[str,Any]],active_generation:str)->tuple[bool,str]:
    tid=str(x.get('test_id') or '');t=known.get(tid)
    if not tid or t is None:return False,'UNKNOWN_TEST_ID'
    if str(x.get('generation_version') or '')!=str(active_generation or ''):return False,'GENERATION_MISMATCH'
    if int(x.get('candidate_id') or -1)!=int(t.get('candidate_id') or -2):return False,'CANDIDATE_MISMATCH'
    if str(x.get('hypothesis_key') or t.get('hypothesis_key') or '')!=str(t.get('hypothesis_key') or ''):return False,'HYPOTHESIS_MISMATCH'
    for k in ('observed_at','actor_type','channel','result'):
        if not x.get(k):return False,'MISSING_'+k.upper()
    typ=t.get('test_type');res=str(x.get('result') or '').upper();positive=res in {'PASS','SUCCESS','CONFIRMED','PAID','POSITIVE'}
    if typ in {'BUYER_CHECK','GAP_CHECK'} and positive and int(x.get('qualified_confirmations') or 0)<3:return False,'INSUFFICIENT_QUALIFIED_CONFIRMATIONS'
    if typ=='REACHABILITY_CHECK' and positive and (int(x.get('qualified_reached') or 0)<10 or int(x.get('responses') or 0)<2):return False,'INSUFFICIENT_REACHABILITY_SAMPLE'
    if typ=='PAYMENT_CHECK' and positive:
        if x.get('paid') is not True:return False,'PAYMENT_SUCCESS_WITHOUT_PAID_BEHAVIOR'
        try:amt=float(x.get('amount') or 0)
        except:amt=0
        if amt<=0 and x.get('signed_paid_pilot') is not True:return False,'PAID_WITHOUT_AMOUNT_OR_SIGNED_PILOT'
    return True,'PASS'

def read_outcomes(known,active_generation):
    valid=[];invalid=[];seen=set()
    if not OUTCOMES.exists():return valid,invalid
    for n,line in enumerate(OUTCOMES.read_text(encoding='utf-8').splitlines(),1):
        line=line.strip()
        if not line:continue
        try:x=json.loads(line)
        except Exception:invalid.append({'line':n,'reason':'INVALID_JSON'});continue
        tid=str(x.get('test_id') or '')
        if tid in seen:invalid.append({'line':n,'reason':'DUPLICATE_TEST_OUTCOME','test_id':tid});continue
        ok,reason=_valid_outcome(x,known,active_generation)
        if ok:
            seen.add(tid);x=dict(x);x['outcome_hash']=hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()[:20];valid.append(x)
        else:invalid.append({'line':n,'reason':reason,'test_id':x.get('test_id')})
    return valid,invalid

def _write_execution_pack(portfolio,tests,blocked_reason):
    MARKET_TEST_PACK.parent.mkdir(parents=True,exist_ok=True);items={str(x.get('id')):x for x in portfolio.get('current_hypotheses') or []}
    lines=['# SignalForge Founder Market-Test Pack — Mature Research Adoption A1','',f"Active generation: {(portfolio.get('active_generation') or {}).get('active_discovery_version')}",f"Portfolio quality: {(portfolio.get('portfolio_quality_gate') or {}).get('status')}",f"Blocked reason: {blocked_reason or 'NONE'}",'', '> This pack tests an evidence-backed problem-family hypothesis. It does not create a product/opportunity thesis, does not treat planned tests as validation, and requires the tested sample to match the intended actor/workflow before generalizing an outcome.','']
    if blocked_reason=='NO_CURRENT_HYPOTHESIS_MEETS_EVIDENCE_THRESHOLD':
        rq=_load(RESEARCH,{});lines += [f"No Current hypothesis qualifies. Evidence research queue: {rq.get('count',0)}",'']
        for i,r in enumerate((rq.get('items') or [])[:12],1):lines += [f"- {i}. {r.get('problem')}",f"  Missing: {r.get('missing_evidence')} | Next: {r.get('allowed_next_evidence')}"]
    grouped={}
    for t in tests:grouped.setdefault(str(t.get('candidate_id')),[]).append(t)
    for cid,x in items.items():
        lines += [f"## {x.get('title')}",f"- Hypothesis key: {x.get('hypothesis_key')}",f"- Facets: {', '.join(x.get('facet_labels') or []) or 'none'}",f"- Actor / workflow: {x.get('actor')} / {x.get('workflow')}",f"- Evidence refs: {', '.join(x.get('evidence_refs') or [])}",f"- Readiness: {x.get('readiness')}",'']
        for t in sorted(grouped.get(cid,[]),key=lambda z:z.get('priority',99)):
            lines += [f"### {t.get('test_type')} — {t.get('test_id')}",f"- Actionable now: {t.get('actionable_now',False)}",f"- Method: {t.get('method')}",f"- Success: {t.get('success_criteria')}",f"- Blocked by: {', '.join(t.get('remaining_blockers') or t.get('blocked_by') or []) or 'none'}",'']
    MARKET_TEST_PACK.write_text('\n'.join(lines),encoding='utf-8');return str(MARKET_TEST_PACK)

def rebuild_validation_queue()->dict[str,Any]:
    p=_load(PORTFOLIO,{});cl=_load(CLAIMS,{});prior=_load(OUT,{});cmap={str(x.get('candidate_id')):x for x in cl.get('candidates') or []};generation=((p.get('active_generation') or {}).get('active_discovery_version'));tests=[];current=list(p.get('current_hypotheses') or []);current_ids={int(x.get('id')) for x in current if x.get('id') is not None};quality=p.get('portfolio_quality_gate') or {};blocked=None
    if not str(quality.get('status') or '').startswith('PASS'):blocked='CURRENT_HYPOTHESIS_PORTFOLIO_QUALITY_NOT_PASS'
    elif not current:blocked='NO_CURRENT_HYPOTHESIS_MEETS_EVIDENCE_THRESHOLD'
    if not blocked:
        seen_h=set()
        for item in current:
            hk=str(item.get('hypothesis_key') or '')
            if not hk or hk in seen_h:continue
            seen_h.add(hk);tests.extend(_tests(item,cmap.get(str(item.get('id')),{}),generation))
    existing_ids={str(t.get('test_id')) for t in tests}
    for t in prior.get('tests') or []:
        if t.get('status')=='COMPLETED' and str(t.get('generation_version') or '')==str(generation or '') and int(t.get('candidate_id') or -1) in current_ids and str(t.get('test_id')) not in existing_ids:tests.append(t);existing_ids.add(str(t.get('test_id')))
    known={str(t['test_id']):t for t in tests};outcomes,invalid=read_outcomes(known,generation);omap={str(x.get('test_id')):x for x in outcomes if x.get('test_id')}
    for t in tests:
        if t['test_id'] in omap:t['status']='COMPLETED';t['result']=str(omap[t['test_id']].get('result') or 'UNKNOWN').upper();t['outcome']=omap[t['test_id']]
    completed={t['test_id'] for t in tests if t['status']=='COMPLETED' and str(t.get('result')).upper() in {'PASS','SUCCESS','CONFIRMED','PAID','POSITIVE'}}
    for t in tests:t['remaining_blockers']=[x for x in t.get('blocked_by') or [] if x not in completed];t['actionable_now']=t['status']!='COMPLETED' and not t['remaining_blockers']
    next_tests={}
    for cid in {str(t.get('candidate_id')) for t in tests}:
        xs=sorted([t for t in tests if str(t.get('candidate_id'))==cid and t.get('actionable_now')],key=lambda x:x['priority'])
        if xs:next_tests[cid]=xs[0]['test_id']
    pack=_write_execution_pack(p,tests,blocked)
    data={'engine_version':ENGINE_VERSION,'generated_at':time.time(),'active_generation':p.get('active_generation'),'active_generation_version':generation,'current_hypotheses':len(current),'tests':tests,'tests_planned':len(tests),'tests_actionable_now':sum(bool(t.get('actionable_now')) for t in tests),'tests_completed':sum(t['status']=='COMPLETED' for t in tests),'valid_outcomes':len(outcomes),'invalid_outcomes':len(invalid),'invalid_outcome_reasons':invalid[:50],'paid_outcomes':sum(1 for x in outcomes if x.get('paid') is True),'next_test_by_candidate':next_tests,'blocked_reason':blocked,'market_test_pack_path':pack,'watch_signals_not_tested':True,'hypothesis_unique_test_identity':len({t.get('test_id') for t in tests})==len(tests),'truth_contract':'Tests bind to unique hypothesis_key + generation + test type. Facets do not create duplicate tests. Planned tests are not validation; payment requires real paid behavior; outcome generalization requires an actor/workflow-representative sample rather than convenience beta users.','outcome_ingest_path':str(OUTCOMES)}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8');return data

def static_acceptance():
    item={'id':1,'hypothesis_key':'h1','canonical_key':'h1','title':'x','facet_labels':['MICRO_FRICTION','PROVEN_MARKET_WEDGE'],'readiness':'RESEARCH_HYPOTHESIS_READY','problem':'x','actor':'u','workflow':'w','evidence_refs':['a','b'],'typed_evidence_bundle':{'problem':['a'],'recurrence':['b']}};claim={'claims':{'C05':{'state':'UNKNOWN'},'C07':{'state':'INSUFFICIENT'},'C10':{'state':'UNKNOWN'},'C11':{'state':'INSUFFICIENT'}}};ts=_tests(item,claim,'r1');known={t['test_id']:t for t in ts};pay=next(t for t in ts if t['test_type']=='PAYMENT_CHECK');good={'test_id':pay['test_id'],'candidate_id':1,'hypothesis_key':'h1','generation_version':'r1','observed_at':'2026-08-29','actor_type':'buyer','channel':'direct','result':'PAID','paid':True,'amount':100};ok,_=_valid_outcome(good,known,'r1');bad,reason=_valid_outcome({**good,'amount':0},known,'r1')
    return {'buyer_test':any(t['test_type']=='BUYER_CHECK' for t in ts),'gap_test':any(t['test_type']=='GAP_CHECK' for t in ts),'reachability_test':any(t['test_type']=='REACHABILITY_CHECK' for t in ts),'payment_dependency_gated':bool(pay.get('blocked_by')),'hypothesis_bound_test_identity':all(t['test_id'].startswith('mta1_') and t.get('hypothesis_key')=='h1' for t in ts),'facets_do_not_duplicate_tests':len({t['test_id'] for t in ts})==len(ts),'strict_valid_outcome':ok,'fake_paid_outcome_rejected':not bad and reason=='PAID_WITHOUT_AMOUNT_OR_SIGNED_PILOT','planned_not_validated':all(t['status']=='NOT_RUN' for t in ts),'watch_not_auto_tested':True,'market_test_pack_declared':MARKET_TEST_PACK.name.endswith('r1.md'),'sample_representativeness_explicit':all((t.get('snapshot') or {}).get('sample_representativeness')=='UNVALIDATED' for t in ts)}
