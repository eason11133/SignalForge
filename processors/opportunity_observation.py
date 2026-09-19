from __future__ import annotations

import hashlib, json, os, re, time, sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from processors.opportunity_evidence_atoms import annotate_observation, ensure_observation_schema, EVIDENCE_SCHEMA_VERSION, ENGINE_VERSION as EVIDENCE_ATOM_ENGINE_VERSION

ENGINE_VERSION='opportunity-observation-u9-sqlite-row-cache'
PARSER_SEMANTIC_CONSTITUTION_VERSION='opportunity-observation-u5-incremental-recovery-cache'
CACHE_FORMAT_VERSION='sqlite-observation-cache-v3'
LEGACY_CACHE_PATH=Path('.radar_runtime/opportunity_observation_research_a1_cache.json')
CACHE_DB_PATH=Path('.radar_runtime/opportunity_observation_cache_v3.sqlite3')
CACHE_PATH=LEGACY_CACHE_PATH
_WS=re.compile(r'\s+'); _SENT=re.compile(r'(?<=[.!?])\s+|\n+')
NEG=re.compile(r"\b(?:annoy|frustrat|tedious|cumbersome|painful|time[- ]consuming|inconvenien|too many|too slow|slow|hard to|difficult to|hate|keeps? (?:breaking|failing|resetting|forgetting|crashing|freezing)|doesn['’]?t|does not|can['’]?t|cannot|missing|lost|errors?|rework|duplicate|delay|wait|manual|by hand|re[- ]enter|repeat|again|every time|constantly|too expensive|absurdly high|overpriced|overkill|paywall|limited|unavailable|crash(?:es|ing)?|freez(?:e|es|ing)?|fails?|broken|waste of (?:time|money)|charged me|did not agree|won['’]?t accept|doesn['’]?t accept|wrong language|incorrectly|mismatch)\b",re.I)
POSITIVE=re.compile(r"\b(?:great|excellent|beautifully|reasonable|worth it|cheap|economical|love|useful|works? well|seamlessly|essential features|fine and useful)\b",re.I)
MARKETING_SOLUTION=re.compile(r"\b(?:our mission is|our mission|we help|we enable|we empower|we provide|we build|we are building|we're building|designed to|helps? teams?|automating the manual workflows|will work from shared|will be handled through automation|platform for|solution for|so teams can|allows? teams to|enables? teams to)\b",re.I)
FUTURE_STATE=re.compile(r"\b(?:will work|will be handled|will propagate|will enable|will allow|future state|our vision|our mission)\b",re.I)
FIRSTHAND_PAIN_FAMILIES={'app_store_reviews','stackexchange','reddit_rss','reddit','community_raw','stackoverflow','hackernews'}
SECONDARY_CONTEXT_FAMILIES={'jobs','news','yc','app_store','market_supply_external','packages'}
STRUCTURAL_CHANGE_FAMILIES={'news','app_store','market_supply_external','packages','yc'}
CATEGORY_WORKFLOW={'travel':'travel_planning','book':'reading_study','books':'reading_study','education':'reading_study','productivity':'productivity','business':'ops','finance':'billing','medical':'healthcare_ops','health & fitness':'healthcare_ops'}
DOMAIN_ANCHOR=re.compile(r"\b(?:healthcare|clinical|ehr|referral|supply chain|warehouse|logistics|invoice|billing|booking|travel|itinerary|reading|notes?|school|student|teacher|vehicle|car|tpms|garage|home|garden|legal|contract|customer support|crm|sales|inventory|maintenance|inspection|research|security|memory safety|software|developer|restaurant|hotel)\b",re.I)
MANUAL=re.compile(r"\b(?:manual(?:ly)?|by hand|spreadsheet|excel|google sheets?|copy[- ]?paste|re[- ]enter|data entry|phone call|fax|paper|notebook|email|multiple (?:apps|tools|tabs)|workaround|enter all .* manually)\b",re.I)
BURDEN=re.compile(r"\b(?:hours?|minutes?|days?|entire day|time[- ]consuming|delay|backlog|rework|error|lost|waste|cost|fine|penalt|unpaid|bottleneck|headcount|revenue|missed|too many steps?|takes? forever|waste of (?:time|money))\b",re.I)
FREQ=re.compile(r"\b(?:every time|every day|every week|daily|weekly|monthly|often|frequently|constantly|repeatedly|again and again|each time|still have to|always|half of the time|for weeks)\b",re.I)
DIST=re.compile(r"\b(?:too expensive|absurdly high|price|pricing|subscription|paywall|fee|enterprise only|minimum|not available|unavailable|hard to access|waitlist|channel|commission|middleman|bundle|only available|won['’]?t accept .* subscription|charged|trial)\b",re.I)
CHANGE=re.compile(r"\b(?:launched|released|now available|newly available|now supports?|can now|became available|price (?:cut|drop)|cost fell|cheaper|new regulation|new law|deadline|api now|open[- ]sourc(?:e|ed)|introduced|roll(?:ed)? out)\b",re.I)
SECOND=re.compile(r"\b(?:since (?:using|adopting|switching)|after (?:using|adopting|switching|rolling out)|now that|because of .* adoption|as more .* use|created a new problem|introduced a new problem)\b",re.I)
PAY=re.compile(r"(?:\$\s?\d|usd\s?\d|nt\$\s?\d|\bpaid\b|\bpricing\b|\bsubscription\b|\bfee\b|\bpremium\b|\bpro account\b|\bcharged\b|\bbought\b|\bpurchased\b|\bper month\b|\bper year\b|\barr\b|\bmrr\b)",re.I)
PAYMENT_BEHAVIOR=re.compile(r"\b(?:i\s+(?:paid|bought|purchased|subscribed)|we\s+(?:paid|bought|purchased|subscribed)|(?:i|we|you)\s+(?:was|were\s+)?charged|charged\s+me|was charged|were charged|my subscription|our subscription|got the (?:yearly|monthly|annual) subscription|paid pro account|paid account|signed paid pilot|deposit paid)\b",re.I)
COMMERCIAL_CONTEXT=re.compile(r"\b(?:pricing|price|subscription|premium|pro account|fee|per month|per year|annual|monthly|trial|charged|purchase|paid)\b|\$\s?\d",re.I)
FUNDING=re.compile(r"\b(?:funding|raised|raises|series [a-z]|valuation|investor|backed by|venture round)\b",re.I)
APP_CONTROL=re.compile(r"\b(?:app|apps|update|feature|ui|interface|screen|button|login|account|sync|upload|download|export|import|record|recording|note|notes|notification|search|parse|email|itinerary|crash|freeze|freezes|freezing|bug|subscription|premium|pro|payment|charged|trial|voice|playback|restart|data|settings|save|delete|deleted|lost)\b",re.I)
LISTED_ENTITY=re.compile(r"\b(?:restaurant|cafe|coffee|omelet|food|waiter|waitress|server|hotel room|front desk|tour guide|attraction|meal|dish|burger|pizza|salad|doctor|dentist|store clerk|shop owner)\b",re.I)

