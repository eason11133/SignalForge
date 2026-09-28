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

from processors import signalforge_founder_idea_loop as loop
from processors import signalforge_source_adapters as adapters
from processors.signalforge_source_expansion import dedupe_and_cluster_traces, plan_source_expansion
from processors.signalforge_source_registry import registry_snapshot, source_runtime_state, github_discussion_repos

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

# Registry/depth contract.
snap=registry_snapshot(); rows={x['source_id']:x for x in snap['sources']}
check('Wave3 registry adds GitHub Discussions as explicit deep community source', 'GITHUB_DISCUSSIONS' in rows, rows.keys())
check('GitHub Discussions content units are discussion comment reply', set(rows['GITHUB_DISCUSSIONS']['content_units'])=={'DISCUSSION','DISCUSSION_COMMENT','DISCUSSION_REPLY'})
with env(GITHUB_TOKEN='gh-secret', SIGNALFORGE_GITHUB_DISCUSSION_REPOS=None):
    check('GitHub Discussions token without repo allowlist is pending configuration', source_runtime_state('GITHUB_DISCUSSIONS')['runtime_state']=='PENDING_CONFIGURATION', source_runtime_state('GITHUB_DISCUSSIONS'))
with env(GITHUB_TOKEN=None, SIGNALFORGE_GITHUB_DISCUSSION_REPOS='owner/repo'):
    check('GitHub Discussions repo allowlist without token is pending credential', source_runtime_state('GITHUB_DISCUSSIONS')['runtime_state']=='PENDING_CREDENTIAL')
with env(GITHUB_TOKEN='gh-secret', SIGNALFORGE_GITHUB_DISCUSSION_REPOS='owner/repo,bad repo/nope,Owner/Repo'):
    cfg=github_discussion_repos()
    check('GitHub Discussions repo parser is explicit and deduped', cfg==[{'owner':'Owner','repo':'Repo'}] or cfg==[{'owner':'owner','repo':'repo'}], cfg)

# HN search -> item tree comments.
old_loop_json=loop._request_json
hn_calls=[]
def hn_json(url, **kwargs):
    hn_calls.append(url)
    if '/api/v1/search?' in url:
        return {'hits':[{'title':'Agent memory pain','story_text':'Developers manually repeat repository rules','objectID':'100','author':'a','created_at':'2026-09-06','num_comments':2}]},{'status_code':200}
    if '/api/v1/items/100' in url:
        return {'id':100,'children':[{'id':101,'parent_id':100,'author':'b','created_at':'2026-09-06','text':'We still paste instructions manually every run.','children':[{'id':102,'parent_id':101,'author':'c','created_at':'2026-09-06','text':'We pay for the assistant but the workaround remains manual.','children':[]}]}]},{'status_code':200}
    raise AssertionError(url)
loop._request_json=hn_json
try: hn=loop._search_hn('AI coding agent repository rules memory')
finally: loop._request_json=old_loop_json
units=[x.get('content_unit') for x in hn['traces']]
check('HN expands matched story into first-class comment traces', units.count('COMMENT')==2 and 'POST' in units, units)
check('HN story and descendants share one independence group', {x.get('metadata',{}).get('independence_group_key') for x in hn['traces']}=={'hn:100'})
check('HN child endpoint is bounded separate depth transport', any('/api/v1/items/100' in x for x in hn_calls) and len(hn_calls)==2, hn_calls)

def hn_depth_fail(url, **kwargs):
    if '/api/v1/search?' in url:
        return {'hits':[{'title':'Agent pain','story_text':'manual rules','objectID':'200','num_comments':5}]},{'status_code':200}
    raise loop.FetchError('depth unavailable')
loop._request_json=hn_depth_fail
try: hnf=loop._search_hn('agent memory')
finally: loop._request_json=old_loop_json
check('HN depth failure does not erase successful parent search', hnf['status']=='SUCCESS' and hnf['count']==1 and hnf['transport']['depth'][0]['status']=='PARTIAL', hnf['transport'])

