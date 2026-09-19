from __future__ import annotations

import json
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parent

def _stub_database():
    db_pkg=sys.modules.setdefault('database',types.ModuleType('database'))
    conn=types.ModuleType('database.connection')
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
from processors.signalforge_source_expansion import dedupe_and_cluster_traces, plan_source_expansion, run_source_expansion
from processors.signalforge_source_registry import registry_snapshot, source_runtime_state, discourse_site_configs
from processors.signalforge_founder_idea_loop import merge_expansion_into_fresh, summarize_fresh_probe

results=[]
def check(name,cond,detail=None):
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

snap=registry_snapshot(); ids={x['source_id'] for x in snap['sources']}
check('wave2 registry adds Bluesky X Discourse and review-policy entries', {'BLUESKY_PUBLIC_SEARCH','X_RECENT_SEARCH','DISCOURSE_PUBLIC','GOOGLE_PLACES_REVIEWS','YELP_REVIEWS','MASTODON_SEARCH'}.issubset(ids), ids)
check('Bluesky public reads are ready without user token', source_runtime_state('BLUESKY_PUBLIC_SEARCH')['runtime_state']=='READY')
check('Google Places and Yelp are blocked from durable Wave2 ingestion', source_runtime_state('GOOGLE_PLACES_REVIEWS')['runtime_state']=='RESTRICTED' and source_runtime_state('YELP_REVIEWS')['runtime_state']=='RESTRICTED')
check('review registry records persistence incompatibility instead of pretending coverage', source_runtime_state('GOOGLE_PLACES_REVIEWS')['persistence_policy']=='EPHEMERAL_DISPLAY_ONLY_REQUIRED')
check('registry never returns upstream secret values', all('secret' not in json.dumps(x).lower() for x in snap['sources']))

old_json=adapters._request_json
# Bluesky: search + thread reply.
calls=[]
def bsky_json(url,*,headers=None,timeout=6.0):
    calls.append((url,dict(headers or {})))
    if 'searchPosts' in url:
        return {'posts':[{'uri':'at://did:plc:abc/app.bsky.feed.post/r1','cid':'c1','author':{'handle':'agencyowner.bsky.social','displayName':'Agency Owner'},'record':{'text':'Our agency still does market validation manually for client proposals.','createdAt':'2026-09-06T01:00:00Z'},'replyCount':1,'likeCount':5,'quoteCount':0}]},{'status_code':200}
    if 'getPostThread' in url:
        return {'thread':{'post':{},'replies':[{'post':{'uri':'at://did:plc:def/app.bsky.feed.post/r2','author':{'handle':'studiolead.bsky.social'},'record':{'text':'Same. We pay for tools but still verify everything ourselves.','createdAt':'2026-09-06T01:05:00Z'},'replyCount':0,'likeCount':2},'replies':[]}] }},{'status_code':200}
    raise AssertionError(url)
adapters._request_json=bsky_json
try: b=adapters.search_bluesky('market evidence intelligence for AI agencies')
finally: adapters._request_json=old_json
check('Bluesky adapter reads public post plus reply', {x['content_unit'] for x in b['traces']}=={'POST','REPLY'}, b)
check('Bluesky public adapter sends no Authorization secret', all('Authorization' not in h for _,h in calls), calls)
check('Bluesky trace keeps unvalidated boundary', all(x.get('truth_status')=='UNVALIDATED_SEARCH_TRACE' for x in b['traces']))

# X: token is server-only and reads are bounded by cost before request.
captured={}
def x_json(url,*,headers=None,timeout=6.0):
    captured['url']=url; captured['headers']=dict(headers or {})
    return {'data':[{'id':'1','text':'Agency discovery still takes too long and is manual.','author_id':'u1','conversation_id':'1','created_at':'2026-09-06T02:00:00Z','lang':'en','public_metrics':{'like_count':3},'referenced_tweets':[]}], 'includes':{'users':[{'id':'u1','username':'agency_ops','name':'Agency Ops'}]}},{'status_code':200}
with env(X_BEARER_TOKEN='x-secret',SIGNALFORGE_X_MAX_POST_READS_PER_PROBE='10',SIGNALFORGE_X_POST_READ_UNIT_USD='0.005',SIGNALFORGE_X_MAX_USD_PER_PROBE='0.05'):
    adapters._request_json=x_json
    try: x=adapters.search_x_recent('agency market validation manual research')
    finally: adapters._request_json=old_json
