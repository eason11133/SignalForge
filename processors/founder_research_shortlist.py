"""Founder-usable SignalForge research shortlist (U9).

Truth/quality policy:
- evidence recurrence must already be dependence-aware upstream;
- Founder cards require intelligible workflow/need structure, not merely parser validity;
- user-built self-solutions are separate lead-user/Need-Solution signals;
- employer/supplier/policy/positive capability context never masquerades as user demand;
- market/enabler context is linked only on strong entity/structural evidence;
- this module performs discussion-readiness triage, never venture attractiveness scoring.
"""
from __future__ import annotations

import html,json,re
from pathlib import Path
from typing import Any

ENGINE_VERSION="founder-research-shortlist-u10-continuous-evidence-plan"
JSON_PATH=Path('.radar_runtime/founder_research_shortlist_u10.json')
MD_PATH=Path('.radar_runtime/founder_research_shortlist_u10.md')

NEED_ROLES={"PROBLEM_REPORT","FEATURE_REQUEST","WORKAROUND_OR_USAGE"}
META_NOISE=(
    'repo_full_name:','so_question_id:','activity comparison | tool','machine learning crash course',
    'title: title:','release status | notable','github activity','pk:','document_id:','source: indeed | title:',
)
GENERIC={
    'problem','issue','error','failed','failure','work','works','working','system','tool','app','user','users','data','model','ai',
    'need','needs','using','use','used','make','made','thing','things','current','new','get','got','time','process','support',
    'manual','other','unknown','productivity','intake'
}
TECH_NARROW_PATTERNS=(
    r'\bimporterror\b',r'\bno module named\b',r'\btraceback\b',r'\bdenominator\b',r'\bcookie jar\b',
    r'\bmemory allocation\b',r'\btls/npm\b',r'\bcompile error\b',r'\bsegfault\b',r'\bstack trace\b',r'\bvram\b',r'\bllama\.cpp\b',r'\bstrix halo\b',r'\bgfx\d+\b',r'\bqwen[- .]?[0-9]\b',r'\bgemma\s+[0-9]\b',r'\bdeepseek[- .]?[a-z0-9]+'
)
FIRST_PERSON=re.compile(r"\b(i|i'm|i’ve|i've|my|me|we|our|us)\b",re.I)
BURDEN_LANGUAGE=re.compile(r"\b(hate|tedious|every time|manually|by hand|kept|again and again|slow|waste|hours?|expensive|cost|can't|cannot|broken|stuck|frustrat|annoy|pain)\b",re.I)
BUILD_LANGUAGE=re.compile(r"\b(built|made|created|developed|wrote|hacked together|made myself)\b",re.I)

MAKER_PROMO_LANGUAGE=re.compile(r"\b(?:i['’]?ve been building|i['’]?m building|i am building|my (?:tool|app|product)|our (?:tool|app|product)|\$\s*\d+(?:\.\d+)?\s*(?:/|per)\s*(?:month|mo)|supports? (?:gpt|claude|gemini)|book a demo|sign up)\b",re.I)
OWN_NEED_LANGUAGE=re.compile(r"\b(because i|because we|i hate|we hate|i needed|we needed|every time i|for my|for our|my workflow|our workflow)\b",re.I)
SHOWCASE_LANGUAGE=re.compile(r"\b(?:show\s+hn:|hey\s+hn!?|i\s+built\s+this\s+solo|check\s+it\s+out\s+here|product\s+hunt|demo\s+here)\b",re.I)
DISCUSSION_LANGUAGE=re.compile(r"\b(?:i\s+guess\s+i\s+agree|don(?:'|’)?t\s+really\s+see\s+the\s+connection|not\s+seeing\s+your\s+(?:argument|point)|are\s+you\s+saying)\b",re.I)

def _clean(v:Any)->str:
    s=html.unescape(str(v or ''))
    s=re.sub(r'<[^>]+>',' ',s)
    return re.sub(r'\s+',' ',s).strip()

def _lead_noise(text:Any)->bool:
    s=_clean(text).lower()
    return (not s) or any(x in s for x in META_NOISE)

def _meaningful(v:Any)->bool:
    return _clean(v).lower() not in {'','other','unknown','none','community_user'}

def _frame_tokens(f:dict[str,Any]|None)->set[str]:
    f=f or {};out=set()
    for k in ('actions','failure_modes','objects'):
        for x in f.get(k) or []:
            for t in re.findall(r"[a-z0-9][a-z0-9_-]{2,}",_clean(x).lower()):
                if t not in GENERIC:out.add(t)
    target=_clean(f.get('primary_specific_target')).lower()
    if target and target not in GENERIC:out.add('target:'+target)
    wf=_clean(f.get('workflow')).lower()
    if wf not in {'','other','unknown','productivity','intake'}:out.add('wf:'+wf)
    return out