# Stack Overflow question -> answers + comments.
stack_calls=[]
def stack_json(url, **kwargs):
    stack_calls.append(url)
    if 'search/advanced' in url:
        return {'items':[{'question_id':11,'title':'Agent forgets project rules','body':'We manually repeat instructions','tags':['ai'],'link':'https://stackoverflow.com/q/11','owner':{'display_name':'dev'},'creation_date':1,'score':5,'answer_count':1,'is_answered':True}], 'quota_remaining':250},{'status_code':200}
    if '/questions/11/answers?' in url:
        return {'items':[{'answer_id':21,'question_id':11,'body':'Use a rules file workaround','owner':{'display_name':'ans'},'creation_date':2,'score':4,'is_accepted':True}]},{'status_code':200}
    if '/questions/11/comments?' in url:
        return {'items':[{'comment_id':31,'post_id':11,'body':'Still breaks after compaction','owner':{'display_name':'qcom'},'creation_date':3,'score':2}]},{'status_code':200}
    if '/answers/21/comments?' in url:
        return {'items':[{'comment_id':41,'post_id':21,'body':'This workaround is still manual','owner':{'display_name':'acom'},'creation_date':4,'score':1}]},{'status_code':200}
    raise AssertionError(url)
loop._request_json=stack_json
try: st=loop._search_stackoverflow('AI coding agent repository rules memory')
finally: loop._request_json=old_loop_json
sunits=[x.get('content_unit') for x in st['traces']]
check('Stack Overflow expands question into answer and both comment layers', {'QUESTION','ANSWER','COMMENT'}.issubset(set(sunits)) and sunits.count('COMMENT')==2, sunits)
check('Stack Overflow whole Q/A conversation shares independence group', {x.get('metadata',{}).get('independence_group_key') for x in st['traces']}=={'stackoverflow:11'}, [x.get('metadata') for x in st['traces']])
check('Stack Exchange depth uses documented question answer/comment endpoints', any('/questions/11/answers?' in x for x in stack_calls) and any('/questions/11/comments?' in x for x in stack_calls) and any('/answers/21/comments?' in x for x in stack_calls), stack_calls)

# GitHub issues -> issue comments.
gh_calls=[]
def gh_json(url, **kwargs):
    gh_calls.append(url)
    if '/search/issues?' in url:
        return {'items':[{'number':9,'title':'Agent loses instructions','body':'Manual re-check every run','html_url':'https://github.com/acme/agent/issues/9','user':{'login':'lead'},'created_at':'2026-09-06','comments':2,'state':'open','repository_url':'https://api.github.com/repos/acme/agent'}]},{'status_code':200}
    if '/repos/acme/agent/issues/9/comments?' in url:
        return {'items':[{'id':501,'body':'We pay for the tool but still verify manually.','html_url':'https://github.com/acme/agent/issues/9#issuecomment-501','user':{'login':'buyer'},'created_at':'2026-09-06','author_association':'MEMBER'}]},{'status_code':200}
    raise AssertionError(url)
loop._request_json=gh_json
try: gi=loop._search_github_issues('AI coding agent repository rules memory')
finally: loop._request_json=old_loop_json
check('GitHub issue search expands into issue comments', [x.get('content_unit') for x in gi['traces']]==['ISSUE','ISSUE_COMMENT'], gi['traces'])
check('GitHub issue and comments share one conversation independence group', {x.get('metadata',{}).get('independence_group_key') for x in gi['traces']}=={'github-issue:acme/agent:9'})
check('GitHub comments request is bounded and official repo issue endpoint', any('/repos/acme/agent/issues/9/comments?' in x and parse_qs(urlparse(x).query).get('per_page')==['30'] for x in gh_calls), gh_calls)

# GitHub Discussions GraphQL configurable source.
old_post=adapters._request_json_post
graph_calls=[]
def graph_post(url,payload,*,headers=None,timeout=6.0):
    graph_calls.append((url,payload,dict(headers or {})))
    return {'data':{'repository':{'discussions':{'nodes':[{
        'id':'D1','number':7,'title':'Agent memory and repository rules','body':'Our team repeats rules manually after context resets.','url':'https://github.com/acme/agent/discussions/7','createdAt':'2026-09-06','updatedAt':'2026-09-06','author':{'login':'maintainer'},
        'comments':{'nodes':[{'id':'C1','body':'Same issue here, paid tools still need manual verification.','url':'https://github.com/acme/agent/discussions/7#discussioncomment-1','createdAt':'2026-09-06','author':{'login':'user'},'replies':{'nodes':[{'id':'R1','body':'We use a checklist workaround.','url':'https://github.com/acme/agent/discussions/7#discussioncomment-2','createdAt':'2026-09-06','author':{'login':'user2'}}]}}]}
    }]}}}}, {'status_code':200}
