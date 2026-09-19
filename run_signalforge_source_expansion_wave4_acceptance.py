from __future__ import annotations

import json
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent


def _stub_database():
    db_pkg = sys.modules.setdefault('database', types.ModuleType('database'))
    conn = types.ModuleType('database.connection')
    class Field:
        def in_(self,*_): return self
        def is_(self,*_): return self
    class Dummy:
        id=Field(); candidate_id=Field(); claim_id=Field(); evidence_id=Field(); case_id=Field()
    for name in ('ProblemCandidate','RadarCase','RadarClaim','RadarClaimEvidence','RadarEvidence'):
        setattr(conn,name,Dummy)
    conn.async_session=None
    sys.modules['database.connection']=conn; setattr(db_pkg,'connection',conn)
_stub_database()

from processors import signalforge_source_adapters as adapters
from processors import signalforge_founder_idea_loop as loop
from processors.signalforge_source_expansion import plan_source_expansion, dedupe_and_cluster_traces
from processors.signalforge_source_registry import (
    registry_snapshot, source_runtime_state, mastodon_instance_configs, lemmy_instance_configs,
    stackexchange_site_configs, ashby_board_names, observation_families_for_source,
)

results=[]
def check(name, cond, detail=None):
    ok=bool(cond); results.append((name,ok,detail)); print(('PASS' if ok else 'FAIL'),name,'' if detail is None else '— '+str(detail)); return ok

@contextmanager
def env(**values):
    old={k:os.environ.get(k) for k in values}
    try:
        for k,v in values.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=str(v)
        yield
    finally:
        for k,v in old.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k]=v

snap=registry_snapshot(); rows={x['source_id']:x for x in snap['sources']}
for sid in ('LEMMY_PUBLIC','STACK_EXCHANGE_NETWORK','ASHBY_PUBLIC_JOBS','MASTODON_SEARCH'):
    check(f'Wave4 registry exposes {sid}', sid in rows)
check('Mastodon is explicitly partial for zero-result absence adequacy', rows['MASTODON_SEARCH']['discovery_scope']=='HASHTAG_TIMELINE_ONLY' and rows['MASTODON_SEARCH']['absence_adequacy']=='PARTIAL', rows['MASTODON_SEARCH'])
check('Lemmy public search is full structured observation source', rows['LEMMY_PUBLIC']['absence_adequacy']=='FULL' and set(rows['LEMMY_PUBLIC']['content_units'])=={'POST','COMMENT'})
check('Ashby is public job metadata source', rows['ASHBY_PUBLIC_JOBS']['access_mode']=='PUBLIC_JOB_POSTING_API' and rows['ASHBY_PUBLIC_JOBS']['auth_type']=='NONE')

with env(SIGNALFORGE_MASTODON_INSTANCES_JSON='[{"base_url":"https://social.example","observation_families":["AGENCY_COMMUNITIES"],"hashtags":["marketresearch"]}]'):
    cfg=mastodon_instance_configs(); st=source_runtime_state('MASTODON_SEARCH')
    check('Mastodon config parser carries explicit observation family and tag', cfg==[{'base_url':'https://social.example','observation_families':['AGENCY_COMMUNITIES'],'hashtags':['marketresearch']}], cfg)
    check('Configured Mastodon is READY without browser/user credential', st['runtime_state']=='READY' and not st['credential_present'], st)
with env(SIGNALFORGE_LEMMY_INSTANCES='https://lemmy.world,https://lemmy.ml'):
    check('Lemmy explicit instance config is deduped and bounded', len(lemmy_instance_configs())==2, lemmy_instance_configs())
with env(SIGNALFORGE_STACKEXCHANGE_SITES_JSON='[{"site":"workplace","observation_families":["AGENCY_COMMUNITIES"]},{"site":"academia","observation_families":["STUDENT_COMMUNITIES"]}]'):
    cfg=stackexchange_site_configs()
    check('Stack Exchange site allowlist carries per-site observation families', cfg[0]['site']=='workplace' and cfg[0]['observation_families']==['AGENCY_COMMUNITIES'], cfg)
    check('Dynamic source family coverage includes configured Stack Exchange families', 'AGENCY_COMMUNITIES' in observation_families_for_source('STACK_EXCHANGE_NETWORK'), observation_families_for_source('STACK_EXCHANGE_NETWORK'))