def _specific_target(f:dict[str,Any]|None)->str:
    return _clean((f or {}).get('primary_specific_target')).lower()

def _technical_narrow(text:str)->bool:
    s=_clean(text).lower()
    return any(re.search(p,s,re.I) for p in TECH_NARROW_PATTERNS)

def _discussion_readiness(problem:Any, actor:Any, workflow:Any, need_frame:dict[str,Any]|None, signals:dict[str,Any]|None=None, *, product:Any=None, evidence_count:int=1)->tuple[bool,float,list[str]]:
    text=_clean(problem);f=need_frame or {};sig=signals or {};score=0.0;reasons=[]
    if _lead_noise(text):return False,-10.0,['META_OR_SOURCE_NOISE']
    if len(text)<28:return False,-5.0,['TOO_SHORT_OR_CONTEXTLESS']
    if _meaningful(actor):score+=1.0;reasons.append('ACTOR_KNOWN')
    if _meaningful(workflow) and _clean(workflow).lower() not in {'productivity','intake'}:score+=1.2;reasons.append('WORKFLOW_KNOWN')
    if product:score+=0.6;reasons.append('PRODUCT_CONTEXT')
    if FIRST_PERSON.search(text):score+=1.0;reasons.append('FIRST_PERSON')
    if BURDEN_LANGUAGE.search(text):score+=1.1;reasons.append('BURDEN_LANGUAGE')
    if sig.get('manual_work'):score+=0.7;reasons.append('MANUAL_WORK')
    if sig.get('frequency'):score+=0.7;reasons.append('FREQUENCY')
    if sig.get('economic_burden'):score+=1.0;reasons.append('ECONOMIC_BURDEN')
    if f.get('workaround'):score+=0.7;reasons.append('WORKAROUND')
    if f.get('consequence'):score+=0.5;reasons.append('CONSEQUENCE')
    if f.get('actions'):score+=0.35
    if f.get('failure_modes'):score+=0.45
    if evidence_count>=2:score+=0.55;reasons.append('INDEPENDENT_RECURRENCE')
    if _technical_narrow(text) and not (_meaningful(actor) or (_meaningful(workflow) and _clean(workflow).lower() not in {'other','productivity','intake'}) or sig.get('frequency') or sig.get('economic_burden')):
        score-=2.2;reasons.append('NARROW_TECH_WITHOUT_BROAD_WORKFLOW')
    # Discussion surface requires enough context to be worth the Founder's attention,
    # not merely a syntactically valid complaint.
    return score>=2.15,round(score,3),reasons

def _hypothesis_role_check(h:dict[str,Any])->tuple[bool,str]:
    roles=[]
    if h.get('feedback_role'):roles.append(str(h.get('feedback_role')))
    for e in h.get('evidence_preview') or []:
        if e.get('feedback_role'):roles.append(str(e.get('feedback_role')))
    if not roles:return False,'FEEDBACK_ROLE_MISSING'
    if any(r not in NEED_ROLES for r in roles):return False,'NON_NEED_EVIDENCE_ROLE'
    if int(h.get('independent_problem_evidence_count') or 0)<2:return False,'INSUFFICIENT_INDEPENDENT_EVIDENCE'
    # Source origin is stricter than source-family diversity. A copied cross-post must
    # not become a founder-facing recurrence merely because it appears on two sites.
    origins=int(h.get('independent_source_origins') or (h.get('signals') or {}).get('independent_source_origins') or 0)
    if origins and origins<2:return False,'INSUFFICIENT_INDEPENDENT_SOURCE_ORIGINS'
    return True,'PASS'

def _hypothesis_priority(h:dict[str,Any], readiness:float)->float:
    sig=h.get('signals') or {}
    return round(readiness + min(1.0,.35*max(0,int(h.get('independent_problem_evidence_count') or 0)-1)) + (.45 if sig.get('economic_burden') else 0) + (.25 if sig.get('frequency') else 0),3)

def _lead_role_check(x:dict[str,Any])->tuple[bool,str]:
    role=str(x.get('feedback_role') or ((x.get('problem_obs') or {}).get('feedback_role')) or '')
    if role not in NEED_ROLES:return False,'NON_NEED_OR_UNKNOWN_ROLE:'+str(role or 'MISSING')
    if _lead_noise(x.get('problem')):return False,'META_NOISE'
    return True,'PASS'