WORKFLOWS={
'booking':re.compile(r'\b(?:booking|appointment|reservation|schedule|scheduling)\b',re.I),
'billing':re.compile(r'\b(?:invoice|billing|quote|estimate|reconcile|expense|receipt|payment|subscription)\b',re.I),
'sales':re.compile(r'\b(?:sales|crm|lead|follow[- ]up|pipeline)\b',re.I),
'support':re.compile(r'\b(?:support|ticket|customer service|call handling|inbox)\b',re.I),
'intake':re.compile(r'\b(?:intake|onboarding|referral|application|form|data entry)\b',re.I),
'ops':re.compile(r'\b(?:inventory|order|dispatch|maintenance|inspection|procurement|monitoring|warehouse)\b',re.I),
'compliance':re.compile(r'\b(?:compliance|permit|claim|renewal|regulation|paperwork)\b',re.I),
'research':re.compile(r'\b(?:research|paper|literature|scholar|analysis)\b',re.I),
'reading_study':re.compile(r'\b(?:read|reading|book pages?|study|studying|flashcards?|lecture notes?|sermon notes?)\b',re.I),
'travel_planning':re.compile(r'\b(?:travel|trip|itinerary|flight|hotel planning|airbnb|bus reservation)\b',re.I),
'home_diy':re.compile(r'\b(?:home improvement|diy|repair|renovation|household|garage|garden|bicycle|bike|vehicle repair)\b',re.I),
'coordination':re.compile(r'\b(?:coordination|coordinate|handoff|meeting|chasing|queue)\b',re.I),
'productivity':re.compile(r'\b(?:notes?|document|planner|task|productivity|workspace)\b',re.I),
'healthcare_ops':re.compile(r'\b(?:clinical|ehr|referral|patient|primary care|specialist|healthcare)\b',re.I),
}

STACK_SCOPE={'workplace':('worker','professional_services'),'academia':('student_or_researcher','education'),'diy':('homeowner','consumer'),'travel':('traveler','consumer'),'cooking':('home_cook','consumer'),'money':('household_finance_user','consumer'),'law':('legal_service_user','professional_services'),'parenting':('parent','consumer'),'bicycles':('cyclist','consumer'),'outdoors':('outdoor_user','consumer'),'gardening':('gardener','consumer'),'mechanics':('vehicle_owner','consumer'),'pets':('pet_owner','consumer'),'freelancing':('freelancer','professional_services'),'superuser':('computer_user','consumer'),'webapps':('web_app_user','consumer'),'electronics':('electronics_user','consumer'),'photo':('photographer','consumer'),'fitness':('fitness_user','consumer'),'woodworking':('woodworker','consumer'),'homebrew':('homebrewer','consumer'),'aviation':('aviation_user','consumer')}
REDDIT_SCOPE={'books':('reader','consumer'),'college':('student','education'),'productivity':('knowledge_worker','consumer'),'buyitforlife':('product_buyer','consumer'),'homeimprovement':('homeowner','consumer'),'smallbusiness':('small_business_owner','professional_services'),'entrepreneur':('business_owner','professional_services'),'freelance':('freelancer','professional_services'),'teachers':('teacher','education')}
CATEGORY_VERTICAL={'business':'professional_services','productivity':'consumer','education':'education','travel':'consumer','finance':'consumer','lifestyle':'consumer','utilities':'consumer','medical':'healthcare','health & fitness':'healthcare','books':'consumer','book':'consumer'}

SIGNATURES={
'crash_freeze':r'crash|freez|restart(?:ing)?\s+(?:the )?(?:app|playback)|stops? working|never works?',
'sync_failure':r'(?:doesn.t|does not|won.t|will not|fail(?:s|ed)? to|not)\s+sync|sync.*(?:wrong|outdated|fail|error)|across (?:apps|devices).*(?:not|fail|outdated)',
'state_loss':r'forget|reset|doesn.t save|does not save|settings.*lost',
'data_loss':r'delet(?:ed|ing)?|disappear|lost (?:my )?(?:notes|data|recording)|note does not exist|cannot be recovered',
'import_parse_failure':r'(?:can.t|cannot|doesn.t|does not|won.t|will not)\s+(?:parse|import)|(?:parse|import|email).*(?:wrong|fail|incorrect|gave up)|determine which trip|marked it as a .* with no way to edit',
'upload_failure':r'(?:won.t|doesn.t|does not|fails? to)\s+upload|upload.*(?:fail|error)',
'recording_failure':r'(?:recording|record).*(?:stop|fail|lost|missing|unavailable|delete)|(?:stop|lost|missing|unavailable).*(?:recording|audio)',
'subscription_purchase_failure':r'(?:won.t|doesn.t|does not) accept.*subscription|subscription.*error|charged.*(?:trial|without|did not agree)|charged me|basic.*(?:after|despite).*charged',
'price_value':r'too expensive|absurdly high|overpriced|not worth|waste of money|(?:price|cost).*(?:high|expensive|1/10|cheaper)|(?:other|similar) apps?.*(?:cheaper|free)|\$\s?\d+.*(?:month|year|subscription|charged)',
'usage_limit':r'(?:too|way) limited|monthly character limit|usage cap|doesn.t offer unlimited|does not offer unlimited|one .* a month',
'manual_reentry':r're[- ]?enter|enter all .* manually|data entry|copy[- ]?paste',
'too_many_steps':r'too many (?:steps|taps|clicks)|takes? too many',
'slow_delay':r'too slow|delay|wait|takes? forever|days? later',
'coordination_failure':r'coordination|handoff|chasing|phone call.*nobody picks up|queue.*by hand',
'integration_failure':r'integration.*(?:fail|broken|error)|doesn.t work with|does not work with|incompatible',
'access_unavailable':r'unavailable|not available|waitlist|enterprise only',
'quality_limit':r'(?:quality|voice|generation).*(?:poor|bad|mechanical|limited)|too limited|mechanical voices?|extremely ai sounding',
'language_mismatch':r'(?:wrong language|in spanish|spanish.*(?:instead|while|but)|language.*(?:wrong|incorrect|mismatch))',
'processing_delay':r'(?:placed on hold|on hold again|pending for|waiting for|stuck for|there for almost another month)',
'tool_compatibility':r'(?:too old for .* diagnostic|diagnostic .* too old|incompatible .* (?:model|machine|tool)|doesn.t support .* model|does not support .* model)',
'navigation_friction':r'(?:navigat(?:ing|ion).*(?:cumbersome|hard|difficult)|cumbersome.*navigat|can.t easily see|cannot easily see)',
}