with env(SIGNALFORGE_ASHBY_BOARDS='acme,foo-bar,acme,bad/name'):
    check('Ashby board parser is explicit and deduped', ashby_board_names()==['acme','foo-bar'], ashby_board_names())

# Mastodon hashtag + context depth.
old_public=adapters._request_public_json
old_assert_public=adapters._assert_public_http_url
mast_calls=[]
def mast_json(url, **kwargs):
    mast_calls.append(url)
    if '/timelines/tag/marketresearch' in url:
        return [{
            'id':'10','created_at':'2026-09-06','content':'<p>Agency client research still takes hours and we verify sources manually.</p>',
            'url':'https://social.example/@a/10','uri':'https://social.example/users/a/statuses/10','in_reply_to_id':None,'replies_count':1,'language':'en',
            'account':{'acct':'a@social.example','username':'a'}
        }], {'status_code':200}
    if '/statuses/10/context' in url:
        return {'ancestors':[], 'descendants':[{'id':'11','created_at':'2026-09-06','content':'<p>Same problem for our product studio.</p>','url':'https://social.example/@b/11','uri':'u11','in_reply_to_id':'10','replies_count':0,'account':{'acct':'b@social.example','username':'b'}}]}, {'status_code':200}
    raise AssertionError(url)
with env(SIGNALFORGE_MASTODON_INSTANCES_JSON='[{"base_url":"https://social.example","observation_families":["AGENCY_COMMUNITIES"],"hashtags":["marketresearch"]}]'):
    adapters._request_public_json=mast_json
    adapters._assert_public_http_url=lambda _url: None
    try: mast=adapters.search_mastodon('market evidence intelligence for AI agencies')
    finally:
        adapters._request_public_json=old_public
        adapters._assert_public_http_url=old_assert_public
check('Mastodon emits status plus thread reply as first-class traces', [x['content_unit'] for x in mast['traces']]==['STATUS','REPLY'], mast['traces'])
check('Mastodon status/reply share one independence group', len({x['metadata']['independence_group_key'] for x in mast['traces']})==1)
check('Mastodon uses public hashtag timeline plus bounded status context', any('/timelines/tag/marketresearch' in x for x in mast_calls) and any('/statuses/10/context' in x for x in mast_calls), mast_calls)
check('Mastodon zero-result semantics stay partial, not absence-adequate', mast['absence_adequacy']=='PARTIAL' and mast['transport']['zero_results_not_adequate_for_market_absence'] is True)

# Lemmy public search + comments.
lemmy_calls=[]
def lemmy_json(url, **kwargs):
    lemmy_calls.append(url)
    if '/api/v4/search?' in url:
        return {'posts':[{'post':{'id':7,'name':'Agency research takes too long','body':'We still verify client evidence manually.','ap_id':'https://lemmy.world/post/7','published_at':'2026-09-06'},'creator':{'name':'agency_owner'},'community':{'name':'smallbusiness'}}], 'comments':[]}, {'status_code':200}
    if '/api/v4/comment/list?' in url:
        return {'items':[{'comment':{'id':8,'post_id':7,'content':'We pay consultants but research is still manual.','ap_id':'https://lemmy.world/comment/8','published_at':'2026-09-06'},'creator':{'name':'studio'},'community':{'name':'smallbusiness'}}]}, {'status_code':200}
    raise AssertionError(url)
with env(SIGNALFORGE_LEMMY_INSTANCES_JSON='[{"base_url":"https://lemmy.world","observation_families":["AGENCY_COMMUNITIES"]}]'):
    adapters._request_public_json=lemmy_json
    adapters._assert_public_http_url=lambda _url: None
    try: lem=adapters.search_lemmy('market research agency client evidence')
    finally:
        adapters._request_public_json=old_public
        adapters._assert_public_http_url=old_assert_public
check('Lemmy public adapter emits post and comment', {x['content_unit'] for x in lem['traces']}=={'POST','COMMENT'}, lem['traces'])
check('Lemmy post/comments share post-level independence group', len({x['metadata']['independence_group_key'] for x in lem['traces']})==1)
check('Lemmy uses public v4 search and bounded comment-list depth', any('/api/v4/search?' in x for x in lemmy_calls) and any('/api/v4/comment/list?' in x for x in lemmy_calls), lemmy_calls)