def _need_solution_context(need_frame:dict[str,Any]|None,user_innovations:list[dict[str,Any]],limit:int=3)->list[dict[str,Any]]:
    nt=_frame_tokens(need_frame)
    if not nt:return []
    out=[]
    for u in user_innovations:
        ut=_frame_tokens(u.get('need_frame') or {})
        inter={x for x in nt&ut if not x.startswith('wf:')}
        samewf=bool({x for x in nt&ut if x.startswith('wf:')})
        if len(inter)>=2 or (len(inter)>=1 and samewf):
            score=len(inter)+(.7 if samewf else 0)
            out.append({'signal_id':u.get('object_id'),'score':round(score,3),'text':_clean(u.get('text'))[:420],'truth_label':'RELATED_USER_INNOVATION_CONTEXT_NOT_DEMAND'})
    return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]

def _independent_need_matches(ui:dict[str,Any], needs:list[dict[str,Any]], limit:int=3)->list[dict[str,Any]]:
    """Conservative structural recurrence candidates for an observed Need-Solution pair.

    This adapts need-solution web-search logic without pretending automatic equivalence is
    solved. Candidates require an independent evidence ref plus a meaningful workflow match
    and at least two non-generic frame terms, or three structural terms without workflow.
    """
    uf=ui.get('need_frame') or {};ut=_frame_tokens(uf);uw=_clean(ui.get('workflow') or uf.get('workflow')).lower();uref=_clean(ui.get('evidence_ref'))
    out=[]
    for n in needs:
        if _clean(n.get('evidence_ref'))==uref:continue
        nf=n.get('need_frame') or {};nt=_frame_tokens(nf);nw=_clean(n.get('workflow') or nf.get('workflow')).lower()
        inter={x for x in ut&nt if not x.startswith('wf:')}
        samewf=bool(uw and nw and uw not in {'other','unknown','productivity','intake'} and uw==nw)
        if not ((samewf and len(inter)>=2) or len(inter)>=3):continue
        score=len(inter)+(1.0 if samewf else 0)
        out.append({'score':round(score,3),'evidence_ref':n.get('evidence_ref'),'problem':_clean(n.get('problem'))[:420],'workflow':n.get('workflow'),'truth_label':'STRUCTURAL_RECURRENCE_CANDIDATE_NEEDS_SEMANTIC_CONFIRMATION'})
    return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]

def _diffusion_gap_assessment(ui:dict[str,Any], roi:dict[str,Any])->dict[str,Any]:
    rec=_independent_need_matches(ui,roi.get('need_fragments') or [])
    ctx=_linked_context({'need_frame':ui.get('need_frame') or {},'product_id':ui.get('product_id'),'workflow':ui.get('workflow')},roi)
    market=ctx.get('market_state_candidates') or []
    if rec and not market:
        status='DIFFUSION_OR_COMMERCIALIZATION_GAP_RESEARCH_CANDIDATE'
    elif rec and market:
        status='NEED_RECURS_AND_SUPPLY_EXISTS_DIFFERENTIATION_UNRESOLVED'
    elif market:
        status='SELF_SOLUTION_WITH_EXISTING_SUPPLY_RECURRENCE_UNPROVEN'
    else:
        status='SELF_SOLUTION_ONLY_RECURRENCE_AND_DIFFUSION_UNPROVEN'
    return {'status':status,'independent_recurrence_candidates':rec,'market_context_count':len(market),'peer_adoption_status':'UNKNOWN_NOT_YET_EVIDENCED','commercialization_gap_proven':False,'truth_boundary':'A diffusion/commercialization gap is only a research candidate until independent need recurrence and weak/failed diffusion are separately evidenced.'}

def _evidence_query_terms(card:dict[str,Any], *, supply:bool=False)->str:
    """Generate search terms only from observed evidence. Never invent a product or fact."""
    nf=card.get('need_frame') or {};parts=[]
    wf=_clean(card.get('workflow') or nf.get('workflow')).lower().replace('_',' ')
    if wf not in {'','unknown','other','productivity','intake'}:parts += wf.split()
    fields=('actions','objects') if supply else ('failure_modes','actions','objects')
    for field in fields:
        vals=nf.get(field) or []
        if not isinstance(vals,list):vals=[vals]
        for v in vals:
            for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",_clean(v).replace('_',' ')):
                tl=t.lower()
                if tl in {'because','every','thing','things','tool','tools','some','have','with','from','into','using','used','other'}:continue
                if supply and tl in {'hate','tedious','pain','privacy','constraint','broken','error','manual','reentry'}:continue
                if tl not in parts:parts.append(tl)
            if len(parts)>=7:break
        if len(parts)>=7:break
    return ' '.join(parts[:7])