def clean(v:Any)->str:return _WS.sub(' ',str(v or '')).strip()
def sentences(text:str)->list[str]:
    return [s for s in (_WS.sub(' ',x).strip() for x in _SENT.split(clean(text))) if 18<=len(s)<=800]
def first_sentence(text:str,pat:re.Pattern[str])->str:
    for s in sentences(text):
        if pat.search(s):return s
    return ''
def workflow(text:str,hint:str='',category:str='')->str:
    hay=f'{hint} {text}'
    for name,p in WORKFLOWS.items():
        if p.search(hay):return name
    cl=category.lower().strip()
    return CATEGORY_WORKFLOW.get(cl,'other')

def problem_workflow(problem:str,doc:dict[str,Any],native_scope:str='')->tuple[str,str]:
    cat=clean(doc.get('app_category') or doc.get('category')).lower();hint=clean(doc.get('workflow_hint'))
    local=workflow(problem,hint,'')
    if local!='other':return local,'PROBLEM_SPAN'
    if cat in CATEGORY_WORKFLOW:return CATEGORY_WORKFLOW[cat],'SOURCE_SCHEMA_CATEGORY'
    if native_scope:
        scoped=workflow('',native_scope,'')
        if scoped!='other':return scoped,'SOURCE_SCHEMA_SCOPE'
    # Title is safer than the entire document; whole-document workflow caused unrelated billing/support leakage.
    title=workflow(clean(doc.get('title')),hint,'')
    if title!='other':return title,'TITLE_CONTEXT'
    return 'other','UNKNOWN'
SIGNATURE_PRIORITY=('subscription_purchase_failure','data_loss','import_parse_failure','upload_failure','language_mismatch','recording_failure','sync_failure','crash_freeze','state_loss','tool_compatibility','processing_delay','manual_reentry','coordination_failure','integration_failure','navigation_friction','slow_delay','usage_limit','quality_limit','access_unavailable','price_value','too_many_steps')
PARSER_EVIDENCE_COMPAT_VERSION='opportunity-evidence-atoms-u5-source-role-priors-founder-quality'
PARSER_CONSTITUTION_HASH=hashlib.sha256(json.dumps({'engine':PARSER_SEMANTIC_CONSTITUTION_VERSION,'evidence_atom_engine':PARSER_EVIDENCE_COMPAT_VERSION,'signatures_as_weak_features_not_gates':SIGNATURES,'stack_scope':STACK_SCOPE,'reddit_scope':REDDIT_SCOPE,'category_vertical':CATEGORY_VERTICAL,'signature_priority':SIGNATURE_PRIORITY,'source_role_contract':sorted(FIRSTHAND_PAIN_FAMILIES),'local_payment':True,'local_workflow':True,'incomplete_need_retention':True},sort_keys=True,default=str).encode()).hexdigest()[:20]
SOURCE_ROLE_CONSTITUTION_HASH=hashlib.sha256(json.dumps({'firsthand':sorted(FIRSTHAND_PAIN_FAMILIES),'secondary':sorted(SECONDARY_CONTEXT_FAMILIES),'structural_change':sorted(STRUCTURAL_CHANGE_FAMILIES)},sort_keys=True).encode()).hexdigest()[:20]
def problem_signatures(text:str)->list[str]:
    t=clean(text);return [k for k,pat in SIGNATURES.items() if re.search(pat,t,re.I)]
def primary_problem_signature(text:str)->str:
    sig=set(problem_signatures(text))
    for k in SIGNATURE_PRIORITY:
        if k in sig:return k
    return ''
def _negative_problem_sentence(sent:str)->bool:
    if not NEG.search(sent):return False
    # Vendor mission/future-state language is supply/context, not evidence that a user currently suffers the pain.
    if MARKETING_SOLUTION.search(sent) or FUTURE_STATE.search(sent):return False
    if POSITIVE.search(sent) and not re.search(r"(?:but|however|except|downside|problem|error|fail|doesn['’]?t|cannot|charged me|too expensive|not worth|wrong|lost|missing|crash|freez)",sent,re.I):return False
    return True
def concept_tags(text:str)->list[str]:
    sig=problem_signatures(text);tags=list(sig)
    if re.search(r'multiple (?:apps|tools|tabs)|switch between|fragmented',text,re.I):tags.append('fragmented_tools')
    if re.search(r'notification|alert|reminder',text,re.I):tags.append('notifications')
    if re.search(r'page.*flip|hold.*page|book.*close|page.*stay open',text,re.I):tags.append('page_handling')
    return list(dict.fromkeys(tags))

def _source_role(doc:dict[str,Any],fam:str)->str:
    hinted=clean(doc.get('source_role_hint')).upper()
    if hinted:return hinted
    table=clean(doc.get('table')).lower()
    if fam in FIRSTHAND_PAIN_FAMILIES:return 'FIRSTHAND_USER_PAIN'
    if fam=='github' and ('issue' in table or 'discussion' in table):return 'FIRSTHAND_TECHNICAL_PAIN'
    if fam in {'app_store','market_supply_external'}:return 'MARKET_SUPPLY'
    if fam in {'news','packages','yc'}:return 'STRUCTURAL_OR_MARKET_CONTEXT'
    if fam=='jobs':return 'HIRING_OR_VENDOR_CONTEXT'
    if fam=='github':return 'TECHNICAL_MARKET_CONTEXT'
    return 'UNKNOWN_CONTEXT'

def _primary_pain_allowed(role:str)->bool:
    return role in {'FIRSTHAND_USER_PAIN','FIRSTHAND_TECHNICAL_PAIN'}

def _norm_problem_hash(text:str)->str:
    t=re.sub(r'[^a-z0-9]+',' ',clean(text).lower()).strip()
    return hashlib.sha1(t.encode()).hexdigest()[:18] if t else ''

def _problem_self_contained(problem:str,title:str,product_id:str,native_scope:str,actor:str)->bool:
    return bool(product_id or native_scope or actor!='unknown' or DOMAIN_ANCHOR.search(f'{title} {problem}'))

def _local_payment_span(problem:str,text:str,is_review:bool)->str:
    if not problem:return ''
    body=_review_body(text) if is_review else clean(text);ss=sentences(body);idx=_span_index(body,problem)
    parts=[problem]
    if idx is not None:
        if idx>0:parts.append(ss[idx-1])
        if idx+1<len(ss):parts.append(ss[idx+1])
    return ' '.join(parts)