check('X recent search uses official bearer header and exact bounded result cap', captured.get('headers',{}).get('Authorization')=='Bearer x-secret' and parse_qs(urlparse(captured['url']).query).get('max_results')==['10'])
check('X adapter exposes cost estimate but never echoes bearer token', x['transport']['estimated_max_cost_usd']==0.05 and 'x-secret' not in json.dumps(x), x['transport'])
check('X paid conversation expansion is disabled by default', x['transport']['conversation_expansion'].startswith('DISABLED'))
with env(X_BEARER_TOKEN='x-secret',SIGNALFORGE_X_MAX_POST_READS_PER_PROBE='20',SIGNALFORGE_X_POST_READ_UNIT_USD='0.005',SIGNALFORGE_X_MAX_USD_PER_PROBE='0.05'):
    try: adapters.search_x_recent('agency market validation'); blocked=False
    except adapters.SourceAdapterError as exc: blocked=exc.category=='COST_BUDGET'
check('X hard-fails before transport when configured per-probe budget would be exceeded', blocked)

# Discourse: explicitly configured public site, SSRF-safe, search + topic posts.
old_public_json=adapters._request_public_json; old_assert=adapters._assert_public_http_url
seen=[]
def discourse_json(url,*,headers=None,timeout=6.0,max_bytes=2_000_000):
    seen.append(url)
    if '/search.json?' in url:
        return {'topics':[{'id':9,'slug':'agency-research','title':'How agencies validate client ideas'}],'posts':[{'id':91,'topic_id':9,'username':'founder','blurb':'We still do discovery research manually.','created_at':'2026-09-06'}]},{'status_code':200}
    if '/t/agency-research/9.json' in url:
        return {'title':'How agencies validate client ideas','post_stream':{'posts':[{'id':91,'post_number':1,'username':'founder','cooked':'We still do discovery research manually.','created_at':'2026-09-06'},{'id':92,'post_number':2,'username':'consultant','cooked':'We charge for discovery sprints but evidence collection is slow.','created_at':'2026-09-06'}]}},{'status_code':200}
    raise AssertionError(url)
with env(SIGNALFORGE_DISCOURSE_SITES_JSON=json.dumps([{'base_url':'https://forum.example.com','observation_families':['AGENCY_COMMUNITIES']}])):
    adapters._assert_public_http_url=lambda url: None
    adapters._request_public_json=discourse_json
    try: d=adapters.search_discourse('agency market validation discovery research')
    finally: adapters._request_public_json=old_public_json; adapters._assert_public_http_url=old_assert
check('Discourse adapter expands public search into topic/reply observations', any(x['content_unit']=='TOPIC' for x in d['traces']) and len(d['traces'])>=3, d)
check('Discourse preserves explicitly configured observation family', 'AGENCY_COMMUNITIES' in d['observation_source_families'], d['observation_source_families'])
with env(SIGNALFORGE_DISCOURSE_SITES_JSON=json.dumps([{'base_url':'http://127.0.0.1:3000','observation_families':['AGENCY_COMMUNITIES']}])):
    try: adapters.search_discourse('agency validation'); discourse_blocked=False
    except adapters.SourceAdapterError as exc: discourse_blocked=exc.category=='SECURITY'
check('Discourse generic site adapter inherits SSRF localhost protection', discourse_blocked)

# Planner: agency now sees free/public community sources if ready; X only when token exists.
with env(X_BEARER_TOKEN=None,SIGNALFORGE_DISCOURSE_SITES_JSON=json.dumps([{'base_url':'https://forum.example.com','observation_families':['AGENCY_COMMUNITIES']}])):
    plan=plan_source_expansion('SignalForge Market Evidence Intelligence for AI Agencies doing opportunity validation')
sel=set(plan['selected_source_ids'])
check('planner auto-selects Bluesky public and configured Discourse for agency buyer voice', {'BLUESKY_PUBLIC_SEARCH','DISCOURSE_PUBLIC'}.issubset(sel), sel)
check('planner does not select unconfigured paid X', 'X_RECENT_SEARCH' not in sel, sel)
with env(X_BEARER_TOKEN='x-secret',SIGNALFORGE_DISCOURSE_SITES_JSON=''):
    planx=plan_source_expansion('SignalForge Market Evidence Intelligence for AI Agencies doing opportunity validation')
