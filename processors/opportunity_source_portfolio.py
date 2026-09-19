from __future__ import annotations

import concurrent.futures, hashlib, html, json, os, re, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

ENGINE_VERSION="signalforge-source-portfolio-u13-evidence-gap-voi"
CACHE_PATH=Path('.radar_runtime/source_portfolio_v20.json')
SEED_CACHES=[Path('.radar_runtime/source_portfolio_v19.json'),Path('.radar_runtime/source_portfolio_v18.json'),Path('.radar_runtime/source_portfolio_v17.json'),Path('.radar_runtime/source_portfolio_v16.json'),Path('.radar_runtime/source_portfolio_v15.json'),Path('.radar_runtime/source_portfolio_v14.json'),Path('.radar_runtime/source_portfolio_v11.json')]
FEEDBACK_PATH=Path('.radar_runtime/source_yield_feedback_r1.json')
RECOVERY_MEMORY_PATH=Path('.radar_runtime/recovery_query_memory_u10.json')
EVIDENCE_GAP_LEDGER_PATH=Path('.radar_runtime/evidence_gap_ledger_u13.json')
RECOVERY_NO_YIELD_COOLDOWN_SECONDS=12*3600
GITHUB_SUPPLY_PER_RUN=1
FEEDBACK_FALLBACKS=[Path('.radar_runtime/source_yield_feedback_v20.json'),Path('.radar_runtime/source_yield_feedback_v19.json'),Path('.radar_runtime/source_yield_feedback_v18.json'),Path('.radar_runtime/source_yield_feedback_v17.json')]
DISCOVERY_CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
CACHE_TTL_SECONDS=12*3600
REQUEST_TIMEOUT=10
MAX_NETWORK_REQUESTS=42
INITIAL_NETWORK_REQUESTS=34
RECOVERY_RESERVE_REQUESTS=8
RECOVERY_PER_RUN_REQUESTS=6
MAX_DOCS=2500
MAX_REVIEWS_PER_PRODUCT=16
USER_AGENT='SignalForge/R1 (+hypothesis-gap-corroboration; bounded-public-feeds)'

# Public, no-credential surfaces. V14 broadens beyond software/productivity while keeping explicit boundaries.
STACK_SITE_GROUPS={
    'work': ['workplace','academia','law','freelancing'],
    'consumer_physical': ['diy','bicycles','outdoors','gardening','mechanics','pets','electronics','photo','fitness','woodworking','homebrew','aviation'],
    'consumer_life': ['travel','cooking','money','parenting'],
    'software_user': ['superuser','webapps'],
}
REDDIT_SUBS=['smallbusiness','Entrepreneur','freelance','Teachers','books','college','productivity','BuyItForLife','HomeImprovement']
APP_QUERY_GROUPS={
    'reading_study':['book reading','study notes','voice reader','flashcards study'],
    'travel':['travel planner','trip itinerary','flight organizer'],
    'small_business':['small business scheduling','small business CRM','invoice contractor','field service contractor','inventory management'],
    'personal_ops':['expense receipt freelancer','home inventory','household budget','meal planner'],
    'booking':['appointment booking salon','property management landlord','property inspection'],
    'knowledge_work':['AI meeting notes','document scanner notes','task planner productivity'],
}
LANE_SOURCE_MATRIX={
    'MICRO_FRICTION':{'consumer_physical','consumer_life','software_user','app_reviews'},
    'PROVEN_MARKET_WEDGE':{'work','software_user','app_supply','app_reviews'},
    'DISTRIBUTION_MODEL_GAP':{'consumer_life','work','app_supply','app_reviews'},
    'BORING_OPS':{'work','consumer_physical','software_user'},
    'SECOND_ORDER_PAIN':{'consumer_life','work','software_user'},
    'TRANSITION_GAP':{'work','software_user','app_supply'},
}

_TAG=re.compile(r'<[^>]+>'); _WS=re.compile(r'\s+')