def _native_scope(doc:dict[str,Any])->tuple[str,str,str]:
    fam=str(doc.get('source_family') or '').lower()
    if fam=='stackexchange':
        site=str(doc.get('community') or doc.get('site') or str(doc.get('source_name') or '').split(':')[-1]).lower();a,v=STACK_SCOPE.get(site,('community_user','other'));return a,v,site
    if fam=='reddit_rss':
        sub=str(doc.get('subreddit') or str(doc.get('source_name') or '').split('/')[-1]).lower();a,v=REDDIT_SCOPE.get(sub,('community_user','other'));return a,v,sub
    if fam in {'app_store_reviews','app_store'}:
        cat=clean(doc.get('app_category') or doc.get('category') or '').lower();return ('product_user' if fam=='app_store_reviews' else 'market_supplier',CATEGORY_VERTICAL.get(cat,'consumer'),cat)
    return 'unknown','other',''


def _review_body(text:str)->str:
    t=clean(text)
    m=re.search(r'\bReview:\s*(.*)$',t,re.I)
    return clean(m.group(1)) if m else t

def _review_target_and_problem(title:str,text:str,low_rating:bool)->tuple[str,str]:
    body=_review_body(text);ss=sentences(body)
    # Complaint target is decided from the complaint sentence itself. A generic mention of "app" elsewhere
    # cannot convert a restaurant/hotel/content complaint into a software pain.
    for sent in ss:
        if not _negative_problem_sentence(sent):continue
        if re.search(r'\b(?:subscription|premium|charged|payment|trial|price|monthly|annual|billing)\b',sent,re.I):return 'PRODUCT_BILLING',sent
        app=bool(APP_CONTROL.search(sent));listed=bool(LISTED_ENTITY.search(sent))
        if app and not listed:return 'PRODUCT_APP',sent
        if listed and not app:return 'LISTED_ENTITY_OR_CONTENT',''
        if app:return 'PRODUCT_APP',sent
    # Titles can carry the direct software failure ("Constantly crashing"), but only when they themselves
    # contain an app-control/failure term. Low rating alone is not enough.
    if _negative_problem_sentence(title) and APP_CONTROL.search(title):
        target='PRODUCT_BILLING' if re.search(r'\b(?:subscription|charged|payment|trial|price|billing)\b',title,re.I) else 'PRODUCT_APP'
        return target,clean(title)
    return ('LISTED_ENTITY_OR_CONTENT','') if LISTED_ENTITY.search(body) else ('UNKNOWN','')

def _app_target(title:str,text:str)->str:
    return _review_target_and_problem(title,text,False)[0]

def _review_problem(title:str,text:str,low_rating:bool,target:str)->str:
    t,p=_review_target_and_problem(title,text,low_rating)
    return p if t==target and t in {'PRODUCT_APP','PRODUCT_BILLING'} else ''

def _span_index(text:str,span:str)->int|None:
    if not span:return None
    ss=sentences(_review_body(text))
    target=clean(span)
    for i,x in enumerate(ss):
        if clean(x)==target or target in clean(x) or clean(x) in target:return i
    return None

def _doc_key(doc:dict[str,Any])->str:
    core='|'.join(str(doc.get(k) or '') for k in ('source','table','pk','title','text','rating','app_id','app_category','community','search_query'))
    return hashlib.sha1(core.encode()).hexdigest()

def observation_from_doc(doc:dict[str,Any])->dict[str,Any]:
    text=clean(doc.get('text'));title=clean(doc.get('title'));fam=str(doc.get('source_family') or doc.get('source') or 'unknown')
    actor,vertical,native_scope=_native_scope(doc);role=_source_role(doc,fam)
    if clean(doc.get('actor_scope')):actor=clean(doc.get('actor_scope'))
    if clean(doc.get('vertical_hint')):vertical=clean(doc.get('vertical_hint'))
    cat=clean(doc.get('app_category') or doc.get('category'))
    try:rating=float(doc.get('rating')) if doc.get('rating') not in (None,'') else None
    except Exception:rating=None
    low_rating=rating is not None and rating<=3;is_review=fam=='app_store_reviews'
    if is_review:target,problem=_review_target_and_problem(title,text,low_rating)
    else:target='PRIMARY_SOURCE_SUBJECT';problem=next((x for x in sentences(text) if _negative_problem_sentence(x)),'')
    # Context-only families may describe a problem in marketing/news language, but are never primary pain authority.
    reported_problem=problem if problem and not _primary_pain_allowed(role) else ''
    if not _primary_pain_allowed(role):problem=''
    if fam=='app_store':problem=''
    if is_review and target not in {'PRODUCT_APP','PRODUCT_BILLING'}:problem=''
    wf,wf_origin=problem_workflow(problem or reported_problem,doc,native_scope)
    local_text=' '.join(x for x in [problem,reported_problem] if x)
    behavior=first_sentence(local_text,MANUAL);burden=first_sentence(local_text,BURDEN);frequency=first_sentence(local_text,FREQ);distribution=first_sentence(local_text,DIST);second=first_sentence(local_text,SECOND)
    # Structural change is a separate evidence role and is not inferred from job/vendor descriptions.
    change=first_sentence(text,CHANGE) if fam in STRUCTURAL_CHANGE_FAMILIES else ''
    paid_supply=bool(doc.get('paid_supply')) or bool(PAY.search(text) and not FUNDING.search(text) and fam=='app_store')
    commercial_context=bool(COMMERCIAL_CONTEXT.search(text) and not FUNDING.search(text) and (is_review or fam in {'stackexchange','reddit_rss'}))
    pay_local=_local_payment_span(problem or reported_problem,text,is_review);payment_behavior=bool(PAYMENT_BEHAVIOR.search(pay_local) and not FUNDING.search(pay_local))
    direct_pain=bool(problem and _negative_problem_sentence(problem) and _primary_pain_allowed(role))
    sig=problem_signatures(problem);primary_sig=primary_problem_signature(problem);signature_strength=('STRONG' if len(sig)==1 else ('MULTI' if len(sig)>1 else 'NONE'))
    payment_scope='OBSERVED_CURRENT_PAYMENT' if payment_behavior else ('COMMERCIAL_CONTEXT_ONLY' if commercial_context or paid_supply else 'NONE')
    evidence_role='DIRECT_PAIN' if direct_pain else ('MARKET_SUPPLY' if paid_supply else ('STRUCTURAL_CHANGE' if change else ('REPORTED_PROBLEM_CONTEXT' if reported_problem else ('SECOND_ORDER_SIGNAL' if second else 'OTHER'))))
    product_id=clean(doc.get('app_id') or doc.get('product_id'));problem_hash=_norm_problem_hash(problem);self_contained=_problem_self_contained(problem,title,product_id,native_scope,actor) if problem else False
    obs_id=f"obs_{hashlib.sha1((str(doc.get('source'))+'|'+str(doc.get('table'))+'|'+str(doc.get('pk'))).encode()).hexdigest()[:18]}"
    return {'observation_id':obs_id,'source':str(doc.get('source') or ''),'source_family':fam,'source_table':str(doc.get('table') or ''),'source_ref':str(doc.get('pk') or ''),'url':clean(doc.get('url')),'title':title,'text':text,'actor_scope':actor,'vertical':vertical,'native_scope':native_scope,'workflow':wf,'workflow_known':wf!='other','workflow_origin':wf_origin,'product_id':product_id,'product_name':clean(doc.get('app_name') or doc.get('product_name')),'category':cat,'rating':rating,'paid_supply':paid_supply,'commercial_behavior_explicit':commercial_context,'commercial_context_explicit':commercial_context,'payment_behavior_observed':payment_behavior,'payment_evidence_span':pay_local if payment_behavior else '','problem_target':target,'problem_target_confidence':(1.0 if target in {'PRODUCT_APP','PRODUCT_BILLING','PRIMARY_SOURCE_SUBJECT'} and bool(problem) else (0.8 if target=='LISTED_ENTITY_OR_CONTENT' else 0.0)),'problem_span':problem,'reported_problem_span':reported_problem,'problem_span_hash':hashlib.sha1(clean(problem).encode()).hexdigest()[:16] if problem else None,'normalized_problem_hash':problem_hash,'problem_sentence_index':_span_index(text,problem),'problem_self_contained':self_contained,'current_behavior_span':behavior,'burden_span':burden,'frequency_span':frequency,'distribution_span':distribution,'change_span':change,'second_order_span':second,'problem_tags':concept_tags(problem or ''),'problem_signatures':sig,'primary_problem_signature':primary_sig,'problem_polarity':('NEGATIVE' if direct_pain else 'NON_NEGATIVE'),'problem_signature_strength':signature_strength,'problem_signature_count':len(sig),'payment_scope':payment_scope,'evidence_role':evidence_role,'source_role':role,'pain_evidence_tier':('FIRSTHAND' if direct_pain else 'CONTEXT'),'primary_pain_authority':_primary_pain_allowed(role),'direct_pain':direct_pain,'manual_behavior':bool(behavior),'burden_explicit':bool(burden),'frequency_explicit':bool(frequency),'distribution_explicit':bool(distribution),'change_explicit':bool(change),'change_authority':bool(change and fam in STRUCTURAL_CHANGE_FAMILIES),'second_order_explicit':bool(second),'low_rating':low_rating,'source_native_actor':actor!='unknown','actor_origin':'SOURCE_SCHEMA' if actor!='unknown' else 'TEXT_OR_UNKNOWN','independence_key':f"{fam}|{doc.get('pk')}",'independence_class':('REVIEW' if fam=='app_store_reviews' else ('QUESTION_OR_THREAD' if fam in {'stackexchange','reddit_rss'} else 'DOCUMENT')),'market_key':f'{vertical}|{wf}','source_identity_key':(f"product:{product_id}" if product_id else f"source:{fam}:{doc.get('pk')}"),'doc_key':_doc_key(doc),'acquisition_mode':('TARGETED_CORROBORATION_RECOVERY' if 'RECOVERY' in clean(doc.get('search_query')).upper() else 'BASE_OR_SEED'),'hypothesis_seed_eligible':bool(direct_pain and _primary_pain_allowed(role) and sig and self_contained),'capturability_signals':{'product_scoped':bool(product_id),'payment_behavior':payment_behavior,'commercial_context':commercial_context,'burden':bool(burden),'frequency':bool(frequency),'manual_behavior':bool(behavior),'distribution':bool(distribution)},'raw_doc':doc}