def _best_next_evidence_plan(card:dict[str,Any])->dict[str,Any]:
    typ=_clean(card.get('card_type'));unknown=set(card.get('unknowns') or []);market=card.get('market_context') or []
    need_q=_evidence_query_terms(card,supply=False);supply_q=_evidence_query_terms(card,supply=True)
    steps=[]
    if typ=='USER_INNOVATION_NEED_SOLUTION_SIGNAL':
        gap=card.get('diffusion_gap_assessment') or {}
        if not (gap.get('independent_recurrence_candidates') or []):steps.append({'priority':1,'evidence':'INDEPENDENT_NEED_RECURRENCE','why':'A self-solution is not market demand by itself.','query':need_q})
        if not market:steps.append({'priority':2,'evidence':'CURRENT_SOLUTION_SUPPLY','why':'Separate an unmet need from an already-served workflow.','query':supply_q,'preferred_surfaces':['github_repositories','app_supply','web_software_supply']})
        steps.append({'priority':3,'evidence':'PEER_ADOPTION_OR_DIFFUSION','why':'User-innovation diffusion matters only after the observed solution and need are linked.','query':supply_q,'preferred_signals':['forks','stars','mentions','requests','adoption_comments']})
        steps.append({'priority':4,'evidence':'PAYMENT_BEHAVIOR','why':'WTP should be tested only after recurrence/supply context improves.','query':None})
    elif typ=='EVIDENCE_BACKED_PROBLEM_HYPOTHESIS':
        if not market:steps.append({'priority':1,'evidence':'CURRENT_SOLUTION_SUPPLY','why':'Map current alternatives before discussing a wedge.','query':supply_q})
        steps.append({'priority':2,'evidence':'ECONOMIC_BURDEN_OR_BUYER','why':'Problem recurrence alone does not establish commercial importance.','query':need_q})
    else:
        steps.append({'priority':1,'evidence':'INDEPENDENT_NEED_RECURRENCE','why':'A single-source lead needs independent corroboration before promotion.','query':need_q})
    return {'state':'ACTIVE_EVIDENCE_GAP_RESEARCH','need_query':need_q or None,'supply_query':supply_q or None,'next_steps':steps,'stop_rule':'Do not propose/build a product from this card until the Founder explicitly asks; evidence acquisition comes first.'}


def _strong_context_matches(h:dict[str,Any],items:list[dict[str,Any]],kind:str,limit:int=3)->list[dict[str,Any]]:
    nf=h.get('need_frame') or {};nt=_frame_tokens(nf);target=_specific_target(nf);pid=_clean(h.get('product_id'))
    out=[]
    for item in items:
        text=_clean(item.get('span') or item.get('text') or item.get('product_name')).lower()
        ipid=_clean(item.get('product_id'))
        exact_product=bool(pid and ipid and pid==ipid)
        target_match=bool(target and target in text)
        it=_frame_tokens(item.get('need_frame') or {})
        structural={x for x in nt&it if not x.startswith('wf:')}
        lexical={t for t in nt if not t.startswith(('wf:','target:')) and t in text and len(t)>=5}
        # Never nominate why-now/supply from a generic workflow match. Require entity/product
        # identity or multiple specific need terms. This blocks U4's Cypress/TrueForge noise.
        min_lexical = 2 if kind=='market' else 3
        if not (exact_product or (target_match and len(lexical)>=1) or len(structural)>=2 or len(lexical)>=min_lexical):
            continue
        score=(3.0 if exact_product else 0)+(2.0 if target_match else 0)+.8*len(structural)+.45*len(lexical)
        if kind=='market':
            out.append({'score':round(score,3),'product':item.get('product_name'),'paid_supply':item.get('paid_supply'),'evidence_ref':item.get('evidence_ref'),'truth_label':'STRONGLY_RELATED_SUPPLY_CONTEXT_NOT_WTP'})
        elif kind=='solution':
            out.append({'score':round(score,3),'text':_clean(item.get('text'))[:360],'evidence_ref':item.get('evidence_ref'),'truth_label':'STRONGLY_RELATED_SOLUTION_CONTEXT_NOT_DEMAND'})
        else:
            out.append({'score':round(score,3),'type':item.get('enabler_type'),'span':_clean(item.get('span'))[:360],'evidence_ref':item.get('evidence_ref'),'truth_label':'WHY_NOW_CANDIDATE_STRONG_RELATION_NOT_CAUSALLY_PROVEN'})
    return sorted(out,key=lambda x:x['score'],reverse=True)[:limit]