with env(GITHUB_TOKEN='gh-secret',SIGNALFORGE_GITHUB_DISCUSSION_REPOS='acme/agent'):
    adapters._request_json_post=graph_post
    try: gd=adapters.search_github_discussions('agent memory repository rules')
    finally: adapters._request_json_post=old_post
check('GitHub Discussions adapter emits discussion comment reply content units', {x['content_unit'] for x in gd['traces']}=={'DISCUSSION','DISCUSSION_COMMENT','DISCUSSION_REPLY'}, gd['traces'])
check('GitHub Discussions all descendants share explicit conversation group', {x['metadata']['independence_group_key'] for x in gd['traces']}=={'github-discussion:acme/agent:D1'})
check('GitHub GraphQL adapter is read-only and never echoes token', graph_calls[0][2].get('Authorization')=='Bearer gh-secret' and 'gh-secret' not in json.dumps(gd) and 'mutation' not in str(graph_calls[0][1]).lower())
with env(GITHUB_TOKEN='gh-secret',SIGNALFORGE_GITHUB_DISCUSSION_REPOS='acme/agent'):
    plan=plan_source_expansion('AI coding agent repository rules and context memory')
check('Developer source planner selects configured GitHub Discussions', 'GITHUB_DISCUSSIONS' in set(plan['selected_source_ids']), plan['selected_source_ids'])

# YouTube incomplete inline replies -> comments.list(parentId) completion.
old_yjson=adapters._request_json
yt_calls=[]
def yt_json(url, **kwargs):
    yt_calls.append(url)
    if '/search?' in url:
        return {'items':[{'id':{'videoId':'v1'},'snippet':{'title':'Taiwan GSAT English writing','description':'Exam students discuss English output practice','channelTitle':'Teacher','publishedAt':'2026-09-06','channelId':'ch'}}]},{'status_code':200}
    if '/commentThreads?' in url:
        return {'items':[{'snippet':{'totalReplyCount':3,'topLevelComment':{'id':'top1','snippet':{'textDisplay':'Students struggle to write under exam time pressure','authorDisplayName':'s1','publishedAt':'2026-09-06','likeCount':4}}},'replies':{'comments':[{'id':'r1','snippet':{'textDisplay':'Same here','authorDisplayName':'s2','publishedAt':'2026-09-06','parentId':'top1'}}]}}]},{'status_code':200}
    if '/comments?' in url:
        return {'items':[{'id':'r1','snippet':{'textDisplay':'Same here','authorDisplayName':'s2','publishedAt':'2026-09-06','parentId':'top1'}},{'id':'r2','snippet':{'textDisplay':'Translation output is also hard','authorDisplayName':'s3','publishedAt':'2026-09-06','parentId':'top1'}},{'id':'r3','snippet':{'textDisplay':'We practice manually every week','authorDisplayName':'s4','publishedAt':'2026-09-06','parentId':'top1'}}]},{'status_code':200}
    raise AssertionError(url)
with env(YOUTUBE_API_KEY='yt-secret',SIGNALFORGE_YOUTUBE_MAX_REPLY_READS_PER_VIDEO='10',SIGNALFORGE_YOUTUBE_MAX_REPLY_PAGES_PER_THREAD='2'):
    adapters._request_json=yt_json
    try: yt=adapters.search_youtube('Taiwan GSAT English output students')
    finally: adapters._request_json=old_yjson
check('YouTube completes replies when inline commentThreads replies are partial', len([x for x in yt['traces'] if x['content_unit']=='COMMENT_REPLY'])==3, [x['metadata'] for x in yt['traces']])
check('YouTube uses comments.list parentId for missing replies', any('/comments?' in x and parse_qs(urlparse(x).query).get('parentId')==['top1'] for x in yt_calls), yt_calls)
check('YouTube inline/full reply merge dedupes same reply ID', len({x['metadata'].get('comment_id') for x in yt['traces'] if x['content_unit']=='COMMENT_REPLY'})==3)
check('YouTube reply depth has explicit quota caps and no key leakage', yt['transport']['reply_depth_contract']['max_reply_reads_per_video']==10 and 'yt-secret' not in json.dumps(yt), yt['transport']['reply_depth_contract'])