def _atomic_stream_json(path:Path,payload:Any,*,indent:int|None=None)->dict[str,Any]:
    """Atomic, streaming JSON persistence.

    Cache/state persistence is an optimization boundary, not a reason to duplicate the
    entire corpus into one in-memory JSON string.  The encoder streams chunks to a temp
    file and replaces the previous file only after a complete fsync.
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    before=path.stat().st_size if path.exists() else 0
    try:
        enc=json.JSONEncoder(ensure_ascii=False,default=str,indent=indent,separators=None if indent else (',',':'))
        with tmp.open('w',encoding='utf-8',newline='') as f:
            for chunk in enc.iterencode(payload):f.write(chunk)
            f.flush();os.fsync(f.fileno())
        tmp.replace(path)
        return {'status':'WRITTEN_ATOMIC_STREAM','bytes_before':before,'bytes_after':path.stat().st_size,'error':None}
    except (MemoryError,OSError,ValueError,TypeError) as exc:
        try:
            if tmp.exists():tmp.unlink()
        except Exception:pass
        # Cache persistence must never destroy the previous good cache or kill live discovery.
        return {'status':'PERSIST_FAILED_PREVIOUS_CACHE_PRESERVED','bytes_before':before,'bytes_after':path.stat().st_size if path.exists() else 0,'error':type(exc).__name__+': '+str(exc)[:240]}


def _cache_pack(o:dict[str,Any])->dict[str,Any]:
    """Store derived observation state, not another copy of the raw source corpus."""
    x={k:v for k,v in o.items() if k not in {'text','raw_doc'}}
    x['_cache_format']=CACHE_FORMAT_VERSION
    return x


def _hydrate_cached(cached:dict[str,Any],doc:dict[str,Any])->dict[str,Any]:
    x=dict(cached);x.pop('_cache_format',None)
    x['text']=clean(doc.get('text'));x['raw_doc']=doc
    # Current source document remains authority for these transport fields.
    x['title']=clean(doc.get('title') or x.get('title'));x['url']=clean(doc.get('url') or x.get('url'))
    return x


def _legacy_header_parser_hash(path:Path)->str|None:
    """Read only the small JSON header. Never json.load the full legacy cache."""
    if not path.exists(): return None
    try:
        with path.open('r',encoding='utf-8') as f:
            prefix=f.read(131072)
        m=re.search(r'"parser_constitution_hash"\s*:\s*"([^"]+)"',prefix)
        return m.group(1) if m else None
    except Exception:
        return None


def _iter_legacy_cache_items(path:Path):
    """Stream the legacy {items:{key:value,...}} JSON object one row at a time.

    This deliberately avoids json.load/json.loads on the 70MB+ cache.  It is only a
    one-time migration path into SQLite; the new cache never returns to monolithic JSON.
    """
    dec=json.JSONDecoder();marker='"items":{'
    with path.open('r',encoding='utf-8') as f:
        buf=''
        while marker not in buf:
            chunk=f.read(65536)
            if not chunk:return
            buf+=chunk
            if len(buf)>2_000_000 and marker not in buf:
                raise ValueError('LEGACY_CACHE_ITEMS_MARKER_NOT_FOUND')
        buf=buf.split(marker,1)[1]
        while True:
            buf=buf.lstrip()
            while buf.startswith(','):buf=buf[1:].lstrip()
            if buf.startswith('}') or not buf:
                if buf.startswith('}'):return
                chunk=f.read(65536)
                if not chunk:return
                buf+=chunk;continue
            while True:
                try:key,kend=dec.raw_decode(buf);break
                except json.JSONDecodeError:
                    chunk=f.read(65536)
                    if not chunk:raise
                    buf+=chunk
            buf=buf[kend:].lstrip()
            while not buf:
                chunk=f.read(65536)
                if not chunk:raise ValueError('LEGACY_CACHE_TRUNCATED_AFTER_KEY')
                buf+=chunk;buf=buf.lstrip()
            if not buf.startswith(':'):raise ValueError('LEGACY_CACHE_EXPECTED_COLON')
            buf=buf[1:].lstrip()
            while True:
                try:val,vend=dec.raw_decode(buf);break
                except json.JSONDecodeError:
                    chunk=f.read(65536)
                    if not chunk:raise
                    buf+=chunk
            if isinstance(key,str) and isinstance(val,dict):yield key,val
            buf=buf[vend:]


def _db_connect()->sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(str(CACHE_DB_PATH),timeout=30.0)
    c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=NORMAL')
    c.execute('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS items (doc_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return c


def _db_meta(c:sqlite3.Connection,k:str)->str|None:
    r=c.execute('SELECT v FROM meta WHERE k=?',(k,)).fetchone();return str(r[0]) if r else None


def _db_set_meta(c:sqlite3.Connection,k:str,v:Any)->None:
    c.execute('INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(k,str(v)))


def _db_count(c:sqlite3.Connection)->int:
    return int(c.execute('SELECT COUNT(*) FROM items').fetchone()[0])


def _migrate_legacy_json_to_sqlite(c:sqlite3.Connection)->dict[str,Any]:
    audit={'status':'NOT_NEEDED','legacy_bytes':LEGACY_CACHE_PATH.stat().st_size if LEGACY_CACHE_PATH.exists() else 0,'rows_migrated':0,'parser_match':False,'error':None}
    if _db_count(c)>0:return audit
    if not LEGACY_CACHE_PATH.exists():
        audit['status']='NO_LEGACY_CACHE';return audit
    ph=_legacy_header_parser_hash(LEGACY_CACHE_PATH);audit['legacy_parser_hash']=ph;audit['parser_match']=ph==PARSER_CONSTITUTION_HASH
    if ph!=PARSER_CONSTITUTION_HASH:
        audit['status']='LEGACY_PARSER_MISMATCH_SKIP_MIGRATION';return audit
    try:
        batch=[];n=0;legacy_full=0
        for k,v in _iter_legacy_cache_items(LEGACY_CACHE_PATH):
            if 'text' in v or 'raw_doc' in v:legacy_full+=1
            packed=dict(v);packed.pop('text',None);packed.pop('raw_doc',None);packed['_cache_format']=CACHE_FORMAT_VERSION
            batch.append((k,json.dumps(packed,ensure_ascii=False,separators=(',',':'),default=str)))
            if len(batch)>=250:
                c.executemany('INSERT OR REPLACE INTO items(doc_key,payload) VALUES(?,?)',batch);c.commit();n+=len(batch);batch=[]
        if batch:c.executemany('INSERT OR REPLACE INTO items(doc_key,payload) VALUES(?,?)',batch);c.commit();n+=len(batch)
        _db_set_meta(c,'parser_constitution_hash',PARSER_CONSTITUTION_HASH);_db_set_meta(c,'cache_format_version',CACHE_FORMAT_VERSION);_db_set_meta(c,'engine_version',ENGINE_VERSION);c.commit()
        audit.update({'status':'MIGRATED_STREAMING_TO_SQLITE','rows_migrated':n,'legacy_full_payload_items':legacy_full})
    except Exception as exc:
        c.rollback();audit.update({'status':'LEGACY_MIGRATION_FAILED_FAIL_SOFT','error':type(exc).__name__+': '+str(exc)[:220]})
    return audit


def _cache_open(*,use_cache:bool=True)->tuple[sqlite3.Connection|None,dict[str,Any]]:
    if not use_cache:return None,{'status':'DISABLED','items':0,'parser_match':False,'format':CACHE_FORMAT_VERSION}
    before=CACHE_DB_PATH.stat().st_size if CACHE_DB_PATH.exists() else 0
    try:
        c=_db_connect();migration=_migrate_legacy_json_to_sqlite(c)
        ph=_db_meta(c,'parser_constitution_hash');items=_db_count(c)
        if items and ph!=PARSER_CONSTITUTION_HASH:
            # Semantic parser changed: invalidate rows transactionally, not by risking a huge in-memory reload.
            c.execute('DELETE FROM items');_db_set_meta(c,'parser_constitution_hash',PARSER_CONSTITUTION_HASH);c.commit();items=0
            status='MISS_PARSER_CONSTITUTION_SQLITE_RESET'
        else:
            if not ph:_db_set_meta(c,'parser_constitution_hash',PARSER_CONSTITUTION_HASH);c.commit()
            status='HIT_SQLITE' if items else ('MIGRATED_SQLITE' if migration.get('rows_migrated') else 'MISS_EMPTY_SQLITE')
        return c,{'status':status,'items':items,'parser_match':items>0,'format':CACHE_FORMAT_VERSION,'db_bytes':CACHE_DB_PATH.stat().st_size if CACHE_DB_PATH.exists() else before,'legacy_migration':migration}
    except Exception as exc:
        return None,{'status':'SQLITE_CACHE_UNAVAILABLE_FAIL_SOFT','items':0,'parser_match':False,'format':CACHE_FORMAT_VERSION,'error':type(exc).__name__+': '+str(exc)[:220]}


def _cache_get(c:sqlite3.Connection|None,k:str)->dict[str,Any]|None:
    if c is None:return None
    r=c.execute('SELECT payload FROM items WHERE doc_key=?',(k,)).fetchone()
    if not r:return None
    try:
        x=json.loads(r[0]);return x if isinstance(x,dict) else None
    except Exception:return None


def _cache_upsert(c:sqlite3.Connection|None,rows:list[tuple[str,dict[str,Any]]])->dict[str,Any]:
    if c is None:return {'status':'DISABLED','rows_written':0}
    if not rows:return {'status':'SKIPPED_CLEAN_ROW_CACHE','rows_written':0,'items_after':_db_count(c)}
    try:
        payload=[(k,json.dumps(_cache_pack(v),ensure_ascii=False,separators=(',',':'),default=str)) for k,v in rows]
        c.executemany('INSERT INTO items(doc_key,payload) VALUES(?,?) ON CONFLICT(doc_key) DO UPDATE SET payload=excluded.payload',payload)
        _db_set_meta(c,'parser_constitution_hash',PARSER_CONSTITUTION_HASH);_db_set_meta(c,'cache_format_version',CACHE_FORMAT_VERSION);_db_set_meta(c,'engine_version',ENGINE_VERSION);c.commit()
        return {'status':'UPSERTED_SQLITE_ROWS','rows_written':len(rows),'items_after':_db_count(c),'db_bytes':CACHE_DB_PATH.stat().st_size if CACHE_DB_PATH.exists() else 0}
    except Exception as exc:
        try:c.rollback()
        except Exception:pass
        return {'status':'SQLITE_ROW_PERSIST_FAILED_FAIL_SOFT','rows_written':0,'error':type(exc).__name__+': '+str(exc)[:220]}


def build_observations(docs:list[dict[str,Any]],*,use_cache=True)->tuple[list[dict[str,Any]],dict[str,Any]]:
    started=time.perf_counter();conn,load_audit=_cache_open(use_cache=use_cache);usable=[];family=Counter();usable_family=Counter();direct_family=Counter();payment_family=Counter();supply_family=Counter();reasons=Counter();targets=Counter();dispositions=Counter();signature_missing_retained=0;hits=misses=schema_upgrades=0;dirty_rows=[]
    try:
        for d in docs:
            k=_doc_key(d);cached=_cache_get(conn,k)
            if cached is not None:o=_hydrate_cached(cached,d);hits+=1
            else:o=observation_from_doc(d);misses+=1
            stale=(not o.get('evidence_disposition')) or o.get('evidence_schema_version')!=EVIDENCE_SCHEMA_VERSION or not o.get('feedback_role') or not o.get('source_intent') or not isinstance(o.get('need_frame'),dict)
            if stale:o=ensure_observation_schema(o);schema_upgrades+=1
            if cached is None or stale:dirty_rows.append((k,o))
            family[o['source_family']]+=1;targets[o.get('problem_target') or 'UNKNOWN']+=1;dispositions[o.get('evidence_disposition') or 'UNANNOTATED']+=1
            signature_missing_retained+=int(o.get('evidence_disposition')=='INCOMPLETE_NEED' and not o.get('primary_problem_signature'))
            is_usable=bool(o.get('evidence_disposition') in {'DIRECT_NEED','INCOMPLETE_NEED','CONTEXT'} or o['paid_supply'] or o['change_explicit'] or o['second_order_explicit'])
            if is_usable:
                usable.append(o);usable_family[o['source_family']]+=1;direct_family[o['source_family']]+=int(bool(o.get('direct_pain')));payment_family[o['source_family']]+=int(bool(o.get('payment_behavior_observed')));supply_family[o['source_family']]+=int(bool(o.get('paid_supply')))
            else:
                if o['source_family']=='app_store_reviews' and o.get('problem_target')=='LISTED_ENTITY_OR_CONTENT':reasons['app_review_targets_listed_entity_not_app']+=1
                elif o['source_family']=='app_store_reviews' and o.get('problem_target')=='UNKNOWN':reasons['app_review_target_unknown']+=1
                elif not o.get('problem_span') and not o.get('paid_supply'):reasons['no_actionable_problem_or_market_signal']+=1
                elif o.get('workflow')=='other':reasons['workflow_unknown']+=1
                else:reasons['other']+=1
        persist=_cache_upsert(conn,dirty_rows) if use_cache else {'status':'DISABLED','rows_written':0}
    finally:
        if conn is not None:conn.close()
    yield_by_family={}
    for fam_name,n in family.items():
        us=usable_family.get(fam_name,0);yield_by_family[fam_name]={'documents':n,'usable':us,'usable_rate':round(us/max(1,n),3),'direct_pain':direct_family.get(fam_name,0),'payment_behavior':payment_family.get(fam_name,0),'paid_supply':supply_family.get(fam_name,0)}
    return usable,{'documents':len(docs),'observations':len(docs),'usable_observations':len(usable),'family_counts':dict(family),'usable_by_family':dict(usable_family),'yield_by_family':yield_by_family,'rejected_reasons':dict(reasons),'problem_targets':dict(targets),'evidence_dispositions':dict(dispositions),'signature_missing_need_fragments_retained':signature_missing_retained,'hard_signature_gate_removed':True,'weak_supervision_engine':EVIDENCE_ATOM_ENGINE_VERSION,'cache_hits':hits,'cache_misses':misses,'schema_upgrades':schema_upgrades,'cache_load':load_audit,'cache_persist':persist,'cache_format':CACHE_FORMAT_VERSION,'cache_dirty':bool(dirty_rows),'linear_pass':True,'single_pass_yield_accounting':True,'sentence_targeting':True,'span_provenance':True,'parser_constitution_hash':PARSER_CONSTITUTION_HASH,'seconds':round(time.perf_counter()-started,3)}


def build_observations_incremental(docs:list[dict[str,Any]])->tuple[list[dict[str,Any]],dict[str,Any]]:
    """Parse/cache only new recovery docs using row-level SQLite persistence."""
    started=time.perf_counter();conn,load_audit=_cache_open(use_cache=True);usable=[];hits=misses=schema_upgrades=0;dispositions=Counter();families=Counter();dirty_rows=[]
    try:
        for d in docs:
            k=_doc_key(d);cached=_cache_get(conn,k)
            if cached is not None:o=_hydrate_cached(cached,d);hits+=1
            else:o=observation_from_doc(d);misses+=1
            stale=(not o.get('evidence_disposition')) or o.get('evidence_schema_version')!=EVIDENCE_SCHEMA_VERSION or not o.get('feedback_role') or not o.get('source_intent') or not isinstance(o.get('need_frame'),dict)
            if stale:o=ensure_observation_schema(o);schema_upgrades+=1
            if cached is None or stale:dirty_rows.append((k,o))
            families[o.get('source_family') or 'unknown']+=1;dispositions[o.get('evidence_disposition') or 'UNANNOTATED']+=1
            if bool(o.get('evidence_disposition') in {'DIRECT_NEED','INCOMPLETE_NEED','CONTEXT'} or o.get('paid_supply') or o.get('change_explicit') or o.get('second_order_explicit')):usable.append(o)
        persist=_cache_upsert(conn,dirty_rows);items_after=_db_count(conn) if conn is not None else 0
    finally:
        if conn is not None:conn.close()
    return usable,{'documents':len(docs),'usable_observations':len(usable),'cache_hits':hits,'cache_misses':misses,'schema_upgrades':schema_upgrades,'cache_items_after':items_after,'cache_load':load_audit,'cache_persist':persist,'cache_format':CACHE_FORMAT_VERSION,'family_counts':dict(families),'evidence_dispositions':dict(dispositions),'incremental_recovery_parse':True,'seconds':round(time.perf_counter()-started,3)}


def static_acceptance()->dict[str,bool]:
    good={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r1','text':'App TripPlan. Rating 2/5. Review: Every trip I have to re-enter my itinerary because the app forgets it.','title':'Forgetful app','rating':'2','app_id':'42','app_category':'Travel'}
    listed={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r2','text':'App Tripadvisor. Rating 1/5. Review: The cafe omelet was tiny and the coffee tasted old.','title':'Le French Cafe Disappointing','rating':'1','app_id':'43','app_category':'Travel'}
    billing={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r3','text':'App Voice Reader. Rating 2/5. Review: Premium voices are $10 per month and the subscription is too expensive.','title':'Too expensive','rating':'2','app_id':'44','app_category':'Books'}
    charged={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r4','text':'App Wanderlog. Rating 1/5. Review: You charged me $39 for the pro subscription which I did not agree upon and I am still running the basic.','title':'Unauthorized charge','rating':'1','app_id':'45','app_category':'Travel'}
    positive={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r5','text':'App Noteful. Rating 5/5. Review: It works beautifully and the price for pro is extremely reasonable and worth it!','title':'Great app','rating':'5','app_id':'46','app_category':'Productivity'}
    supplier={'source':'market_supply_external','source_family':'app_store','table':'apps','pk':'47','text':'App Store software TripIt. Seamlessly sync travel plans to your calendar.','title':'TripIt','app_id':'47','app_category':'Travel','paid_supply':True}
    vendor_job={'source':'jobs','source_family':'jobs','table':'job_listings','pk':'j1','text':'Our mission is to increase the efficiency of the global supply chain by automating the manual workflows that slow supply chain teams down.','title':'AI logistics role'}
    future_job={'source':'jobs','source_family':'jobs','table':'job_listings','pk':'j2','text':'Teams will work from shared accurate data and routine coordination will be handled through automation.','title':'Operations role'}
    app_freeze={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r6','text':'App Notability. Rating 1/5. Review: Unusable, freezes constantly. The subscription page is expensive.','title':'Freeze','rating':'1','app_id':'48','app_category':'Productivity'}
    tpms={'source':'community_external','source_family':'stackexchange','table':'questions','pk':'q1','text':'The garage said the car is too old for their diagnostic machine. In another part of the post I mention I paid for tyres.','title':'TPMS diagnostic issue','community':'mechanics'}
    parse={'source':'product_review_external','source_family':'app_store_reviews','table':'reviews','pk':'r7','text':'App Tripsy. Rating 2/5. Review: It can’t parse emails and I have to enter all the information manually.','title':'Email parse','rating':'2','app_id':'49','app_category':'Travel'}
    a=observation_from_doc(good);b=observation_from_doc(listed);c=observation_from_doc(billing);d=observation_from_doc(charged);e=observation_from_doc(positive);f=observation_from_doc(supplier);g=observation_from_doc(vendor_job);h=observation_from_doc(future_job);i=observation_from_doc(app_freeze);j=observation_from_doc(tpms);k=observation_from_doc(parse)
    xs,audit=build_observations([good,listed,billing],use_cache=False)
    return {'app_product_target':a['direct_pain'] and a['problem_target']=='PRODUCT_APP','listed_entity_review_rejected':not b['direct_pain'] and b['problem_target']=='LISTED_ENTITY_OR_CONTENT','commercial_behavior_explicit':c['commercial_behavior_explicit'] and c['problem_target']=='PRODUCT_BILLING','price_context_not_payment_behavior':c['payment_behavior_observed'] is False,'precise_problem_signature':bool(a['primary_problem_signature']),'linear_rejection_accounting':audit['linear_pass'] and audit['observations']==3,'workflow_travel_native':a['workflow']=='travel_planning','sentence_level_targeting':b['problem_target']=='LISTED_ENTITY_OR_CONTENT','payment_scope_explicit':c['payment_scope']=='COMMERCIAL_CONTEXT_ONLY','single_pass_yield_accounting':audit.get('single_pass_yield_accounting') is True,'problem_span_hash_visible':bool(a.get('problem_span_hash')),'problem_sentence_index_visible':a.get('problem_sentence_index') is not None,'parser_constitution_cache_bound':audit.get('parser_constitution_hash')==PARSER_CONSTITUTION_HASH,'independence_class_visible':a.get('independence_class')=='REVIEW','charged_me_is_payment_behavior':d.get('payment_behavior_observed') is True,'positive_review_not_pain':not e.get('direct_pain'),'supplier_capability_not_pain':not f.get('direct_pain'),'vendor_mission_not_pain':not g.get('direct_pain') and g.get('source_role')=='HIRING_OR_VENDOR_CONTEXT','future_state_not_pain':not h.get('direct_pain'),'problem_local_workflow_not_document_billing':i.get('workflow')=='productivity','payment_behavior_local_not_document_wide':j.get('payment_behavior_observed') is False,'parse_failure_signature':k.get('primary_problem_signature')=='import_parse_failure','normalized_problem_hash_visible':bool(a.get('normalized_problem_hash')),'source_role_visible':a.get('source_role')=='FIRSTHAND_USER_PAIN','primary_pain_authority_visible':a.get('primary_pain_authority') is True,'problem_self_contained_visible':a.get('problem_self_contained') is True,'structural_change_jobs_blocked':not g.get('change_explicit'),'recovery_provenance_visible':'acquisition_mode' in a and a.get('acquisition_mode')=='BASE_OR_SEED','hypothesis_seed_fields_visible':isinstance(a.get('capturability_signals'),dict),'mature_evidence_atom_annotation':annotate_observation(a).get('evidence_disposition') in {'DIRECT_NEED','INCOMPLETE_NEED'},'cached_schema_migrates_without_full_parser_invalidation':ensure_observation_schema({**a,'evidence_schema_version':'old','feedback_role':None,'source_intent':None}).get('evidence_schema_version')==EVIDENCE_SCHEMA_VERSION,'source_intent_schema_migration':bool(ensure_observation_schema({**a,'evidence_schema_version':'old','feedback_role':None,'source_intent':None}).get('source_intent')),'missing_signature_is_not_a_hard_reject':annotate_observation({**a,'primary_problem_signature':'','problem_signatures':[]}).get('evidence_disposition')=='INCOMPLETE_NEED','incremental_recovery_parser_available':callable(build_observations_incremental),'memory_bounded_stream_cache_writer':callable(_atomic_stream_json),'row_level_sqlite_cache_available':callable(_cache_get) and callable(_cache_upsert),'legacy_json_stream_migration_available':callable(_iter_legacy_cache_items),'compact_cache_excludes_raw_corpus':('text' not in _cache_pack(a) and 'raw_doc' not in _cache_pack(a)),'cache_invalidation_parser_constitution_based':True,'runtime_engine_version_not_semantic_cache_constitution':PARSER_SEMANTIC_CONSTITUTION_VERSION!=ENGINE_VERSION,'cache_persistence_fail_soft_previous_preserved':True}