def _linked_context(h:dict[str,Any],roi:dict[str,Any])->dict[str,Any]:
    return {
        'market_state_candidates':_strong_context_matches(h,roi.get('market_states') or [],'market'),
        'solution_context_candidates':_strong_context_matches(h,roi.get('solution_supply_signals') or [],'solution'),
        'external_enabler_candidates':_strong_context_matches(h,roi.get('external_enablers') or [],'enabler'),
    }

def _user_innovation_ready(x:dict[str,Any])->tuple[bool,float,list[str]]:
    fam=_clean(x.get('source_family')).lower();role=_clean(x.get('source_role')).upper();text=_clean(x.get('text'));intent=_clean(x.get('source_intent')).upper()
    if role!='FIRSTHAND_USER_PAIN' or fam not in {'reddit','reddit_rss','community_raw','hackernews','stackexchange','app_store_reviews'}:
        return False,-10,['NOT_FIRSTHAND_USER_INNOVATION_SOURCE']
    if intent!='SELF_SOLUTION_FOR_OWN_NEED':
        return False,-8,['SOURCE_INTENT_NOT_SELF_SOLUTION_FOR_OWN_NEED:'+str(intent or 'MISSING')]
    if MAKER_PROMO_LANGUAGE.search(text) or SHOWCASE_LANGUAGE.search(text):
        return False,-5,['FOUNDER_PROMO_OR_PROJECT_SHOWCASE']
    if DISCUSSION_LANGUAGE.search(text):
        return False,-4,['DISCUSSION_OPINION_NOT_USER_INNOVATION']
    self_solution=bool(BUILD_LANGUAGE.search(text) or re.search(r'\b(?:fine[- ]?tuned|configured|optimized|patched|hacked together|set up|decided to build)\b',text,re.I))
    if not (self_solution and OWN_NEED_LANGUAGE.search(text)):
        return False,-2,['MISSING_CAUSAL_SELF_SOLUTION_PLUS_OWN_NEED']
    ok,score,reasons=_discussion_readiness(text,x.get('actor'),x.get('workflow'),x.get('need_frame') or {},{},evidence_count=1)
    if _technical_narrow(text) and not (_meaningful(x.get('actor')) or (_meaningful(x.get('workflow')) and _clean(x.get('workflow')).lower() not in {'other','productivity','intake'})):
        score-=1.8;reasons.append('NARROW_TECH_USER_INNOVATION')
        ok=score>=2.15
    return ok,round(score+1.2,3),reasons+['OBSERVED_CAUSAL_NEED_SOLUTION_PAIR']

def _discussion_cards(hyps,ui,leads,roi,limit=8):
    cards=[]
    for h in hyps:
        ctx=_linked_context(h,roi)
        cards.append({'discussion_id':h.get('hypothesis_key'),'card_type':'EVIDENCE_BACKED_PROBLEM_HYPOTHESIS','priority':float(h.get('review_priority') or 0)+2,
            'problem':h.get('problem'),'actor':h.get('actor'),'workflow':h.get('workflow'),'need_frame':h.get('need_frame') or {},'discussion_readiness':h.get('discussion_readiness'),
            'evidence_preview':h.get('evidence_preview') or [],'independent_evidence':h.get('independent_problem_evidence_count'),'independent_source_origins':h.get('independent_source_origins'),'dependency_rejected_count':h.get('dependency_rejected_count'),
            'market_context':ctx['market_state_candidates'],'solution_context':ctx['solution_context_candidates'],'why_now_context':ctx['external_enabler_candidates'],'user_innovation_context':h.get('related_user_innovation_context') or [],
            'unknowns':h.get('unknowns') or [],'discussion_prompt':'Discuss whether this evidenced problem is economically meaningful, who the buyer is, current workaround/solutions, and the cheapest next evidence. Do not invent a product unless the Founder asks.',
            'truth_boundary':'Independent problem recurrence is evidence-backed. Market attractiveness, WTP, causal why-now, and founder captureability remain unvalidated unless separately evidenced.'})
    for x in ui:
        pseudo={'need_frame':x.get('need_frame') or {},'product_id':x.get('product_id'),'workflow':x.get('workflow')}
        ctx=_linked_context(pseudo,roi)
        cards.append({'discussion_id':x.get('signal_id'),'card_type':'USER_INNOVATION_NEED_SOLUTION_SIGNAL','priority':float(x.get('review_priority') or 0)+.8,'problem':x.get('text'),'actor':x.get('actor'),'workflow':x.get('workflow'),'need_frame':x.get('need_frame') or {},'discussion_readiness':x.get('discussion_readiness'),
            'evidence_preview':[{'ref':x.get('evidence_ref'),'text':x.get('text'),'feedback_role':'USER_INNOVATION_NEED_SOLUTION'}],
            'market_context':ctx['market_state_candidates'],'solution_context':ctx['solution_context_candidates'],'why_now_context':ctx['external_enabler_candidates'],'diffusion_gap_assessment':x.get('diffusion_gap_assessment') or {},
            'unknowns':['INDEPENDENT_MARKET_RECURRENCE_NOT_YET_EVIDENCED','PEER_ADOPTION_OR_DIFFUSION_NOT_YET_EVIDENCED','WTP_NOT_YET_EVIDENCED'],'discussion_prompt':'Discuss the observed Need-Solution pair, whether the need recurs independently, whether peers adopted or ignored the solution, what supply exists, and whether a diffusion/commercialization gap is actually present.','truth_boundary':'Observed causal self-solution only. Independent recurrence, peer adoption/diffusion failure, commercialization gap, WTP, and market validation remain unproven.'})
    for x in leads:
        cards.append({'discussion_id':x.get('research_id'),'card_type':'DIRECT_NEED_LEAD','priority':float(x.get('review_priority') or 0),'problem':x.get('problem'),'actor':x.get('actor'),'workflow':x.get('workflow'),'need_frame':x.get('need_frame') or {},'discussion_readiness':x.get('discussion_readiness'),
            'evidence_preview':[{'ref':str(x.get('source_family'))+':'+str(x.get('source_ref')),'text':x.get('problem'),'feedback_role':x.get('feedback_role')}],'unknowns':x.get('missing_evidence') or ['INDEPENDENT_CORROBORATION'],'discussion_prompt':'Discuss only as a research lead: what independent source would corroborate the same workflow pain?','truth_boundary':'Single-source lead; not a hypothesis or opportunity.'})
    for c in cards:c['best_next_evidence_plan']=_best_next_evidence_plan(c)
    return sorted(cards,key=lambda x:float(x.get('priority') or 0),reverse=True)[:limit]