# Stack Exchange network public Q/A/comments.
old_json=adapters._request_json
se_calls=[]
def se_json(url, **kwargs):
    se_calls.append(url)
    if 'search/advanced' in url:
        return {'items':[{'question_id':42,'title':'How do agencies validate client ideas?','body':'Our consultancy spends hours on manual research.','link':'https://workplace.stackexchange.com/q/42','owner':{'display_name':'consultant'},'creation_date':1,'score':3,'answer_count':1}]}, {'status_code':200}
    if '/questions/42/answers?' in url:
        return {'items':[{'answer_id':50,'body':'We use paid discovery workshops.','owner':{'display_name':'lead'},'creation_date':2,'score':2}]}, {'status_code':200}
    if '/questions/42/comments?' in url:
        return {'items':[{'comment_id':60,'body':'Still hard to trust AI research.','owner':{'display_name':'user'},'creation_date':3,'score':1}]}, {'status_code':200}
    raise AssertionError(url)
with env(SIGNALFORGE_STACKEXCHANGE_SITES_JSON='[{"site":"workplace","observation_families":["AGENCY_COMMUNITIES"]}]'):
    adapters._request_json=se_json
    try: se=adapters.search_stackexchange_network('agency market validation client research')
    finally: adapters._request_json=old_json
check('Stack Exchange network emits question answer comment units', {x['content_unit'] for x in se['traces']}=={'QUESTION','ANSWER','COMMENT'}, se['traces'])
check('Stack Exchange configured site conversation shares independence group', len({x['metadata']['independence_group_key'] for x in se['traces']})==1)
check('Stack Exchange calls only explicit configured api_site_parameter', all('site=workplace' in x for x in se_calls), se_calls)

# Ashby jobs.
ash_calls=[]
def ash_json(url, **kwargs):
    ash_calls.append(url)
    return {'jobs':[{'title':'Product Strategy Consultant','location':'Remote','department':'Strategy','team':'Consulting','isListed':True,'descriptionPlain':'Run customer research and market validation for clients.','jobUrl':'https://jobs.ashbyhq.com/acme/1','publishedAt':'2026-09-06','compensation':{'summary':'$120k-$150k'}}]}, {'status_code':200}
with env(SIGNALFORGE_ASHBY_BOARDS='acme'):
    adapters._request_json=ash_json
    try: ash=adapters.search_ashby_jobs('product strategy market validation research')
    finally: adapters._request_json=old_json
check('Ashby adapter emits relevant public job with compensation metadata', ash['count']==1 and ash['traces'][0]['metadata']['compensation']['summary']=='$120k-$150k', ash['traces'])
check('Ashby request uses official public posting API with includeCompensation', ash_calls==['https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true'], ash_calls)

# Source adequacy: partial discovery can find evidence but cannot justify zero-result PARK.
fresh_summary={
    'founder_query':'SignalForge market evidence intelligence for AI agencies',
    'coverage':'COMPLETE_FOR_CONFIGURED_SOURCES','language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE',
    'source_health':[{
        'source':'MASTODON_SEARCH','source_family':'MASTODON','observation_source_families':['AGENCY_COMMUNITIES'],
        'status':'SUCCESS','count':0,'absence_adequacy':'PARTIAL','discovery_scope':'HASHTAG_TIMELINE_ONLY'
    }]
}
source_fit={'source_fit_state':'INSUFFICIENT','configured_source_families':['AGENCY_COMMUNITIES']}
adeq=loop.build_source_adequacy(fresh_summary=fresh_summary, source_fit=source_fit)
check('Partial Mastodon discovery family is observed but excluded from absence-adequate fit', 'AGENCY_COMMUNITIES' in adeq['observed_source_families'] and 'AGENCY_COMMUNITIES' not in adeq['absence_adequate_source_families'], adeq)
check('Partial-only source cannot make agency source fit sufficient for PARK', adeq['source_fit_state']!='SUFFICIENT' and 'MASTODON_SEARCH' in adeq['limited_absence_sources'], adeq)