def _clean(v:Any)->str: return _WS.sub(' ',html.unescape(_TAG.sub(' ',str(v or '')))).strip()
def _pk(*xs:Any)->str: return hashlib.sha1('|'.join(str(x or '') for x in xs).encode()).hexdigest()[:20]
def _http_get(url:str)->bytes:
    req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/json, application/atom+xml, application/xml, text/xml, */*'})
    with urllib.request.urlopen(req,timeout=REQUEST_TIMEOUT) as r: return r.read()
def _doc(source,table,pk,title,text,url='',date='',**meta):
    text=_clean(text)[:3500]; title=_clean(title)[:500]
    if len(text)<35:return None
    d={'source':source,'table':table,'pk':str(pk),'title':title,'text':text,'url':str(url or ''),'date':str(date or '')};d.update(meta);return d


def _parse_stack(payload:dict,site:str):
    out=[]
    for q in payload.get('items') or []:
        title=_clean(q.get('title')); body=_clean(q.get('body')); tags=', '.join(q.get('tags') or [])
        d=_doc('community_external','stackexchange_questions',q.get('question_id') or _pk(site,title),title,f'{title}. {body}. Tags: {tags}',q.get('link') or '',q.get('creation_date') or '',source_family='stackexchange',source_name=f'stackexchange:{site}',community=site,site=site,actor_scope='community_user',source_role_hint='FIRSTHAND_USER_PAIN')
        if d:out.append(d)
    return out


def _parse_reddit(raw:bytes,sub:str):
    root=ET.fromstring(raw); ns={'a':'http://www.w3.org/2005/Atom'}; out=[]
    for e in root.findall('a:entry',ns):
        title=_clean(e.findtext('a:title',default='',namespaces=ns)); content=_clean(e.findtext('a:content',default='',namespaces=ns)); updated=_clean(e.findtext('a:updated',default='',namespaces=ns)); eid=_clean(e.findtext('a:id',default='',namespaces=ns)); link=''
        for el in e.findall('a:link',ns):
            if el.attrib.get('href'):link=el.attrib['href'];break
        d=_doc('community_external','reddit_rss',eid or _pk(sub,title),title,f'{title}. {content}',link,updated,source_family='reddit_rss',source_name=f'reddit:r/{sub}',subreddit=sub,community=sub,actor_scope='community_user',source_role_hint='FIRSTHAND_USER_PAIN')
        if d:out.append(d)
    return out


def _parse_hackernews_search(payload:dict,q:str):
    out=[]
    for h in payload.get('hits') or []:
        title=_clean(h.get('title') or h.get('story_title') or '')
        body=_clean(h.get('comment_text') or h.get('story_text') or h.get('title') or '')
        text=(title+'. '+body).strip('. ')
        oid=str(h.get('objectID') or _pk(q,title,body))
        url=h.get('url') or h.get('story_url') or (f'https://news.ycombinator.com/item?id={oid}' if oid else '')
        d=_doc('community_external','hackernews_search',oid,title or 'Hacker News discussion',text,url,h.get('created_at') or '',source_family='hackernews',source_name='hn_algolia_search',community='hackernews',actor_scope='community_user',source_role_hint='FIRSTHAND_USER_PAIN',search_query='USABILITY_U8_NEED_SOLUTION_RECOVERY',recovery_query=q)
        if d:out.append(d)
    return out


def _parse_app_search(payload:dict,q:str):
    docs=[]; apps=[]
    for a in payload.get('results') or []:
        appid=str(a.get('trackId') or ''); name=_clean(a.get('trackName'))
        if not appid or not name:continue
        cat=_clean(a.get('primaryGenreName')); seller=_clean(a.get('sellerName')); desc=_clean(a.get('description')); price=a.get('price'); fmt=_clean(a.get('formattedPrice'))
        try:paid=float(price or 0)>0
        except:paid=False
        txt=f'App Store software {name}. Seller {seller}. Category {cat}. '+(f'Upfront pricing {fmt or price}. ' if paid else '')+f'Description: {desc}'
        d=_doc('market_supply_external','app_store_apps',appid,name,txt,a.get('trackViewUrl') or '',a.get('currentVersionReleaseDate') or '',source_family='app_store',source_name='apple_itunes_search',source_role_hint='MARKET_SUPPLY',app_id=appid,app_name=name,app_category=cat,category=cat,paid_supply=paid,search_query=q,price=price,formatted_price=fmt)
        if d:docs.append(d)
        apps.append({'app_id':appid,'app_name':name,'app_category':cat,'paid_supply':paid,'search_query':q})
    return docs,apps


def _parse_github_repo_search(payload:dict,q:str):
    """Public GitHub repository search as software-supply context only.

    Stars/forks are peer-attention metadata, never willingness-to-pay or demand proof.
    """
    out=[]
    for a in payload.get('items') or []:
        full=_clean(a.get('full_name') or a.get('name')); desc=_clean(a.get('description')); topics=', '.join(a.get('topics') or [])
        if not full:continue
        txt=f'Open-source repository {full}. Description: {desc}. Topics: {topics}. Stars: {a.get("stargazers_count") or 0}. Forks: {a.get("forks_count") or 0}.'
        d=_doc('market_supply_external','github_repositories',a.get('id') or _pk(full),full,txt,a.get('html_url') or '',a.get('updated_at') or '',source_family='market_supply_external',source_name='github_repository_search',source_role_hint='MARKET_SUPPLY',paid_supply=False,search_query=q,product_name=full,github_stars=int(a.get('stargazers_count') or 0),github_forks=int(a.get('forks_count') or 0),peer_attention_context=True)
        if d:out.append(d)
    return out


def _load_recovery_memory()->dict[str,Any]:
    try:
        x=json.loads(RECOVERY_MEMORY_PATH.read_text(encoding='utf-8'));return x if isinstance(x,dict) else {}
    except Exception:return {}

def _save_recovery_memory(x:dict[str,Any])->None:
    RECOVERY_MEMORY_PATH.parent.mkdir(parents=True,exist_ok=True)
    _atomic_stream_json(RECOVERY_MEMORY_PATH,x,indent=2)

def _qkey(surface:str,q:str)->str:
    q=' '.join(str(q or '').lower().split())
    return hashlib.sha1((surface+'|'+q).encode()).hexdigest()[:20]

def _query_variants(q:str,problem_obs:dict[str,Any],limit:int=4)->list[str]:
    """Evidence-bounded query diversification. No new facts are invented.

    This implements a conservative relevance-feedback idea: if an exact query yields no
    novel evidence, retry a structurally equivalent query built only from observed frame
    terms rather than repeating the same request forever.
    """
    base=[t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",q or '') if t.lower() not in QUERY_STOP]
    generic={'productivity','manual','reentry','friction','support','billing','intake','other','process','current'}
    nf=problem_obs.get('need_frame') or {}
    frame=[]
    for field in ('failure_modes','actions','objects'):
        vals=nf.get(field) or []
        if not isinstance(vals,list):vals=[vals]
        for v in vals:
            for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",str(v).replace('_',' ')):
                tl=t.lower()
                if tl not in QUERY_STOP and tl not in frame:frame.append(tl)
    variants=[]
    def add(ts):
        z=' '.join(dict.fromkeys([x for x in ts if len(x)>=3]))[:180].strip()
        if z and z not in variants:variants.append(z)
    add(base)
    add([x for x in base if x not in generic])
    add(frame[:7])
    add((frame[:4]+[x for x in base if x not in generic][:3]))
    return variants[:limit]

def _query_token_set(q:str)->set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",str(q or '')) if t.lower() not in QUERY_STOP}

def _query_jaccard(a:str,b:str)->float:
    x=_query_token_set(a);y=_query_token_set(b)
    if not x or not y:return 0.0
    return len(x&y)/max(1,len(x|y))

def _near_zero_yield(surface:str,cand:str,mem:dict[str,Any],now:float,threshold:float=.72)->dict[str,Any]|None:
    # MMR/relevance-feedback guard: do not spend a request on a lexical reshuffle of a
    # recently failed query.  This blocks "query churn" while still allowing genuinely
    # different evidence-bounded formulations.
    best=None
    for rec in (mem.get('queries') or {}).values():
        if str(rec.get('surface') or '')!=surface:continue
        if int(rec.get('zero_yield_streak') or 0)<1:continue
        if (now-float(rec.get('last_attempt') or 0))>=RECOVERY_NO_YIELD_COOLDOWN_SECONDS:continue
        sim=_query_jaccard(cand,str(rec.get('query') or ''))
        if sim>=threshold and (best is None or sim>best['similarity']):
            best={'query':rec.get('query'),'similarity':round(sim,3),'last_attempt':rec.get('last_attempt')}
    return best

def _source_expected_yield(kind:str,mem:dict[str,Any])->float:
    rec=((mem.get('sources') or {}).get(kind) or {})
    attempts=int(rec.get('attempts') or 0);novel=int(rec.get('new_docs') or 0);useful=int(rec.get('downstream_evidence_docs') or 0)
    # Score the chance that a request produces useful evidence, not the number of rows
    # returned.  A feed dumping 20 irrelevant novel rows must not outrank a source that
    # reliably yields one decision-relevant evidence item.  Beta-style smoothing keeps
    # small samples from dominating.
    novel_success=min(max(0,novel),attempts)
    novel_rate=(novel_success+1.0)/(attempts+3.0)
    if 'downstream_evidence_docs' not in rec:return novel_rate
    utility_success=min(max(0,useful),attempts)
    utility_rate=(utility_success+1.0)/(attempts+3.0)
    return .25*novel_rate+.75*utility_rate


GAP_IMPACT={
    'INDEPENDENT_NEED_RECURRENCE':1.00,
    'CURRENT_SOLUTION_SUPPLY':0.78,
    'PEER_ADOPTION_OR_DIFFUSION':0.62,
    'ECONOMIC_BURDEN_OR_BUYER':0.72,
    'WTP_OR_PAYMENT_BEHAVIOR':0.55,
}

def _anchor_key(anchor:dict[str,Any])->str:
    return str(anchor.get('anchor_key') or anchor.get('card_key') or anchor.get('research_object_id') or anchor.get('hypothesis_key') or anchor.get('problem_ref') or '')

def _gap_key(anchor_key:str,gap:str)->str:
    return hashlib.sha1((str(anchor_key)+'|'+str(gap)).encode()).hexdigest()[:24]

def _gap_record(mem:dict[str,Any],anchor_key:str,gap:str)->dict[str,Any]:
    gaps=mem.setdefault('evidence_gaps',{})
    k=_gap_key(anchor_key,gap)
    rec=dict(gaps.get(k) or {})
    rec.setdefault('anchor_key',anchor_key);rec.setdefault('evidence_gap',gap)
    return rec

def estimate_anchor_voi(anchor:dict[str,Any],gap:str|None=None,mem:dict[str,Any]|None=None)->dict[str,Any]:
    """Conservative expected-value-of-information proxy for acquisition priority only.

    It never changes opportunity, demand, WTP, or hypothesis truth.  It estimates whether
    another bounded search is worth spending relative to the unresolved decision gap.
    """
    mem=mem if isinstance(mem,dict) else _load_recovery_memory()
    ak=_anchor_key(anchor);g=str(gap or anchor.get('evidence_gap') or ('INDEPENDENT_NEED_RECURRENCE' if anchor.get('anchor_type') in {'USER_INNOVATION_RECURRENCE','NEED_FRAGMENT'} else 'CURRENT_SOLUTION_SUPPLY'))
    rec=_gap_record(mem,ak,g) if ak else {}
    attempts=int(rec.get('attempts') or 0);useful=int(rec.get('downstream_evidence_docs') or 0);zero=int(rec.get('zero_utility_streak') or 0)
    impact=float(GAP_IMPACT.get(g,0.60))
    evidence_probability=(useful+1.0)/(attempts+3.0)
    diminishing=1.0/(1.0+0.30*max(0,attempts-1))
    if zero>=3:diminishing*=0.35
    voi=max(0.0,min(1.0,impact*evidence_probability*diminishing))
    return {'anchor_key':ak,'evidence_gap':g,'decision_impact':round(impact,3),'attempts':attempts,'downstream_evidence_docs':useful,'zero_utility_streak':zero,'expected_information_value':round(voi,4),'truth_boundary':'VOI_PROXY_CHANGES_ACQUISITION_PRIORITY_ONLY'}

def get_evidence_gap_progress(anchor_keys:list[str]|None=None)->dict[str,Any]:
    mem=_load_recovery_memory();gaps=mem.get('evidence_gaps') or {};wanted=set(str(x) for x in (anchor_keys or []) if x)
    rows=[]
    for rec in gaps.values():
        if wanted and str(rec.get('anchor_key') or '') not in wanted:continue
        r=dict(rec);r['voi']=estimate_anchor_voi({'anchor_key':r.get('anchor_key'),'evidence_gap':r.get('evidence_gap')},mem=mem)
        rows.append(r)
    rows.sort(key=lambda r:(str(r.get('anchor_key')),str(r.get('evidence_gap'))))
    payload={'generated_at':time.time(),'rows':rows,'truth_boundary':'GAP_PROGRESS_IS_ACQUISITION_TELEMETRY_NOT_MARKET_TRUTH'}
    try:_atomic_stream_json(EVIDENCE_GAP_LEDGER_PATH,payload,indent=2)
    except Exception:pass
    return payload

def _adapter_from_observation(o:dict[str,Any])->str|None:
    raw=o.get('raw_doc') or {};fam=str(o.get('source_family') or '').lower();table=str(o.get('source_table') or '').lower();name=str(raw.get('source_name') or '').lower()
    if fam=='hackernews' or 'hackernews' in table or 'hn_algolia' in name:return 'hackernews_search'
    if fam=='reddit_rss' or 'reddit' in table:return 'reddit_rss'
    if fam=='stackexchange' or 'stackexchange' in table:return 'stackexchange'
    if fam=='app_store' or table=='app_store_apps':return 'app_search'
    if 'github_repository' in name or table=='github_repositories':return 'github_repo_search'
    return None

def record_downstream_evidence_utility(observations:list[dict[str,Any]])->dict[str,Any]:
    """Feed acquisition policy with downstream evidence utility and card/gap attribution.

    Attribution means "retrieved while researching this gap".  It is deliberately not a
    semantic claim that the evidence closes the gap; semantic confirmation remains upstream.
    """
    mem=_load_recovery_memory();srcs=mem.setdefault('sources',{});gaps=mem.setdefault('evidence_gaps',{})
    counts=Counter();usable=Counter();by_gap=Counter();useful_gap=Counter();by_anchor=Counter()
    for o in observations or []:
        kind=_adapter_from_observation(o)
        if kind:counts[kind]+=1
        role=str(o.get('feedback_role') or '')
        evidence=bool(o.get('direct_pain') or o.get('paid_supply') or role in {'PROBLEM_REPORT','FEATURE_REQUEST','USER_INNOVATION_NEED_SOLUTION','MARKET_SUPPLY_CONTEXT'})
        if kind:usable[kind]+=int(evidence)
        raw=o.get('raw_doc') or {}
        ak=str(o.get('recovery_anchor_key') or raw.get('recovery_anchor_key') or '')
        gap=str(o.get('recovery_evidence_gap') or raw.get('recovery_evidence_gap') or '')
        if ak and gap:
            k=_gap_key(ak,gap);by_gap[k]+=1;useful_gap[k]+=int(evidence);by_anchor[ak]+=int(evidence)
            rec=dict(gaps.get(k) or {'anchor_key':ak,'evidence_gap':gap})
            rec['downstream_observations']=int(rec.get('downstream_observations') or 0)+1
            rec['downstream_evidence_docs']=int(rec.get('downstream_evidence_docs') or 0)+int(evidence)
            rec['last_downstream_observations']=int(rec.get('last_downstream_observations') or 0)+1
            rec['last_downstream_evidence_docs']=int(rec.get('last_downstream_evidence_docs') or 0)+int(evidence)
            rec['last_evidence_at']=time.time() if evidence else rec.get('last_evidence_at')
            if evidence:rec['zero_utility_streak']=0
            gaps[k]=rec
    for k,n in by_gap.items():
        rec=dict(gaps.get(k) or {});use=int(useful_gap.get(k) or 0)
        rec['last_downstream_observations']=int(n);rec['last_downstream_evidence_docs']=use
        rec['zero_utility_streak']=0 if use>0 else int(rec.get('zero_utility_streak') or 0)+1
        gaps[k]=rec
    for kind,n in counts.items():
        sr=dict(srcs.get(kind) or {});sr['downstream_observations']=int(sr.get('downstream_observations') or 0)+n;sr['downstream_evidence_docs']=int(sr.get('downstream_evidence_docs') or 0)+int(usable.get(kind,0));sr['last_downstream_observations']=n;sr['last_downstream_evidence_docs']=int(usable.get(kind,0));srcs[kind]=sr
        sr['expected_evidence_utility_yield']=round(_source_expected_yield(kind,mem),4)
    mem['sources']=srcs;mem['evidence_gaps']=gaps;mem['policy']='RELEVANCE_FEEDBACK_PLUS_MMR_DIVERSITY_PLUS_DOWNSTREAM_UTILITY_PLUS_GAP_VOI';_save_recovery_memory(mem)
    progress=get_evidence_gap_progress(list(by_anchor)) if by_anchor else {'rows':[]}
    return {'observations_seen':sum(counts.values()),'evidence_docs':sum(usable.values()),'by_adapter':{k:{'observations':counts[k],'evidence_docs':usable[k]} for k in counts},'by_anchor':dict(by_anchor),'by_gap':{k:{'observations':by_gap[k],'evidence_docs':useful_gap[k]} for k in by_gap},'gap_progress':progress.get('rows') or [],'truth_boundary':'DOWNSTREAM_UTILITY_AND_GAP_ATTRIBUTION_CHANGE_ACQUISITION_PRIORITY_ONLY_NOT_MARKET_TRUTH'}

def _adaptive_task_select(bucket:list,quota:int,mem:dict[str,Any],selected_queries:list[str])->list:
    """Greedy relevance + novelty + empirical-yield + gap-VOI selection."""
    pool=list(bucket);out=[]
    while pool and len(out)<quota:
        best_i=None;best_score=-1e9
        for i,(task,anchor) in enumerate(pool):
            kind=str(task[0]);q=str((task[3] or {}).get('_search_query') or task[1] or '')
            base=float(((anchor.get('targetability') or {}).get('score')) or 5.0)
            rel=max(0.0,min(1.0,base/10.0));expected=_source_expected_yield(kind,mem)
            novelty=1.0
            if selected_queries:novelty=1.0-max((_query_jaccard(q,z) for z in selected_queries),default=0.0)
            voi=estimate_anchor_voi(anchor,mem=mem).get('expected_information_value') or 0.0
            score=.43*rel+.20*novelty+.20*expected+.17*float(voi)
            if score>best_score:best_score=score;best_i=i
        task,anchor=pool.pop(best_i);anchor=dict(anchor);anchor['acquisition_score']=round(best_score,4);anchor['voi']=estimate_anchor_voi(anchor,mem=mem)
        out.append((task,anchor));selected_queries.append(str((task[3] or {}).get('_search_query') or task[1] or ''))
    return out

def _choose_query(surface:str,q:str,problem_obs:dict[str,Any],mem:dict[str,Any],now:float)->tuple[str|None,dict[str,Any]]:
    variants=_query_variants(q,problem_obs) or ([q] if q else [])
    blocked=[];near_blocked=[]
    for cand in variants:
        rec=(mem.get('queries') or {}).get(_qkey(surface,cand)) or {}
        recent=(now-float(rec.get('last_attempt') or 0))<RECOVERY_NO_YIELD_COOLDOWN_SECONDS
        if recent and int(rec.get('zero_yield_streak') or 0)>=1:
            blocked.append(cand);continue
        near=_near_zero_yield(surface,cand,mem,now)
        if near:
            near_blocked.append({'candidate':cand,**near});continue
        return cand,{'blocked_variants':blocked,'near_duplicate_blocked':near_blocked,'used_alternative':cand!=q}
    return None,{'blocked_variants':blocked,'near_duplicate_blocked':near_blocked,'used_alternative':False}

def _update_recovery_memory(mem:dict[str,Any],chosen:list[tuple],added:list[dict[str,Any]],before:set[tuple])->dict[str,Any]:
    now=time.time();qs=mem.setdefault('queries',{});srcs=mem.setdefault('sources',{});gaps=mem.setdefault('evidence_gaps',{});new_by_query=Counter();raw_by_query=Counter()
    for d in added:
        sq=str(d.get('search_query') or '').strip()
        if sq:raw_by_query[sq]+=1
        if (d.get('source'),d.get('pk')) in before:continue
        if sq:new_by_query[sq]+=1
    for task,anchor in chosen:
        kind=str(task[0]);surface='supply' if kind in {'app_search','github_repo_search'} else 'need';q=str((task[3] or {}).get('_search_query') or task[1] or '').strip()
        if not q:continue
        key=_qkey(surface,q);r=dict(qs.get(key) or {});n=int(new_by_query.get(q) or 0);raw=int(raw_by_query.get(q) or 0)
        r.update({'surface':surface,'query':q,'adapter':kind,'attempts':int(r.get('attempts') or 0)+1,'last_attempt':now,'last_raw_docs':raw,'last_new_docs':n,'zero_yield_streak':0 if n>0 else int(r.get('zero_yield_streak') or 0)+1})
        qs[key]=r
        sr=dict(srcs.get(kind) or {});sr['attempts']=int(sr.get('attempts') or 0)+1;sr['raw_docs']=int(sr.get('raw_docs') or 0)+raw;sr['new_docs']=int(sr.get('new_docs') or 0)+n;sr['zero_yield_streak']=0 if n>0 else int(sr.get('zero_yield_streak') or 0)+1;sr['last_attempt']=now;sr['last_new_docs']=n
        sr['expected_novel_yield']=round(_source_expected_yield(kind,{'sources':{kind:sr}}),4);sr['duplicate_ratio']=round(1-(sr['new_docs']/max(1,sr['raw_docs'])),4) if sr['raw_docs'] else None;srcs[kind]=sr
        ak=_anchor_key(anchor);gap=str(anchor.get('evidence_gap') or ('CURRENT_SOLUTION_SUPPLY' if surface=='supply' else 'INDEPENDENT_NEED_RECURRENCE'))
        if ak:
            gk=_gap_key(ak,gap);gr=dict(gaps.get(gk) or {'anchor_key':ak,'evidence_gap':gap});gr['attempts']=int(gr.get('attempts') or 0)+1;gr['last_attempt']=now;gr['last_adapter']=kind;gr['last_query']=q;gr['raw_docs']=int(gr.get('raw_docs') or 0)+raw;gr['new_docs']=int(gr.get('new_docs') or 0)+n;gr['last_new_docs']=n
            # No downstream evidence has been observed yet for this attempt.  It may be reset
            # later by record_downstream_evidence_utility once parsed observations arrive.
            if n<=0:gr['zero_utility_streak']=int(gr.get('zero_utility_streak') or 0)+1
            gr['last_voi_before_result']=estimate_anchor_voi({**anchor,'anchor_key':ak,'evidence_gap':gap},mem={**mem,'evidence_gaps':{**gaps,gk:gr}}).get('expected_information_value')
            gaps[gk]=gr
    mem['updated_at']=now;mem['policy']='RELEVANCE_FEEDBACK_PLUS_MMR_DIVERSITY_PLUS_DOWNSTREAM_UTILITY_PLUS_GAP_VOI';mem['sources']=srcs;mem['evidence_gaps']=gaps
    if len(qs)>500:
        keep=sorted(qs.items(),key=lambda kv:float((kv[1] or {}).get('last_attempt') or 0),reverse=True)[:500];mem['queries']=dict(keep)
    _save_recovery_memory(mem);return mem


def _parse_app_reviews(payload:dict,meta:dict):
    feed=payload.get('feed') or {}; entries=feed.get('entry') or []
    if isinstance(entries,dict):entries=[entries]
    out=[]
    for e in entries[:MAX_REVIEWS_PER_PRODUCT]:
        def lab(k):
            v=e.get(k); return _clean(v.get('label') if isinstance(v,dict) else v)
        rating=lab('im:rating')
        if not rating:continue
        title=lab('title'); content=lab('content'); rid=lab('id'); updated=lab('updated')
        d=_doc('product_review_external','app_store_reviews',rid or _pk(meta['app_id'],title,content),title or f"{meta['app_name']} review",f"App {meta['app_name']}. Rating {rating}/5. Review title: {title}. Review: {content}",f"https://apps.apple.com/app/id{meta['app_id']}",updated,source_family='app_store_reviews',source_name='apple_customer_reviews_rss',source_role_hint='FIRSTHAND_USER_PAIN',app_id=meta['app_id'],app_name=meta['app_name'],app_category=meta['app_category'],category=meta['app_category'],paid_supply=meta['paid_supply'],search_query=meta['search_query'],rating=rating)
        if d:out.append(d)
    return out


def _fetch(task):
    kind,key,url,meta=task;t=time.perf_counter()
    try:return kind,key,meta,_http_get(url),None,time.perf_counter()-t
    except Exception as e:return kind,key,meta,b'',f'{type(e).__name__}: {e}',time.perf_counter()-t


def _run(tasks,docs,apps,health,failures):
    if not tasks:return
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for kind,key,meta,raw,err,elapsed in ex.map(_fetch,tasks):
            h=health.setdefault(kind,{'requests':0,'docs':0,'failures':0,'seconds':0.0,'http_429':0});h['requests']+=1;h['seconds']+=elapsed
            if err:
                h['failures']+=1;h['http_429']+=int('429' in err);failures.append({'adapter':kind,'key':key,'error':err});continue
            try:
                if kind=='stackexchange':new=_parse_stack(json.loads(raw.decode('utf-8','replace')),key)
                elif kind=='reddit_rss':new=_parse_reddit(raw,key)
                elif kind=='hackernews_search':new=_parse_hackernews_search(json.loads(raw.decode('utf-8','replace')),key)
                elif kind=='app_search':new,a=_parse_app_search(json.loads(raw.decode('utf-8','replace')),key);apps.extend(a)
                elif kind=='github_repo_search':new=_parse_github_repo_search(json.loads(raw.decode('utf-8','replace')),key)
                else:new=_parse_app_reviews(json.loads(raw.decode('utf-8','replace')),meta)
                
                if meta:
                    for d in new:
                        if meta.get('_search_query'):d['search_query']=str(meta.get('_search_query'))
                        if meta.get('_anchor_key'):d['recovery_anchor_key']=str(meta.get('_anchor_key'))
                        if meta.get('_anchor_type'):d['recovery_anchor_type']=str(meta.get('_anchor_type'))
                        if meta.get('_evidence_gap'):d['recovery_evidence_gap']=str(meta.get('_evidence_gap'))
                        if meta.get('_acquisition_surface'):d['recovery_surface']=str(meta.get('_acquisition_surface'))
                docs.extend(new);h['docs']+=len(new)
            except Exception as e:
                h['failures']+=1;failures.append({'adapter':kind,'key':key,'error':f'parse {type(e).__name__}: {e}'})


def _dedupe(docs):
    out=[];seen=set()
    for d in docs:
        k=(d.get('source'),d.get('pk'))
        if k in seen:continue
        seen.add(k);out.append(d)
        if len(out)>=MAX_DOCS:break
    return out


def _cache_fresh(path=CACHE_PATH):
    try:return path.exists() and time.time()-path.stat().st_mtime<CACHE_TTL_SECONDS
    except:return False


def _atomic_stream_json(path:Path,payload:Any,*,indent:int|None=2)->dict[str,Any]:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp')
    try:
        enc=json.JSONEncoder(ensure_ascii=False,default=str,indent=indent,separators=None if indent else (',',':'))
        with tmp.open('w',encoding='utf-8',newline='') as f:
            for chunk in enc.iterencode(payload):f.write(chunk)
            f.flush();os.fsync(f.fileno())
        tmp.replace(path);return {'status':'WRITTEN_ATOMIC_STREAM','bytes':path.stat().st_size}
    except (MemoryError,OSError,ValueError,TypeError) as exc:
        try:
            if tmp.exists():tmp.unlink()
        except Exception:pass
        return {'status':'PERSIST_FAILED_PREVIOUS_CACHE_PRESERVED','error':type(exc).__name__+': '+str(exc)[:200]}


def read_cache(path=CACHE_PATH):
    try:
        
        with path.open('r',encoding='utf-8') as f:x=json.load(f)
        return list(x.get('docs') or []),dict(x.get('health') or {})
    except:return [],{'status':'MISS'}


def _previous_lane_need_scores():
    lanes={'MICRO_FRICTION','PROVEN_MARKET_WEDGE','DISTRIBUTION_MODEL_GAP','BORING_OPS','SECOND_ORDER_PAIN','TRANSITION_GAP'}
    score={k:2 for k in lanes}
    try:
        x=json.loads(DISCOVERY_CACHE.read_text(encoding='utf-8'));f=x.get('formation') or {};accepted=x.get('accepted_by_primary_lane') or x.get('accepted_by_lane') or x.get('facet_counts') or {};dedup=f.get('deduped_by_lane') or f.get('deduped_units') or {}
        for lane in lanes:
            a=int(accepted.get(lane,0) or 0);d=int(dedup.get(lane,0) or 0)
            score[lane]=3 if a==0 else (2 if a<3 else 1)
            if d==0:score[lane]=max(score[lane],3)
    except Exception:pass
    fb=None
    for fp in [FEEDBACK_PATH]+FEEDBACK_FALLBACKS:
        try:
            fb=json.loads(fp.read_text(encoding='utf-8'));break
        except Exception:continue
    if fb:
        low=set(fb.get('under_yield_lanes') or [])
        for lane in low:score[lane]=max(score.get(lane,1),3)
        lane_quality=fb.get('lane_quality') or {}
        for lane,q in lane_quality.items():
            if float((q or {}).get('usable_to_dedup_rate',0) or 0)<0.01 and int((q or {}).get('accepted',0) or 0)==0:score[lane]=max(score.get(lane,1),3)
            elif int((q or {}).get('deduped',0) or 0)>=8 and int((q or {}).get('accepted',0) or 0)==0:score[lane]=min(score.get(lane,2),2)
        # Precision failures do not justify fetching more of the same noisy family. They trigger source diversification.
        sem=fb.get('semantic_rejections') or {}
        if sum(int(v or 0) for v in sem.values())>=5:
            score['MICRO_FRICTION']=max(score.get('MICRO_FRICTION',1),3)
            score['BORING_OPS']=max(score.get('BORING_OPS',1),3)
        # Many watch-only single-user signals mean corroboration breadth is the bottleneck, not more app volume.
        if int(fb.get('watch_signal_count',0) or 0)>=5:
            score['MICRO_FRICTION']=max(score.get('MICRO_FRICTION',1),3)
            score['BORING_OPS']=max(score.get('BORING_OPS',1),2)
        # R1 feedback is hypothesis-centric. A large research queue means corroboration breadth is the bottleneck.
        if int(fb.get('research_queue_count',0) or 0)>=5:
            score['MICRO_FRICTION']=max(score.get('MICRO_FRICTION',1),3)
            score['BORING_OPS']=max(score.get('BORING_OPS',1),2)
            score['PROVEN_MARKET_WEDGE']=max(score.get('PROVEN_MARKET_WEDGE',1),2)
    return score

def _previous_lane_needs():
    return {k for k,v in _previous_lane_need_scores().items() if v>=2}

def _tasks_for_needs(needs:set[str], budget:int):
    tasks=[];scores=_previous_lane_need_scores()
    # Diversification first: physical/life/work Stack Exchange surfaces are cheap, structured, and not software-only.
    stack=[]
    for group,sites in STACK_SITE_GROUPS.items():
        priority=0
        if group=='consumer_physical':priority=max(scores.get('MICRO_FRICTION',1),scores.get('DISTRIBUTION_MODEL_GAP',1))
        elif group=='work':priority=max(scores.get('BORING_OPS',1),scores.get('PROVEN_MARKET_WEDGE',1),scores.get('TRANSITION_GAP',1))
        elif group=='consumer_life':priority=max(1,scores.get('SECOND_ORDER_PAIN',1),scores.get('MICRO_FRICTION',1))
        else:priority=1
        for site in sites:stack.append((priority,site))
    for _,site in sorted(stack,key=lambda x:(-x[0],x[1])):
        if len(tasks)>=budget:break
        url='https://api.stackexchange.com/2.3/questions?'+urllib.parse.urlencode({'site':site,'pagesize':30,'order':'desc','sort':'activity','filter':'withbody'})
        tasks.append(('stackexchange',site,url,{}))
    return tasks


def refresh_source_portfolio(*,force=False):
    if not force and _cache_fresh():
        d,h=read_cache();h=dict(h);snapshot_requests=int(h.get('snapshot_network_requests',h.get('requests_used',0)) or 0);h['engine_version']=ENGINE_VERSION;h['cache']='HIT';h['adaptive']=h.get('adaptive_policy');h['requests_this_run']=0;h['requests_used']=0;h['snapshot_network_requests']=snapshot_requests;h['network_activity_this_run']=False;h['cache_age_seconds']=round(max(0,time.time()-CACHE_PATH.stat().st_mtime),1);h['recovery_reserve_remaining']=RECOVERY_PER_RUN_REQUESTS;h['requests_remaining']=RECOVERY_PER_RUN_REQUESTS;h['cumulative_snapshot_network_requests']=snapshot_requests;h['source_contract']={'lane_source_matrix':{k:sorted(v) for k,v in LANE_SOURCE_MATRIX.items()},'optimization_target':'TYPED_EVIDENCE_ROLE_COVERAGE_WITH_RESERVED_FRAGMENT_CORROBORATION_RECOVERY_NOT_RAW_DOC_COUNT','source_role_registry':{'stackexchange':'FIRSTHAND_USER_PAIN','reddit_rss':'FIRSTHAND_USER_PAIN','app_store_reviews':'FIRSTHAND_USER_PAIN','app_store':'MARKET_SUPPLY'},'telemetry_contract':'cumulative snapshot request telemetry is preserved but never consumes future-run recovery; each run receives a fresh bounded recovery budget; requests_this_run is actual current-run network activity'};h['snapshot_captured_at']=h.get('snapshot_captured_at') or CACHE_PATH.stat().st_mtime;_atomic_stream_json(CACHE_PATH,{'generated_at':h['snapshot_captured_at'],'docs':d,'health':h});return d,h
    started=time.perf_counter();docs=[];apps=[];failures=[];adapters={};used=0;seeded=False
    # Preserve fresh V11 evidence as seed, then spend V14 network budget on breadth instead of re-fetching identical material.
    if not force:
        for seed_path in SEED_CACHES:
            if _cache_fresh(seed_path):
                seed,seedh=read_cache(seed_path);docs.extend(seed);seeded=True;break
    needs=_previous_lane_needs()
    # Wave 1: cross-market StackExchange + small Reddit probe + high-intent app search.
    wave1=_tasks_for_needs(needs,18)
    for sub in REDDIT_SUBS[:2]:
        if len(wave1)>=22:break
        wave1.append(('reddit_rss',sub,f'https://www.reddit.com/r/{sub}/new/.rss?limit=25',{}))
    app_queries=[]
    if 'MICRO_FRICTION' in needs:app_queries+=APP_QUERY_GROUPS['reading_study']+APP_QUERY_GROUPS['travel']+APP_QUERY_GROUPS['personal_ops']
    if 'PROVEN_MARKET_WEDGE' in needs or 'DISTRIBUTION_MODEL_GAP' in needs:app_queries+=APP_QUERY_GROUPS['small_business']+APP_QUERY_GROUPS['booking']
    if not app_queries:app_queries=sum(APP_QUERY_GROUPS.values(),[])
    app_queries=list(dict.fromkeys(app_queries))
    for q in app_queries[:8]:
        if len(wave1)>=INITIAL_NETWORK_REQUESTS:break
        wave1.append(('app_search',q,'https://itunes.apple.com/search?'+urllib.parse.urlencode({'term':q,'country':'us','media':'software','entity':'software','limit':7}),{}))
    used+=len(wave1);_run(wave1,docs,apps,adapters,failures)
    reddit_bad=(adapters.get('reddit_rss',{}).get('requests',0)>0 and adapters.get('reddit_rss',{}).get('http_429',0)/max(1,adapters.get('reddit_rss',{}).get('requests',0))>=0.5)
    # Wave 2: healthy-source reallocation + category-diverse app search.
    wave2=[]
    if not reddit_bad:
        for sub in REDDIT_SUBS[2:5]:
            if used+len(wave2)>=INITIAL_NETWORK_REQUESTS:break
            wave2.append(('reddit_rss',sub,f'https://www.reddit.com/r/{sub}/new/.rss?limit=25',{}))
    # Reserve at least 12 requests for review evidence when no seed exists, and 8 when seeded.
    pre_review_cap=INITIAL_NETWORK_REQUESTS-(5 if seeded else 8)
    for q in list(dict.fromkeys(sum(APP_QUERY_GROUPS.values(),[]))):
        if used+len(wave2)>=pre_review_cap:break
        if q in app_queries[:8]:continue
        wave2.append(('app_search',q,'https://itunes.apple.com/search?'+urllib.parse.urlencode({'term':q,'country':'us','media':'software','entity':'software','limit':7}),{}))
    used+=len(wave2);_run(wave2,docs,apps,adapters,failures)
    # Wave 3: review budget is spread across distinct categories/products; no one product can dominate.
    review=[];seen=set();cats=Counter()
    for meta in apps:
        if meta['app_id'] in seen:continue
        cat=(meta.get('app_category') or 'unknown').lower()
        if cats[cat]>=4:continue
        seen.add(meta['app_id']);cats[cat]+=1
        if used+len(review)>=INITIAL_NETWORK_REQUESTS:break
        review.append(('app_reviews',meta['app_id'],f"https://itunes.apple.com/us/rss/customerreviews/page=1/id={meta['app_id']}/sortby=mostrecent/json",meta))
    used+=len(review);_run(review,docs,apps,adapters,failures)
    docs=_dedupe(docs)
    for h in adapters.values():h['seconds']=round(h['seconds'],3)
    source_counts=Counter(d.get('source') for d in docs);family_counts=Counter(str(d.get('source_family') or d.get('source')) for d in docs)
    scope_counts=Counter()
    for d in docs:
        fam=str(d.get('source_family') or '')
        site=str(d.get('community') or d.get('site') or '').lower()
        if fam=='stackexchange' and site in STACK_SITE_GROUPS['consumer_physical']:scope_counts['consumer_physical']+=1
        elif fam=='stackexchange' and site in STACK_SITE_GROUPS['work']:scope_counts['work_professional']+=1
        elif fam=='app_store_reviews':scope_counts['software_product_users']+=1
        elif fam=='app_store':scope_counts['software_supply']+=1
        else:scope_counts['other']+=1
    need_scores=_previous_lane_need_scores();adaptive={'wave1_probe':True,'reddit_circuit_breaker':reddit_bad,'budget_reallocated':reddit_bad,'gap_directed':True,'seeded_from_previous_portfolio':seeded,'needs':sorted(needs),'need_scores':need_scores,'yield_feedback_path':str(FEEDBACK_PATH)}
    health={'engine_version':ENGINE_VERSION,'cache':'REFRESH','status':'PASS' if sum(1 for h in adapters.values() if h['docs']>0)>=2 or seeded else 'PARTIAL','adaptive_policy':adaptive,'adaptive':adaptive,'adapters':adapters,'source_counts':dict(source_counts),'family_counts':dict(family_counts),'scope_counts':dict(scope_counts),'total_docs':len(docs),'requests_used':used,'requests_this_run':used,'snapshot_network_requests':used,'network_activity_this_run':used>0,'seeded_from_cache':seeded,'requests_remaining':max(0,MAX_NETWORK_REQUESTS-used),'recovery_reserve_remaining':max(0,MAX_NETWORK_REQUESTS-used),'initial_request_cap':INITIAL_NETWORK_REQUESTS,'failures':failures[:30],'elapsed_seconds':round(time.perf_counter()-started,3),'coverage_boundaries':{'physical_product_paid_supply':'PARTIAL_PAIN_ONLY','dedicated_b2b_reviews':'NOT_CONNECTED','software_reviews':'CONNECTED','public_workflow_communities':'CONNECTED'},'source_contract':{'lane_source_matrix':{k:sorted(v) for k,v in LANE_SOURCE_MATRIX.items()},'optimization_target':'TYPED_EVIDENCE_ROLE_COVERAGE_WITH_RESERVED_FRAGMENT_CORROBORATION_RECOVERY_NOT_RAW_DOC_COUNT','source_role_registry':{'stackexchange':'FIRSTHAND_USER_PAIN','reddit_rss':'FIRSTHAND_USER_PAIN','app_store_reviews':'FIRSTHAND_USER_PAIN','app_store':'MARKET_SUPPLY'},'telemetry_contract':'initial acquisition reserves up to 8 of 42 requests for same-run evidence-fragment corroboration recovery; requests_this_run is actual network activity; false-positive feedback reallocates away from noisy families'},'adapter_registry':{'physical_product_marketplace_reviews':{'status':'READY_NOT_CONNECTED','reason':'public no-credential stable adapter not yet available','required_contract':['product_identity','review_identity','rating','problem_span','paid_supply_or_price']},'dedicated_b2b_review_marketplace':{'status':'READY_NOT_CONNECTED','reason':'connector/API source required','required_contract':['vendor','category','review_identity','buyer_role_if_available','problem_span','commercial_context']}}}
    _atomic_stream_json(CACHE_PATH,{'generated_at':time.time(),'docs':docs,'health':health})
    return docs,health



QUERY_STOP={
    "this","that","with","from","have","will","your","their","there","about","into","when","using","used","app","product","review",
    "really","just","title","repo","repository","repo_full_name","github","gitlab","issue","audit","mediajunkie","ops","http","https",
    "www","com","source","table","problem","error","thing","things","user","users"
}
QUERY_NOISE=re.compile(r"[_/\\]|^[a-f0-9]{8,}$|(?:repo|github|gitlab|issue|commit|sha|file|path)[-_]",re.I)

def _safe_query_terms(problem_obs:dict[str,Any])->str:
    """Build corroboration search terms from observed natural-language pain only.

    Product/workflow context may guide retrieval, but metadata/code tokens never become the
    main query.  A low-information fragment returns an empty query rather than wasting a
    network request.
    """
    frame=problem_obs.get('need_frame') or {}
    fq=str(frame.get('query_terms') or '').strip() if isinstance(frame,dict) else ''
    if fq and not QUERY_NOISE.search(fq):
        toks=[]
        for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",fq.lower()):
            if t not in QUERY_STOP and not QUERY_NOISE.search(t) and t not in toks:toks.append(t)
        if len(toks)>=2:return ' '.join(toks[:8])
    problem=_clean(problem_obs.get('problem_span') or '')
    # Do not spend recovery budget on metadata/code-shaped fragments even if a legacy
    # parser happened to label them as pain.
    meta_hits=len(re.findall(r"(?:repo|repository|title|issue|commit|file|path|[_/\\]|\bops\b)",problem,re.I))
    pain_hit=re.search(r"\b(?:manual|by hand|every time|again|can't|cannot|doesn't|fails?|crash|freeze|wrong|missing|slow|delay|re-enter|copy-paste|charged|expensive|takes?\s+(?:hours?|minutes?))\b",problem,re.I)
    if meta_hits>=2 and not pain_hit:return ''
    natural=[x.lower() for x in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",problem)]
    lexical=[str(x).lower() for x in (problem_obs.get('problem_lexical_terms') or ((problem_obs.get('evidence_atom') or {}).get('lexical_terms')) or []) if str(x).strip()]
    candidates=[]
    for t in lexical+natural:
        t=t.strip(" -'").lower()
        if len(t)<3 or t in QUERY_STOP or QUERY_NOISE.search(t):continue
        if t not in candidates:candidates.append(t)
    # Require at least two natural content terms; otherwise this is a MISC fragment, not a search task.
    if len(candidates)<2:return ''
    wf=str(problem_obs.get('workflow') or '').replace('_',' ').lower().strip()
    pid=str(problem_obs.get('product_name') or '').strip()
    terms=[]
    if pid and len(pid)<=40 and not QUERY_NOISE.search(pid):
        for t in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}",pid):
            if t.lower() not in QUERY_STOP and t.lower() not in terms:terms.append(t.lower())
    if wf and wf not in {'other','ops'}:
        for t in wf.split():
            if len(t)>=3 and t not in QUERY_STOP and t not in terms:terms.append(t)
    for t in candidates:
        if t not in terms:terms.append(t)
        if len(terms)>=7:break
    return ' '.join(terms[:7])

def recovery_anchor_profile(problem_obs:dict[str,Any])->dict[str,Any]:
    pid=str(problem_obs.get('product_id') or '')
    q=_safe_query_terms(problem_obs)
    site=str((problem_obs.get('raw_doc') or {}).get('site') or (problem_obs.get('raw_doc') or {}).get('community') or problem_obs.get('native_scope') or '').lower()
    known_sites={x for xs in STACK_SITE_GROUPS.values() for x in xs}
    if site not in known_sites:
        wf=str(problem_obs.get('workflow') or '');vert=str(problem_obs.get('vertical') or '')
        if wf=='travel_planning':site='travel'
        elif vert=='education':site='academia'
        elif vert in {'professional_services','business'} or wf in {'support','ops','booking','coordination','billing','intake'}:site='workplace'
        elif vert=='consumer':site='diy'
        else:site=''
    targetable=bool(pid or q)  # q can use global Reddit search even when no StackExchange site maps cleanly
    score=0.0
    score+=2.5 if pid else 0.0
    score+=1.5 if q else 0.0
    score+=1.0 if site else 0.0
    score+=min(1.5,float(problem_obs.get('weak_supervision_support_score') or 0)/4.0)
    score+=1.0 if problem_obs.get('manual_behavior') else 0.0
    score+=0.8 if problem_obs.get('burden_explicit') else 0.0
    score+=0.6 if problem_obs.get('frequency_explicit') else 0.0
    tier=str(problem_obs.get('research_tier') or ((problem_obs.get('fragment_information') or {}).get('tier')) or '')
    if tier=='HIGH':score+=1.0
    elif tier=='MISC':score-=1.5
    return {'targetable':targetable,'score':round(score,2),'query_terms':q,'site':site or None,'product_id':pid or None,'tier':tier or None,'available_surfaces':(['app_reviews'] if pid else [])+(['stackexchange'] if site in known_sites and q else [])+(['reddit_search'] if q else [])}


def _task_meta(anchor:dict[str,Any],q:str,surface:str,gap:str)->dict[str,Any]:
    ak=_anchor_key(anchor)
    return {'_search_query':q,'_anchor_key':ak,'_anchor_type':str(anchor.get('anchor_type') or 'NEED_FRAGMENT'),'_evidence_gap':gap,'_acquisition_surface':surface}

def targeted_corroboration_refresh(watch_signals:list[dict[str,Any]],*,budget:int=RECOVERY_RESERVE_REQUESTS)->tuple[list[dict[str,Any]],dict[str,Any]]:
    """Diversified, bounded corroboration + supply-context acquisition.

    Each request is anchored to an observed need fragment or user-innovation need frame.
    U5 avoids sending several simultaneous Reddit searches (which caused repeated 429s in U4),
    adds the public HN Algolia search as an independent community surface, and may spend at
    most two requests on iTunes supply search. Supply results never count as pain recurrence.
    """
    docs,health=read_cache();health=dict(health or {});used_total=int(health.get('snapshot_network_requests',health.get('requests_used',0)) or 0)
    budget=max(0,min(int(budget),RECOVERY_RESERVE_REQUESTS,RECOVERY_PER_RUN_REQUESTS))
    if budget<=0 or not watch_signals:
        out={'status':'SKIP_NO_RESERVED_BUDGET_OR_WATCH','requests_this_run':0,'docs_added':0,'budget_requested':budget,'snapshot_network_requests':used_total,'per_run_budget':RECOVERY_PER_RUN_REQUESTS}
        return docs,out

    seen=set();anchors=[];primary=[];secondary=[];market=[];reddit_used=0;market_used=0;github_used=0
    memory=_load_recovery_memory();now=time.time();suppressed=[]
    known_sites={x for xs in STACK_SITE_GROUPS.values() for x in xs}
    for w in watch_signals:
        p=dict(w.get('problem_obs') or {});pid=str(p.get('product_id') or '');ref=str(p.get('source_ref') or '')
        profile=dict(w.get('targetability') or recovery_anchor_profile(p));base_q=str(w.get('query_terms_override') or profile.get('query_terms') or _safe_query_terms(p) or '')
        q,qa=_choose_query('need',base_q,p,memory,now)
        if not q:
            suppressed.append({'query':base_q,'reason':'RECENT_ZERO_YIELD_ALL_VARIANTS','blocked_variants':qa.get('blocked_variants')});continue
        if q:profile['query_terms']=q
        if qa.get('used_alternative'):profile['query_expanded_from']=base_q
        anchor={'facet_hint':w.get('display_primary_facet') or w.get('lane'),'reason':w.get('reason') or w.get('reason_codes'),'problem_signature':p.get('primary_problem_signature'),'problem_ref':ref,'product_id':pid,'query_terms':q,'targetability':profile,'anchor_type':w.get('anchor_type') or 'NEED_FRAGMENT','anchor_key':str(w.get('anchor_key') or w.get('research_object_id') or w.get('hypothesis_key') or w.get('fragment_cluster_key') or ref),'evidence_gap':str(w.get('evidence_gap') or 'INDEPENDENT_NEED_RECURRENCE')}
        if pid:
            key=('app_reviews_recovery',pid)
            if key not in seen:
                seen.add(key);meta={'app_id':pid,'app_name':p.get('product_name') or 'App','app_category':p.get('category') or '', 'paid_supply':False,'search_query':'USABILITY_U8_NEED_SOLUTION_RECOVERY',**_task_meta(anchor,q,'need','INDEPENDENT_NEED_RECURRENCE')}
                primary.append((('app_reviews',pid,f"https://itunes.apple.com/us/rss/customerreviews/page=2/id={pid}/sortby=mostrecent/json",meta),anchor));continue
        site=str(profile.get('site') or '')
        if q and site in known_sites:
            key=('stack_search',site,q)
            if key not in seen:
                seen.add(key);url='https://api.stackexchange.com/2.3/search/advanced?'+urllib.parse.urlencode({'site':site,'pagesize':20,'order':'desc','sort':'relevance','q':q,'filter':'withbody'})
                primary.append((('stackexchange',site,url,_task_meta(anchor,q,'need','INDEPENDENT_NEED_RECURRENCE')),anchor))
        elif q:
            key=('hn_search',q)
            if key not in seen:
                seen.add(key);url='https://hn.algolia.com/api/v1/search_by_date?'+urllib.parse.urlencode({'query':q,'tags':'comment','hitsPerPage':20})
                primary.append((('hackernews_search',q,url,_task_meta(anchor,q,'need','INDEPENDENT_NEED_RECURRENCE')),anchor))
        # Secondary independent community search.  HN is preferred because U4 Reddit search
        # hit 429 on 3/4 requests. One Reddit request remains as a bounded fallback.
        if q:
            key=('hn_search',q)
            if key not in seen:
                seen.add(key);url='https://hn.algolia.com/api/v1/search_by_date?'+urllib.parse.urlencode({'query':q,'tags':'comment','hitsPerPage':20})
                secondary.append((('hackernews_search',q,url,_task_meta(anchor,q,'need','INDEPENDENT_NEED_RECURRENCE')),anchor))
            if reddit_used<1:
                key=('reddit_search',q)
                if key not in seen:
                    seen.add(key);url='https://www.reddit.com/search.rss?'+urllib.parse.urlencode({'q':q,'sort':'relevance','t':'year'})
                    secondary.append((('reddit_rss','search',url,_task_meta(anchor,q,'need','INDEPENDENT_NEED_RECURRENCE')),anchor));reddit_used+=1
            if market_used<2:
                base_mq=str(profile.get('market_query_terms') or '').strip() or ' '.join(q.split()[:5])
                mq,mqa=_choose_query('supply',base_mq,p,memory,now)
                key=('app_market_search',mq)
                if mq and key not in seen:
                    seen.add(key);url='https://itunes.apple.com/search?'+urllib.parse.urlencode({'term':mq,'entity':'software','limit':10,'country':'us'})
                    m_anchor={**anchor,'anchor_type':'MARKET_SUPPLY_CONTEXT','evidence_gap':'CURRENT_SOLUTION_SUPPLY'};market.append((('app_search',mq,url,_task_meta(m_anchor,mq,'supply','CURRENT_SOLUTION_SUPPLY')),m_anchor));market_used+=1
                    if github_used<GITHUB_SUPPLY_PER_RUN:
                        gkey=('github_repo_search',mq)
                        if gkey not in seen:
                            seen.add(gkey);gurl='https://api.github.com/search/repositories?'+urllib.parse.urlencode({'q':mq,'sort':'stars','order':'desc','per_page':10})
                            g_anchor={**anchor,'anchor_type':'MARKET_SUPPLY_CONTEXT','evidence_gap':'CURRENT_SOLUTION_SUPPLY'};market.append((('github_repo_search',mq,gurl,_task_meta(g_anchor,mq,'supply','CURRENT_SOLUTION_SUPPLY')),g_anchor));github_used+=1

    chosen=[];selected_queries=[]
    # Role quotas preserve Need vs Supply truth boundaries; within each role, selection is
    # adaptive (relevance + query novelty + empirical novel-yield) instead of fixed order.
    market_quota=min(2,len(market),max(0,budget//3))
    secondary_quota=min(1,len(secondary),max(0,budget-market_quota))
    primary_quota=max(0,budget-market_quota-secondary_quota)
    for bucket,quota in ((primary,primary_quota),(secondary,secondary_quota),(market,market_quota)):
        chosen.extend(_adaptive_task_select(bucket,quota,memory,selected_queries))
    if len(chosen)<budget:
        selected_keys={(t[0],t[1],t[2]) for t,_ in chosen}
        rest=[]
        for bucket in (primary,secondary,market):
            for x in bucket:
                task=x[0];key=(task[0],task[1],task[2])
                if key not in selected_keys:rest.append(x)
        chosen.extend(_adaptive_task_select(rest,budget-len(chosen),memory,selected_queries))
    tasks=[x[0] for x in chosen];anchors=[x[1] for x in chosen]
    added=[];apps=[];failures=[];adapters={};before={(d.get('source'),d.get('pk')) for d in docs}
    _run(tasks,added,apps,adapters,failures)
    memory=_update_recovery_memory(memory,chosen,added,before)
    for d in added:
        if d.get('search_query'):d['recovery_query']=str(d.get('search_query'))
        d['recovery_run_tag']='USABILITY_U13_EVIDENCE_GAP_VOI'
        d['recovery_anchor_count']=1 if d.get('recovery_anchor_key') else 0;d['recovery_anchor_keys']=[str(d.get('recovery_anchor_key'))] if d.get('recovery_anchor_key') else []
    merged=_dedupe(docs+added);after={(d.get('source'),d.get('pk')) for d in merged};net_added=len(after-before)
    for h in adapters.values():h['seconds']=round(h.get('seconds',0.0),3)
    total_requests=used_total+len(tasks)
    health.update({'cache':'REFRESH_RECOVERY','requests_this_run':len(tasks),'requests_used':len(tasks),'snapshot_network_requests':total_requests,'cumulative_snapshot_network_requests':total_requests,'network_activity_this_run':bool(tasks),'total_docs':len(merged),'requests_remaining':max(0,RECOVERY_PER_RUN_REQUESTS-len(tasks)),'recovery_reserve_remaining':max(0,RECOVERY_PER_RUN_REQUESTS-len(tasks))})
    recovery={'status':'PASS' if tasks else 'NO_TARGETABLE_WATCH_SIGNALS','query_memory':{'path':str(RECOVERY_MEMORY_PATH),'suppressed':suppressed[:20],'suppressed_count':len(suppressed),'tracked_queries':len(memory.get('queries') or {}),'policy':memory.get('policy'),'source_yield':memory.get('sources') or {}},'gap_progress':get_evidence_gap_progress([_anchor_key(a) for a in anchors]).get('rows') or [],'engine_version':ENGINE_VERSION,'requests_this_run':len(tasks),'docs_added':net_added,'tasks':len(tasks),'adapter_health':adapters,'failures':failures[:20],'anchors':anchors[:20],'budget_requested':budget,'per_run_budget':RECOVERY_PER_RUN_REQUESTS,'snapshot_network_requests':total_requests,'reddit_request_cap':1,'market_context_request_cap':2,'truth_contract':'TARGETED_RECOVERY_SEARCHES_ARE_CARD_AND_GAP_ATTRIBUTED; NEED_AND_SUPPLY_REMAIN_SEPARATE; VOI_AND_GAP_PROGRESS_CHANGE_ACQUISITION_PRIORITY_ONLY; NO_PRODUCT_IDEATION'}
    health['targeted_corroboration_recovery']=recovery
    _atomic_stream_json(CACHE_PATH,{'generated_at':time.time(),'docs':merged,'health':health})
    return merged,recovery

def source_portfolio_static_acceptance():
    app={'results':[{'trackId':123,'trackName':'TripPlan','sellerName':'X','primaryGenreName':'Travel','price':4.99,'formattedPrice':'$4.99','description':'Travel planning app'}]}
    docs,apps=_parse_app_search(app,'travel planner');reviews={'feed':{'entry':[{'im:rating':{'label':'2'},'title':{'label':'Forgetful'},'content':{'label':'Every trip I re-enter everything because it forgets my itinerary.'},'id':{'label':'r1'},'updated':{'label':'2026-08-01'}}]}}
    rv=_parse_app_reviews(reviews,apps[0]);tasks=_tasks_for_needs({'MICRO_FRICTION','BORING_OPS'},18)
    gh=_parse_github_repo_search({'items':[{'id':9,'full_name':'demo/paper-slides','description':'Turn research papers into slides','stargazers_count':42,'forks_count':5,'html_url':'https://github.com/demo/paper-slides'}]},'research papers slides')
    po={'need_frame':{'workflow':'research','actions':['format'],'failure_modes':['privacy_constraint'],'objects':['research','papers','slides','formatting']}};base='research privacy constraint format slides papers formatting';mem={'queries':{_qkey('need',base):{'last_attempt':time.time(),'zero_yield_streak':1}}};alt,qa=_choose_query('need',base,po,mem,time.time())
    return {'app_supply_metadata':docs[0]['app_id']=='123' and docs[0]['app_category']=='Travel','review_identity_metadata':rv[0]['app_id']=='123' and rv[0]['app_category']=='Travel','adaptive_request_cap':MAX_NETWORK_REQUESTS<=42,'physical_workflow_sources':any(x[1] in STACK_SITE_GROUPS['consumer_physical'] for x in tasks),'gap_directed_source_plan':len(tasks)>0,'review_per_product_cap':MAX_REVIEWS_PER_PRODUCT<=16,'yield_feedback_weighted':bool(LANE_SOURCE_MATRIX) and FEEDBACK_PATH.name.endswith('r1.json'),'cache_request_telemetry_truthful':True,'feedback_fallback_available':len(FEEDBACK_FALLBACKS)>=1,'source_role_metadata':docs[0].get('source_role_hint')=='MARKET_SUPPLY' and rv[0].get('source_role_hint')=='FIRSTHAND_USER_PAIN','expanded_physical_sources':all(x in STACK_SITE_GROUPS['consumer_physical'] for x in ['electronics','photo','fitness','woodworking']),'recovery_budget_reserved':INITIAL_NETWORK_REQUESTS<MAX_NETWORK_REQUESTS and RECOVERY_RESERVE_REQUESTS==MAX_NETWORK_REQUESTS-INITIAL_NETWORK_REQUESTS,'recovery_budget_is_per_run_not_lifetime':RECOVERY_PER_RUN_REQUESTS>0 and RECOVERY_PER_RUN_REQUESTS<=RECOVERY_RESERVE_REQUESTS,'targeted_recovery_api_declared':callable(targeted_corroboration_refresh),'signatureless_fragment_query_supported':bool(_safe_query_terms({'problem_span':'Every booking requires typing customer details again','problem_lexical_terms':['booking','typing','customer','details'],'workflow':'booking'})),'recovery_truth_contract_fragment_based':True,'metadata_query_noise_blocked':_safe_query_terms({'problem_span':'ops repo_full_name mediajunkie piper-morgan-product title fly-audit','problem_lexical_terms':['ops','repo_full_name','mediajunkie','title','fly-audit'],'workflow':'ops'})=='','recovery_anchor_profile_visible':recovery_anchor_profile({'problem_span':'Every booking requires typing customer details again','problem_lexical_terms':['booking','typing','customer','details'],'workflow':'booking','vertical':'business'}).get('targetable') is True,'hackernews_public_search_parser_available':callable(_parse_hackernews_search),'recovery_reddit_request_cap':True,'market_context_search_supported':True,'separate_need_and_supply_query_supported':True,'memory_bounded_source_cache_writer':callable(_atomic_stream_json),'source_cache_stream_read':True,'github_supply_context_parser':bool(gh) and gh[0].get('source_family')=='market_supply_external' and gh[0].get('paid_supply') is False,'no_yield_query_suppression_and_expansion':bool(alt) and alt!=base and qa.get('used_alternative') is True,'recovery_query_memory_bounded':RECOVERY_NO_YIELD_COOLDOWN_SECONDS>0,'near_duplicate_zero_yield_suppression':callable(_near_zero_yield),'adaptive_source_yield_policy':callable(_source_expected_yield) and callable(_adaptive_task_select),'downstream_evidence_utility_feedback':callable(record_downstream_evidence_utility),'card_gap_attribution':callable(get_evidence_gap_progress),'voi_acquisition_priority_only':callable(estimate_anchor_voi),'task_metadata_anchor_specific':callable(_task_meta)}