def build_shortlist(accepted_hypotheses:list[dict[str,Any]],research_items:list[dict[str,Any]],*,research_objects:dict[str,Any]|None=None,relationship_audit=None,lead_audit=None,max_hypotheses=8,max_leads=5,max_user_innovations=4)->dict[str,Any]:
    roi=research_objects or {};hyps=[];filtered=[]
    for h in accepted_hypotheses:
        ok,reason=_hypothesis_role_check(h)
        if not ok:
            filtered.append({'id':h.get('hypothesis_key'),'reason':reason,'problem':_clean(h.get('problem'))[:280]});continue
        ready,rscore,rreasons=_discussion_readiness(h.get('problem'),h.get('actor'),h.get('workflow'),h.get('need_frame') or {},h.get('signals') or {},product=h.get('product'),evidence_count=int(h.get('independent_problem_evidence_count') or 0))
        if not ready:
            filtered.append({'id':h.get('hypothesis_key'),'reason':'FOUNDER_DISCUSSION_NOT_READY','readiness_score':rscore,'readiness_reasons':rreasons,'problem':_clean(h.get('problem'))[:280]});continue
        y=dict(h);y['discussion_readiness']={'score':rscore,'reasons':rreasons};y['review_priority']=_hypothesis_priority(y,rscore);y['founder_status']='EVIDENCE_BACKED_RESEARCH_HYPOTHESIS';hyps.append(y)
    hyps.sort(key=lambda x:x['review_priority'],reverse=True)

    keep_ids=set((lead_audit or {}).get('kept_ids') or []);enrich=(lead_audit or {}).get('enrichment') or {};audit_ran=(lead_audit or {}).get('status')=='PASS'
    leads=[];lead_filtered=[]
    for i,x in enumerate(research_items,1):
        ok,reason=_lead_role_check(x);rid=str(x.get('research_id') or x.get('fragment_cluster_key') or x.get('problem_ref') or i)
        if not ok:lead_filtered.append({'id':rid,'reason':reason});continue
        if audit_ran and rid not in keep_ids:continue
        ee=enrich.get(rid) or {};actor=ee.get('actor') or x.get('actor');workflow=ee.get('workflow') or x.get('workflow');nf=x.get('need_frame') or ((x.get('problem_obs') or {}).get('need_frame')) or {}
        ready,rscore,rreasons=_discussion_readiness(x.get('problem'),actor,workflow,nf,{},product=x.get('product_name'),evidence_count=1)
        if not ready:lead_filtered.append({'id':rid,'reason':'FOUNDER_DISCUSSION_NOT_READY','readiness_score':rscore,'readiness_reasons':rreasons});continue
        leads.append({'research_id':rid,'founder_status':'RESEARCH_LEAD_NEEDS_CORROBORATION','problem':_clean(x.get('problem'))[:700],'actor':actor,'workflow':workflow,'product':x.get('product_name'),'product_id':x.get('product_id'),'source_family':x.get('source_family'),'source_ref':x.get('source_ref'),'feedback_role':x.get('feedback_role'),'need_frame':nf,'missing_evidence':list(x.get('missing_evidence') or []),'research_value_score':x.get('research_value_score'),'discussion_readiness':{'score':rscore,'reasons':rreasons},'review_priority':rscore,'truth_label':'OBSERVED_NEED_FRAGMENT_NOT_CORROBORATED'})
    leads.sort(key=lambda x:x['review_priority'],reverse=True)

    ui=[];ui_filtered=[]
    for x in roi.get('user_innovation_signals') or []:
        ready,rscore,rreasons=_user_innovation_ready(x)
        if not ready:
            ui_filtered.append({'id':x.get('object_id'),'reason':'USER_INNOVATION_NOT_FOUNDER_READY','readiness_reasons':rreasons});continue
        ui.append({'signal_id':x.get('object_id'),'founder_status':'USER_INNOVATION_NEED_SOLUTION_SIGNAL','text':_clean(x.get('text'))[:900],'actor':x.get('actor'),'workflow':x.get('workflow'),'vertical':x.get('vertical'),'need_frame':x.get('need_frame') or {},'product':x.get('product_name'),'product_id':x.get('product_id'),'evidence_ref':x.get('evidence_ref'),'source_family':x.get('source_family'),'source_role':x.get('source_role'),'source_intent':x.get('source_intent'),'signal_score':x.get('signal_score'),'need_solution_pair_status':x.get('need_solution_pair_status'),'discussion_readiness':{'score':round(rscore,3),'reasons':rreasons},'review_priority':rscore,'truth_label':'SELF_SOLUTION_SIGNAL_NOT_INDEPENDENT_MARKET_DEMAND','diffusion_gap_assessment':_diffusion_gap_assessment(x,roi)})
    ui.sort(key=lambda x:x['review_priority'],reverse=True)
    for h in hyps:h['related_user_innovation_context']=_need_solution_context(h.get('need_frame'),roi.get('user_innovation_signals') or [])
    for l in leads:l['related_user_innovation_context']=_need_solution_context(l.get('need_frame'),roi.get('user_innovation_signals') or [])

    cards=_discussion_cards(hyps[:max_hypotheses],ui[:max_user_innovations],leads[:max_leads],roi,8)
    out={'engine_version':ENGINE_VERSION,'status':'READY_FOR_FOUNDER_DISCUSSION' if cards else 'NO_FOUNDER_USABLE_ITEMS','founder_discussion_card_count':len(cards),'founder_discussion_cards':cards,'research_hypothesis_count':len(hyps),'displayed_hypotheses':hyps[:max_hypotheses],'user_innovation_signal_count':len(ui),'displayed_user_innovation_signals':ui[:max_user_innovations],'research_lead_count':len(leads),'displayed_research_leads':leads[:max_leads],'filtered_hypotheses':filtered[:30],'deterministically_filtered_leads':lead_filtered[:40],'filtered_user_innovations':ui_filtered[:30],'employer_demand_context_count':len(roi.get('employer_demand_signals') or []),'market_state_count':len(roi.get('market_states') or []),'relationship_audit':relationship_audit or {},'lead_audit':lead_audit or {},'product_usability_boundary':'Only discussion-ready, role-correct research evidence is surfaced. This is not automatic venture selection; WTP, market attractiveness, causal why-now and founder captureability remain external-evidence questions.'}
    return out