# Positive evidence from partial source still goes through relevance and can count if semantically relevant.
fresh={
    'founder_query':'SignalForge Market Evidence Intelligence for AI Agencies','status':'PASS','language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE',
    'sources':[{'source':'MASTODON_SEARCH','source_family':'MASTODON','observation_source_families':['AGENCY_COMMUNITIES'],'absence_adequacy':'PARTIAL','status':'SUCCESS','count':1}],
    'traces':[loop._make_trace(source='MASTODON_SEARCH',kind='DISCUSSION',title='AI agency client research',excerpt='Our AI agency spends hours validating client opportunities and still verifies research manually.',url='https://social.example/@a/10',metadata={'content_unit':'STATUS','independence_group_key':'mastodon:s:10'})]
}
sm=loop.summarize_fresh_probe(fresh)
check('Partial discovery source positive trace may count only after thesis relevance', sm['relevant_trace_count']==1 and sm['problem_discussions']==1, sm)

# Planner dynamic config coverage + truth boundaries.
with env(SIGNALFORGE_LEMMY_INSTANCES_JSON='[{"base_url":"https://lemmy.world","observation_families":["AGENCY_COMMUNITIES"]}]', SIGNALFORGE_ASHBY_BOARDS='acme'):
    plan=plan_source_expansion('SignalForge Market Evidence Intelligence for AI Agencies')
check('Agency planner can select configured Lemmy and Ashby source surfaces', {'LEMMY_PUBLIC','ASHBY_PUBLIC_JOBS'}.issubset(set(plan['selected_source_ids'])), plan['selected_source_ids'])
with env(SIGNALFORGE_MASTODON_INSTANCES_JSON='[{"base_url":"https://mastodon.social","observation_families":["AGENCY_COMMUNITIES"],"hashtags":["agency"]}]'):
    plan2=plan_source_expansion('SignalForge Market Evidence Intelligence for AI Agencies')
check('Planner explicitly separates partial absence-adequacy sources', 'MASTODON_SEARCH' in plan2['partial_absence_adequacy_source_ids'] and 'MASTODON_SEARCH' not in plan2['full_absence_adequacy_source_ids'], plan2)

raw=[
 {'source':'LEMMY_PUBLIC','source_family':'LEMMY','content_unit':'POST','title':'Agency research pain','excerpt':'Our agency spends hours verifying client research manually before proposals.','url':'https://lemmy.world/post/7','metadata':{'independence_group_key':'lemmy:lemmy.world:post:7'}},
 {'source':'MASTODON_SEARCH','source_family':'MASTODON','content_unit':'STATUS','title':'Agency research pain','excerpt':'Our agency spends hours verifying client research manually before proposals.','url':'https://social.example/@a/10','metadata':{'independence_group_key':'mastodon:s:10'}},
]
dedup, clusters=dedupe_and_cluster_traces(raw)
check('Wave4 cross-source exact mirror still dedupes before recurrence', len(dedup)==1 and all(c['independence_status']=='UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE' for c in clusters), (dedup,clusters))

src=(ROOT/'processors/signalforge_source_adapters.py').read_text(encoding='utf-8')
reg=(ROOT/'processors/signalforge_source_registry.py').read_text(encoding='utf-8')
exp=(ROOT/'processors/signalforge_source_expansion.py').read_text(encoding='utf-8')
check('Wave4 adds no browser-session automation or bypass implementation', all(x not in (src+reg).lower() for x in ['import selenium','from selenium','import playwright','from playwright','browser_cookie3','captcha_solver']) and 'NO_BROWSER_COOKIES' in reg and 'ANTI_BOT_BYPASS' in reg)
check('Wave4 imports no Market Ground Truth writer into source layer', 'market_ground_truth' not in src and 'market_ground_truth' not in exp)
check('Wave4 keeps source output UNVALIDATED and zero Market Truth authority', 'UNVALIDATED_SEARCH_TRACE' in src and 'market_truth_writes' in exp)

passed=sum(1 for _,ok,_ in results if ok)
print('-'*108)
print(f'RESULT: {passed}/{len(results)} PASS')
if passed!=len(results): raise SystemExit(1)
print('FINAL_STATUS: SIGNALFORGE_SOURCE_EXPANSION_WAVE4_ACCEPTANCE_PASS')