# Cross-source mirror / recurrence hardening.
long_text='Client opportunity research takes too long and our team manually verifies every evidence source before sending a proposal to the buyer.'
raw=[
 {'source':'BRAVE_WEB','source_family':'BRAVE_WEB','content_unit':'WEB_PAGE','title':'Agency research pain','excerpt':long_text,'url':'https://example.com/a?utm_source=x','metadata':{}},
 {'source':'RSS_ATOM','source_family':'PUBLIC_FEEDS','content_unit':'FEED_ITEM','title':'Agency research pain','excerpt':long_text,'url':'https://mirror.example.net/story','metadata':{}},
]
dedup,clusters=dedupe_and_cluster_traces(raw)
check('Wave3 exact long-text mirror dedupes across different URLs/sources', len(dedup)==1, dedup)
raw2=[
 {'source':'YOUTUBE_DATA_API','source_family':'YOUTUBE','content_unit':'COMMENT_REPLY','title':'Reply','excerpt':'We still verify client research manually because evidence is hard to trust.','url':'https://youtube.com/watch?v=v&lc=a','metadata':{'independence_group_key':'youtube:v:comment:top'}},
 {'source':'YOUTUBE_DATA_API','source_family':'YOUTUBE','content_unit':'COMMENT_REPLY','title':'Reply','excerpt':'We still verify client research by hand because the evidence remains hard to trust.','url':'https://youtube.com/watch?v=v&lc=b','metadata':{'independence_group_key':'youtube:v:comment:top'}},
]
d2,c2=dedupe_and_cluster_traces(raw2)
check('Wave3 preserves thread-level independence group on child observations', all(x['metadata']['independence_group_key']=='youtube:v:comment:top' for x in d2), d2)
check('Wave3 never upgrades clusters into recurrence authority', all(x['metadata']['recurrence_authority']=='NONE_UNTIL_EXPLICIT_SOURCE_INDEPENDENCE_VALIDATION' for x in d2) and all(c['independence_status']=='UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE' for c in c2), c2)

# Relevance gate applies after depth too.
fresh={
 'status':'PASS','founder_query':'English Output Trainer for Taiwan Exam Students','sources':[{'source':'GITHUB_ISSUES','status':'SUCCESS','count':2,'traces':[]}],
 'traces':[
   loop._make_trace(source='GITHUB_SEARCH',kind='DISCUSSION',title='GPT bot repository comment',excerpt='New repository automation bot launched.',url='https://github.com/a/b/issues/1#issuecomment-1',metadata={'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:a/b:1'}),
   loop._make_trace(source='GITHUB_SEARCH',kind='DISCUSSION',title='Taiwan GSAT student English writing',excerpt='Taiwan students struggle to produce English writing and translation under exam time pressure.',url='https://github.com/a/b/issues/2#issuecomment-2',metadata={'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:a/b:2'}),
 ],
 'language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE'
}
sm=loop.summarize_fresh_probe(fresh)
check('Deep child traces still pass thesis relevance before counters', sm['relevant_trace_count']==1 and sm['problem_discussions']==1, sm)

# Source/security authority inspection.
ad_src=(ROOT/'processors/signalforge_source_adapters.py').read_text(encoding='utf-8')
loop_src=(ROOT/'processors/signalforge_founder_idea_loop.py').read_text(encoding='utf-8')
exp_src=(ROOT/'processors/signalforge_source_expansion.py').read_text(encoding='utf-8')
check('Wave3 depth layer imports no Market Ground Truth authority', 'market_ground_truth' not in ad_src and 'market_ground_truth' not in loop_src)
check('Wave3 adds no browser session cookie VPN CAPTCHA shortcuts', all(x not in (ad_src+loop_src).lower() for x in ['selenium','playwright','browser_cookie','vpn_password','captcha_solver']))
check('Wave3 source expansion remains UNVALIDATED and recurrence-fail-closed', 'UNVALIDATED_SEARCH_TRACE' in ad_src and 'CLUSTERS_DO_NOT_CREATE_INDEPENDENT_RECURRENCE' in exp_src)

passed=sum(1 for _,ok,_ in results if ok)
print('-'*108)
print(f'RESULT: {passed}/{len(results)} PASS')
if passed!=len(results): raise SystemExit(1)
print('FINAL_STATUS: SIGNALFORGE_SOURCE_EXPANSION_WAVE3_ACCEPTANCE_PASS')