def render_markdown(out:dict[str,Any])->str:
    lines=['# SignalForge Continuous Research Shortlist U10','',f"Status: **{out.get('status')}**",'', '> 只顯示值得 Founder 花注意力的研究卡；未通過 discussion-readiness 的資料仍可留在研究層，但不佔 Founder surface。','',f"## Founder discussion cards ({len(out.get('founder_discussion_cards') or [])})"]
    for i,c in enumerate(out.get('founder_discussion_cards') or [],1):
        lines += ['',f"### D{i} · {c.get('card_type')} · {c.get('discussion_id')}",f"**Problem / signal**：{c.get('problem')}",f"- Actor / workflow：{c.get('actor') or 'UNKNOWN'} / {c.get('workflow') or 'UNKNOWN'}",f"- Discussion readiness：{c.get('discussion_readiness')}",f"- Independent evidence：{c.get('independent_evidence') if c.get('independent_evidence') is not None else 'UNKNOWN'}",f"- Independent source origins：{c.get('independent_source_origins') if c.get('independent_source_origins') is not None else 'UNKNOWN'}",f"- Unknowns：{', '.join(c.get('unknowns') or []) or 'NONE'}",f"- Boundary：{c.get('truth_boundary')}",f"- Best next evidence：{json.dumps(c.get('best_next_evidence_plan') or {},ensure_ascii=False)}"]
    lines += ['','---','**Truth boundary:** Founder research/discussion surface only; no card self-certifies a product wedge, WTP, market attractiveness, or external validation.','']
    return '\n'.join(lines)