check('planner selects X only after credential exists', 'X_RECENT_SEARCH' in set(planx['selected_source_ids']), planx['selected_source_ids'])

# Cross-source exact mirrors and near-duplicates must not inflate recurrence.
raw=[
 {'source':'BRAVE_WEB','source_family':'BRAVE_WEB','content_unit':'WEB_PAGE','title':'Agency validation is still manual','excerpt':'Client opportunity research takes too long and teams verify evidence manually.','url':'https://example.com/post?utm_source=x','truth_status':'UNVALIDATED_SEARCH_TRACE'},
 {'source':'RSS_ATOM','source_family':'PUBLIC_FEEDS','content_unit':'FEED_ITEM','title':'Agency validation is still manual','excerpt':'Client opportunity research takes too long and teams verify evidence manually.','url':'https://example.com/post?utm_source=rss','truth_status':'UNVALIDATED_SEARCH_TRACE'},
 {'source':'BLUESKY_PUBLIC_SEARCH','source_family':'BLUESKY','content_unit':'POST','title':'Agency founder note','excerpt':'Client opportunity research takes too long and teams still verify evidence manually.','url':'https://bsky.app/profile/a/post/1','truth_status':'UNVALIDATED_SEARCH_TRACE'},
]
dedup,clusters=dedupe_and_cluster_traces(raw)
check('canonical URL strips tracking params and exact web/feed mirror is deduped', len(dedup)==2, dedup)
check('near-duplicate cross-source traces are clustered but independence remains unvalidated', any(c['member_count']>=2 and c['independence_status']=='UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE' for c in clusters), clusters)

# Full expansion merge must still run existing semantic relevance gate.
legacy={'engine_version':'fixture','status':'PASS','founder_query':'English Output Trainer for Taiwan Exam Students','queries':[],'search_query_used':'','language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE','sources':[],'traces':[],'truth_boundary':'fixture'}
exp={'status':'PASS','plan':{},'elapsed_ms':1,'sources':[{'source':'BLUESKY_PUBLIC_SEARCH','source_family':'BLUESKY','observation_source_families':['STUDENT_COMMUNITIES'],'status':'SUCCESS','count':2,'traces':[
 {'source':'BLUESKY_PUBLIC_SEARCH','source_family':'BLUESKY','kind':'DISCUSSION','content_unit':'POST','title':'Taiwan GSAT English writing','excerpt':'Taiwan students struggle to produce English writing and translation under exam time pressure.','url':'https://bsky.app/profile/a/post/1','truth_status':'UNVALIDATED_SEARCH_TRACE'},
 {'source':'BLUESKY_PUBLIC_SEARCH','source_family':'BLUESKY','kind':'DISCUSSION','content_unit':'POST','title':'GitHub bot launch','excerpt':'A new coding bot was released for repository workflows.','url':'https://bsky.app/profile/b/post/2','truth_status':'UNVALIDATED_SEARCH_TRACE'}]}]}
merged=merge_expansion_into_fresh(legacy,exp); sm=summarize_fresh_probe(merged)
check('Wave2 traces still pass thesis relevance before counters', sm['relevant_trace_count']==1 and sm['problem_discussions']==1, sm)

# Truth/security source inspection.
reg=(ROOT/'processors/signalforge_source_registry.py').read_text()
ad=(ROOT/'processors/signalforge_source_adapters.py').read_text()
exp_src=(ROOT/'processors/signalforge_source_expansion.py').read_text()
check('Wave2 adapters do not import Market Ground Truth authority', 'market_ground_truth' not in ad and 'RadarClaim' not in ad)
check('Wave2 clustering explicitly cannot create recurrence', 'UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE' in exp_src and 'CLUSTERS_DO_NOT_CREATE_INDEPENDENT_RECURRENCE' in exp_src)
check('Wave2 never adds browser cookie VPN or CAPTCHA shortcuts', all(x not in ad for x in ['browser_cookie','VPN_PASSWORD','captcha_solver','selenium']))

passed=sum(1 for _,ok,_ in results if ok)
print('-'*100)
print(f'RESULT: {passed}/{len(results)} PASS')
if passed!=len(results): raise SystemExit(1)
print('FINAL_STATUS: SIGNALFORGE_SOURCE_EXPANSION_WAVE2_ACCEPTANCE_PASS')