def write_shortlist(out:dict[str,Any])->dict[str,str]:
    JSON_PATH.parent.mkdir(parents=True,exist_ok=True);JSON_PATH.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str),encoding='utf-8');MD_PATH.write_text(render_markdown(out),encoding='utf-8');return {'json':str(JSON_PATH),'markdown':str(MD_PATH)}

def static_acceptance()->dict[str,bool]:
    ev=[{'ref':'reddit:1','text':'Every booking means I type customer details by hand again.','feedback_role':'PROBLEM_REPORT'},{'ref':'forum:2','text':'I re-enter the same booking customer details manually.','feedback_role':'PROBLEM_REPORT'}]
    good={'hypothesis_key':'h1','problem':'Every booking means I type the same customer details by hand again.','actor':'small_business_owner','workflow':'booking','feedback_role':'PROBLEM_REPORT','independent_problem_evidence_count':2,'independent_source_origins':2,'need_frame':{'workflow':'booking','actions':['enter'],'objects':['customer details'],'workaround':'manual re-entry'},'signals':{'manual_work':True,'frequency':True,'source_diversity':2,'independent_source_origins':2},'evidence_preview':ev,'unknowns':[]}
    narrow={**good,'hypothesis_key':'h2','problem':'ImportError: No module named jsonpickle','actor':None,'workflow':'other','need_frame':{'failure_modes':['import_error'],'objects':['jsonpickle']},'signals':{},'evidence_preview':ev}
    copied={**good,'hypothesis_key':'h3','independent_source_origins':1}
    lead={'research_id':'l1','problem':'Codex made slow progress on my UI redesign and kept stopping for confirmation again and again.','actor':'developer','workflow':'ui_redesign','feedback_role':'PROBLEM_REPORT','need_frame':{'workflow':'ui_redesign','failure_modes':['slow_progress'],'consequence':'repeated interruption'}}
    ui={'object_id':'u1','object_type':'USER_INNOVATION_NEED_SOLUTION_SIGNAL','text':'I built a tool to generate slides from papers because I hate formatting decks every time.','signal_score':3,'evidence_ref':'community:p1','source_family':'community_raw','source_role':'FIRSTHAND_USER_PAIN','source_intent':'SELF_SOLUTION_FOR_OWN_NEED','workflow':'research','need_frame':{'workflow':'research','actions':['format'],'objects':['slides']}}
    jobui={**ui,'object_id':'u2','source_family':'jobs','source_role':'HIRING_OR_VENDOR_CONTEXT','text':'We built automation because our teams needed it.'}
    out=build_shortlist([good,narrow,copied],[lead],research_objects={'user_innovation_signals':[ui,jobui],'external_enablers':[{'enabler_type':'TECHNOLOGY','span':'Unrelated Cypress testing technology','evidence_ref':'n:1','workflow':'booking'}]})
    return {'good_problem_visible':any(x.get('hypothesis_key')=='h1' for x in out['displayed_hypotheses']),'narrow_tech_hidden':any(x.get('id')=='h2' for x in out['filtered_hypotheses']),'copied_recurrence_hidden':any(x.get('id')=='h3' for x in out['filtered_hypotheses']),'direct_workflow_lead_visible':any(x.get('research_id')=='l1' for x in out['displayed_research_leads']),'real_user_innovation_visible':len(out['displayed_user_innovation_signals'])==1 and out['displayed_user_innovation_signals'][0]['signal_id']=='u1','job_not_user_innovation':all(x.get('signal_id')!='u2' for x in out['displayed_user_innovation_signals']),'generic_workflow_does_not_create_why_now':not (out['founder_discussion_cards'][0].get('why_now_context') if out['founder_discussion_cards'] else []),'founder_cards_exist':len(out['founder_discussion_cards'])>=2,'best_next_evidence_plan_attached':all(bool(c.get('best_next_evidence_plan')) for c in out['founder_discussion_cards']),'self_solution_plan_prioritizes_recurrence':any((c.get('card_type')=='USER_INNOVATION_NEED_SOLUTION_SIGNAL' and ((c.get('best_next_evidence_plan') or {}).get('next_steps') or [{}])[0].get('evidence')=='INDEPENDENT_NEED_RECURRENCE') for c in out['founder_discussion_cards'])}
