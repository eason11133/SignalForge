from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# The repair package is an overlay. In the real repository, use the actual
# unchanged dependencies so import/integration defects are visible. Only the
# package-only preflight (where those files are genuinely absent) gets zero-
# authority stubs.
if (ROOT / 'processors/signalforge_money_trail.py').is_file():
    import processors.signalforge_money_trail  # noqa: F401
else:
    money = types.ModuleType('processors.signalforge_money_trail')
    async def _money_probe(*, title: str, description: str = ''):
        return {
            'status': 'NO_PUBLISHED_MATCH',
            'revenue_wedge': {'recommendation': 'INVESTIGATE'},
            'paid_dissatisfaction': {'count': 0},
            'existing_spend': {'strength': 'UNKNOWN'},
        }
    def _spend(_row): return []
    def _pd(_row): return None
    def _playbook(**_kwargs): return {'status': 'STUB'}
    money.probe_money_trail_direction = _money_probe
    money.classify_spend_evidence = _spend
    money.detect_paid_dissatisfaction = _pd
    money.route_founder_playbook = _playbook
    sys.modules['processors.signalforge_money_trail'] = money

if (ROOT / 'processors/signalforge_founder_hypothesis_registry.py').is_file():
    import processors.signalforge_founder_hypothesis_registry  # noqa: F401
else:
    registry = types.ModuleType('processors.signalforge_founder_hypothesis_registry')
    registry.record_founder_hypothesis_probe = lambda **_kwargs: {'status': 'STUB_NO_MARKET_AUTHORITY', 'market_truth_writes': 0}
    sys.modules['processors.signalforge_founder_hypothesis_registry'] = registry

from processors import signalforge_founder_idea_loop as loop
from processors import signalforge_source_adapters as adapters

RESULTS: list[tuple[str, bool, object]] = []
def check(name: str, cond: object, detail: object = None) -> None:
    ok = bool(cond)
    RESULTS.append((name, ok, detail))
    print(('PASS' if ok else 'FAIL'), name, '' if detail is None else '— ' + str(detail))

TITLE = 'AI coding agents finish work but founders cannot efficiently verify whether the work is actually correct and complete'
DESC = 'Founders using Claude Code, Codex or similar coding agents need to verify requirements, tests and actual completion without manually reviewing everything'
HYPOTHESIS = f'{TITLE} {DESC}'

# Exact live failure examples.
fp_music = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title="AI coding made me faster, but I can't code to music anymore",
    excerpt='It definitely changed how I get into flow state. I fire off agents to work on different parts of the code, then the agents complete and finish while I map bigger tasks, then I review smaller tasks. The complaint is that music and flow state are harder while juggling agents.',
    url='https://news.ycombinator.com/item?id=music', author='music_user',
    metadata={'content_unit':'POST','independence_group_key':'hn:music'},
)
fp_spit = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='Show HN: Spit Notes – An iOS app that keeps your lyrics and voice memos together',
    excerpt='A notes app for lyrics and voice memos.', url='https://news.ycombinator.com/item?id=spit', author='spit',
    metadata={'content_unit':'POST','independence_group_key':'hn:spit'},
)
fp_gtm = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='Show HN: Cantrip – Agent-native GTM engine I built for solo technical founders',
    excerpt='A solo technical founder built a go-to-market engine. Selling software is the hard part. The product builds a persistent business context graph and helps find customers; it is not about verifying whether coding-agent work satisfies requirements or tests.', url='https://news.ycombinator.com/item?id=gtm', author='gtm',
    metadata={'content_unit':'POST','independence_group_key':'hn:gtm'},
)
fp_insurance = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='The Hardest Document Extraction Problem in Insurance',
    excerpt='Insurance document extraction is difficult. The author recommends self-correction, checks, success criteria, and automatically verifying when an agent declares itself done. These are generic AI harness patterns inside an insurance-document workflow.',
    url='https://news.ycombinator.com/item?id=insurance', author='insurance',
    metadata={'content_unit':'POST','independence_group_key':'hn:insurance'},
)
fn_review = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION', title='Hacker News comment',
    excerpt='Think we are close to where we will no longer need to prompt AI to refactor or review refactoring within tight constraints. But when functionality changes, AI is not at a point yet where it can always be trusted to understand what the requirements are, what is acceptable in user experience, and human review is still useful and in many cases essential.',
    url='https://news.ycombinator.com/item?id=9001', author='reviewer',
    metadata={'story_id':'42','comment_id':'9001','content_unit':'COMMENT','independence_group_key':'hn:42'},
)

check('A Spit Notes is not specific completion-verification evidence', not loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_spit)['countable'])
check('B AI coding/music adjacency is not exact verification evidence', not loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_music)['countable'])
rel_fn = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fn_review)
check('C requirements/functionality/human-review comment is relevant', rel_fn['countable'] and 'REQUIREMENT_ADHERENCE' in rel_fn['compatibility']['specific_problem_dimensions'], rel_fn)
check('C false-negative no longer gets a synthetic domain conflict from query-lens aliases', rel_fn['compatibility'].get('domain_conflict') is False, rel_fn)
check('Broad agent/founder adjacency alone is insufficient', not loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_gtm)['countable'])
check('Insurance document-extraction adjacency is not completion-verification evidence', not loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_insurance)['countable'])


# Founder human-review closure regressions: workflow/object identity must be
# general, not URL/repository blacklists.
fp_build_agent = loop._make_trace(
    source='STACK_OVERFLOW_API', kind='DISCUSSION',
    title='MSBuild deployment comment',
    excerpt='Please share entire log, as well as your MSBuild argument. Also, you need to check the permission which runs the build agent. Use MSBuild command line to deploy your project.',
    url='https://stackoverflow.com/questions/38639029#comment-64685691_38639029', author='so-user',
    metadata={'question_id':'38639029','content_unit':'COMMENT','independence_group_key':'stackoverflow:38639029'},
)
fp_doc_review = loop._make_trace(
    source='GITHUB_SEARCH', kind='DISCUSSION',
    title='Automated AgentSpace document quality review',
    excerpt='AI quality review: markdown formatting is incomplete, references and URLs are missing, license/version metadata is absent, and API, security, test and CI documentation sections need completion.',
    url='https://github.com/example/project/issues/317#issuecomment-doc', author='review-bot',
    metadata={'repository':'example/project','issue_number':317,'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:example/project:317'},
)
positive_agentteams = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='AgentTeams – Traceable AI coding workflows',
    excerpt='AI coding agents ship code quickly. Every task has a plan and a completion report with verification summary, tests and evidence so reviewers can verify the implementation before accepting the change.',
    url='https://news.ycombinator.com/item?id=agentteams', author='builder',
    metadata={'content_unit':'POST','independence_group_key':'hn:agentteams'},
)
build_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_build_agent)
doc_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_doc_review)
agentteams_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=positive_agentteams)
check('Founder closure: MSBuild build-agent permission comment is irrelevant', not build_rel['countable'] and build_rel['gate'] == 'INCOMPATIBLE_AGENT_WORKFLOW', build_rel)
check('Founder closure: documentation-quality review is irrelevant', not doc_rel['countable'] and doc_rel['compatibility'].get('workflow_identity_compatible') is False, doc_rel)
check('Founder closure: AgentTeams traceable coding workflow remains eligible', agentteams_rel['countable'] and agentteams_rel['compatibility'].get('workflow_identity_compatible') is True, agentteams_rel)
check('Founder closure: requirements/human-review HN comment keeps AI coding implementation identity', rel_fn['countable'] and rel_fn['compatibility'].get('workflow_identity_compatible') is True, rel_fn)

# Final narrow closure: documentation object dominance and ambiguous "correct"
# must not inflate exact AI-coding verification relevance.
fp_doc_review_live_like = loop._make_trace(
    source='GITHUB_SEARCH', kind='DISCUSSION',
    title='Comment on AgentSpace self-hosted agent documentation request',
    excerpt='AI quality review result: the documentation has mixed language and formatting, missing references and URLs, license/version metadata gaps, incomplete API and security sections, and insufficient test/CI documentation. The Pull Request procedure and code examples also need clearer documentation.',
    url='https://github.com/example/project/issues/317#issuecomment-live-like', author='review-bot',
    metadata={'repository':'example/project','issue_number':317,'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:example/project:317'},
)
fp_manual_correction = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION', title='Hacker News comment',
    excerpt='I let the AI first generate an outline in markdown. I correct these all, then I let the AI generate the classes of the outline one by one.',
    url='https://news.ycombinator.com/item?id=manual-correction', author='user',
    metadata={'content_unit':'COMMENT','independence_group_key':'hn:manual-correction'},
)
positive_mixed_docs_impl = loop._make_trace(
    source='GITHUB_SEARCH', kind='ISSUE', title='AI coding agent changed implementation and docs',
    excerpt='Claude Code implemented the feature and changed the code. It also updated the README. Before acceptance, we verified the real diff, tests and requirements because the agent had previously skipped work.',
    url='https://github.com/example/project/issues/impl-docs', author='maintainer',
    metadata={'content_unit':'ISSUE','independence_group_key':'github-issue:example/project:impl-docs'},
)
live_doc_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_doc_review_live_like)
manual_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_manual_correction)
mixed_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=positive_mixed_docs_impl)
check('Final closure: live-like documentation QA is dominated by DOCUMENTATION', not live_doc_rel['countable'] and live_doc_rel['compatibility'].get('trace_dominant_object') == 'DOCUMENTATION', live_doc_rel)
check('Final closure: manual correction alone is adjacent/non-exact', not manual_rel['countable'], manual_rel)
check('Final closure: real implementation + docs remains exact when implementation relationship is explicit', mixed_rel['countable'] and mixed_rel['compatibility'].get('trace_dominant_object') != 'DOCUMENTATION', mixed_rel)

# R6 regression from the actual live failure shape. This is intentionally content-
# based rather than URL/repository-based: multilingual documentation QA with an
# incidental Pull Request/CI/API mention must remain documentation, not software
# implementation.
fp_multilingual_doc_review = loop._make_trace(
    source='GITHUB_SEARCH', kind='DISCUSSION',
    title='Agent project documentation quality review',
    excerpt='자동 품질 검토 결과: 문서는 설치·운영 가이드와 API 설명을 다루지만 언어 혼용, 인용 URL 누락, 라이선스·버전 정보 누락, CI·테스트 파이프라인 설명 부족이 있습니다. Pull Request 절차와 코드 예시는 문서 보완 항목입니다.',
    url='https://github.com/example/project/issues/multilingual-doc-review', author='review-bot',
    metadata={'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:example/project:multilingual-doc-review'},
)
multilingual_doc_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_multilingual_doc_review)
check(
    'R6 multilingual documentation QA cannot manufacture software implementation identity',
    not multilingual_doc_rel['countable']
    and multilingual_doc_rel['compatibility'].get('trace_dominant_object') == 'DOCUMENTATION'
    and multilingual_doc_rel['compatibility'].get('trace_explicit_implementation_evidence') is False,
    multilingual_doc_rel,
)

fp_coordination_board = loop._make_trace(
    source='GITHUB_SEARCH', kind='DISCUSSION',
    title='Claude Coordination Board',
    excerpt='Claude Code session coordination board: touching settings, skills docs and workflow metadata; holding a PR with correctness fixes for an operator merge nod.',
    url='https://github.com/example/project/issues/coordination-board', author='claude',
    metadata={'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:example/project:coordination-board'},
)
coordination_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_coordination_board)
check(
    'R6 coordination/documentation chatter is non-exact without direct implementation evidence',
    not coordination_rel['countable'],
    coordination_rel,
)

# R7: an agent-generated DONE/status artifact is not a human market conversation.
# The actual live R6 primary trace ended with an explicit Claude Code generation
# footer and was incorrectly counted as a PROBLEM_DISCUSSION.
fp_agent_generated_done = loop._make_trace(
    source='GITHUB_SEARCH', kind='DISCUSSION',
    title='Claude Coordination Board',
    excerpt='✅ DONE · session_01PKEYK1 · branch `claude/system-health-review-rk852g` Repo: ict-trading-bot Shipped: #6926 correctness fixes — merged + deployed + live-verified. Area now clear. --- _Generated by [Claude Code](https://claude.ai/code)_',
    url='https://github.com/example/project/issues/6927#issuecomment-agent-done', author='automation',
    metadata={'content_unit':'ISSUE_COMMENT','independence_group_key':'github-issue:example/project:6927'},
)
agent_done_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_agent_generated_done)
check(
    'R7 explicit Claude Code generated DONE artifact is not human market evidence',
    not agent_done_rel['countable']
    and agent_done_rel['gate'] == 'AUTOMATED_OUTPUT_NOT_HUMAN_MARKET_CONVERSATION'
    and agent_done_rel['compatibility'].get('trace_automated_operational_output') is True,
    agent_done_rel,
)

positive_human_claim_review = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='Coding agent says done but I still verify it',
    excerpt='Claude Code says the feature is done, but I still inspect the diff and rerun acceptance tests because I cannot trust the completion claim to match the requirements.',
    url='https://news.ycombinator.com/item?id=human-claim-review', author='founder',
    metadata={'content_unit':'COMMENT','independence_group_key':'hn:human-claim-review'},
)
human_claim_rel = loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=positive_human_claim_review)
check(
    'R7 human complaint about an agent completion claim remains exact relevant',
    human_claim_rel['countable']
    and human_claim_rel['compatibility'].get('trace_automated_operational_output') is False,
    human_claim_rel,
)

# Mid-text product prose about automatic report generation must not trigger the
# footer detector. This protects AgentTeams and similar human-written discussions.
check(
    'R7 human AgentTeams discussion is not mistaken for automated output',
    agentteams_rel['countable']
    and agentteams_rel['compatibility'].get('trace_automated_operational_output') is False,
    agentteams_rel,
)

# Live-like border cases: status/orchestration chatter must not become correctness evidence,
# while explicit requirement/test/reviewer evidence must remain countable.
fp_remote = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='CCBot – remote control over AI coding agents',
    excerpt='The agent keeps working while you are away. You miss when it finishes or gets stuck, so the bot shows status and lets you send keystrokes remotely.',
    url='https://news.ycombinator.com/item?id=remote', author='remote',
    metadata={'content_unit':'POST','independence_group_key':'hn:remote'},
)
valid_gate = loop._make_trace(
    source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION',
    title='Different-model reviewer blocks bad AI coding changes',
    excerpt='A second model reviews the change, catches bugs that self-review misses, checks tests and requirements, and can block apply when verification finds a critical issue.',
    url='https://news.ycombinator.com/item?id=review-gate', author='builder',
    metadata={'content_unit':'POST','independence_group_key':'hn:review-gate'},
)
check('Agent status/remote-control workflow is not correctness verification evidence', not loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=fp_remote)['countable'])
check('Explicit reviewer + bugs + tests + requirements remains relevant', loop.classify_trace_relevance(hypothesis_text=HYPOTHESIS, trace=valid_gate)['countable'])

# Generalization guard: the mechanism must work on a different job/domain, not
# special-case the coding-agent sentence.
RFQ_HYPOTHESIS = 'Procurement teams manually compare supplier PDF and Excel quotes and need to normalize specifications prices delivery and terms'
rfq_relevant = loop._make_trace(
    source='STACK_EXCHANGE_NETWORK', kind='DISCUSSION',
    title='Supplier quotation comparison is still manual',
    excerpt='Our procurement team normalizes vendor RFQ quotes and delivery terms in Excel before we can compare them.',
    url='https://workplace.stackexchange.com/q/1', author='buyer',
    metadata={'content_unit':'QUESTION','independence_group_key':'stackexchange:workplace:q:1'},
)
rfq_unrelated = loop._make_trace(
    source='GITHUB_ISSUES', kind='ISSUE',
    title='AI code review agent missed a test',
    excerpt='The coding agent said it was complete but QA found a regression.',
    url='https://github.com/x/y/issues/2', author='dev',
    metadata={'issue_number':2,'independence_group_key':'github:x/y:issue:2'},
)
check('General semantic mechanism recognizes an RFQ compare/normalize workflow', loop.classify_trace_relevance(hypothesis_text=RFQ_HYPOTHESIS, trace=rfq_relevant)['countable'])
check('General semantic mechanism rejects a different specific job despite AI/verification strength', not loop.classify_trace_relevance(hypothesis_text=RFQ_HYPOTHESIS, trace=rfq_unrelated)['countable'])

# Thread depth: five useful comments in one story remain inspectable but one recurrence.
thread_comments = [fn_review]
for i, text in enumerate([
    'Our AI coding agent says the software task is done, but we still verify the actual implementation completion before shipping.',
    'After the coding agent changes code, we use tests and acceptance criteria because claimed completion is not enough.',
    'Human code review is still required to check whether the coding agent implementation adheres to requirements.',
    'The hardest part is verifying correctness after the coding agent reports the code task finished.',
], start=2):
    thread_comments.append(loop._make_trace(
        source='HACKER_NEWS_ALGOLIA', kind='DISCUSSION', title='Hacker News comment', excerpt=text,
        url=f'https://news.ycombinator.com/item?id=900{i}', author=f'user{i}',
        metadata={'story_id':'42','comment_id':f'900{i}','content_unit':'COMMENT','independence_group_key':'hn:42'},
    ))

gh_issue = loop._make_trace(
    source='GITHUB_SEARCH', kind='ISSUE', title='Agent marks task complete before acceptance tests pass',
    excerpt='We need to verify requirements and test evidence because the coding agent reports completion too early.',
    url='https://github.com/example/agent/issues/1', author='maintainer',
    metadata={'repository':'example/agent','issue_number':1,'content_unit':'ISSUE','independence_group_key':'github:example/agent:issue:1'},
)
all_traces = [fp_music, fp_spit, fp_gtm, fp_insurance, fp_build_agent, fp_doc_review, *thread_comments, gh_issue]
fresh = {
    'founder_query': HYPOTHESIS,
    'status': 'PARTIAL',
    'language_coverage': 'SUPPORTED_BY_CURRENT_QUERY_BRIDGE',
    'sources': [
        {'source':'HACKER_NEWS_ALGOLIA','source_family':'HACKER_NEWS','status':'SUCCESS','count':9,'traces':[],'absence_adequacy':'FULL'},
        {'source':'GITHUB_ISSUES','source_family':'GITHUB_ISSUES','status':'SUCCESS','count':2,'traces':[],'absence_adequacy':'FULL'},
        {'source':'STACK_OVERFLOW_API','source_family':'STACK_OVERFLOW','status':'SUCCESS','count':1,'traces':[],'absence_adequacy':'FULL'},
        {'source':'GDELT_DOC','source_family':'GDELT_NEWS','status':'FAILED','count':0,'traces':[],'error':'TLS handshake timeout','absence_adequacy':'FULL'},
        {'source':'BLUESKY_PUBLIC_SEARCH','source_family':'BLUESKY','status':'FAILED','count':0,'traces':[],'error':'HTTP 403','absence_adequacy':'FULL'},
    ],
    'traces': all_traces,
}
summary = loop.summarize_fresh_probe(fresh)
check('D same HN story comments count as at most one independent discussion', summary['independent_discussion_count'] == 2, summary['source_contribution'])
check('Thread comments remain relevant depth evidence before primary selection', summary['source_contribution'][3]['relevant'] == 5 if len(summary['source_contribution']) > 3 and summary['source_contribution'][3].get('source') == 'HACKER_NEWS_ALGOLIA' else any(x.get('source')=='HACKER_NEWS_ALGOLIA' and x.get('relevant')==5 for x in summary['source_contribution']), summary['source_contribution'])
check('Founder primary selects one representative per independence group', len([x for x in summary['founder_primary_traces'] if (x.get('metadata') or {}).get('independence_group_key') == 'hn:42']) == 1, summary['founder_primary_traces'])
check('Founder primary has no repeated independence group', len({(x.get('metadata') or {}).get('independence_group_key') or x.get('url') for x in summary['founder_primary_traces']}) == len(summary['founder_primary_traces']), summary['founder_primary_traces'])
check('E Founder primary/top candidates contain only relevant traces', all((x.get('thesis_relevance') or {}).get('countable') for x in summary['founder_primary_traces']))
check('Garbage traces are excluded from Founder primary evidence', not any(x.get('title') in {fp_music['title'], fp_spit['title'], fp_gtm['title'], fp_insurance['title'], fp_build_agent['title'], fp_doc_review['title']} for x in summary['founder_primary_traces']))
check('F observation metrics expose raw/relevant/independent/unique-author/source contribution', all(k in summary for k in ('raw_trace_count','relevant_trace_count','independent_discussion_count','unique_author_count','source_contribution')), {k:summary[k] for k in ('raw_trace_count','relevant_trace_count','independent_discussion_count','unique_author_count')})
check('Source contribution separates HN raw/relevant/independent', any(x['source']=='HACKER_NEWS_ALGOLIA' and x['raw']==9 and x['relevant']==5 and x['independent_discussions']==1 for x in summary['source_contribution']), summary['source_contribution'])
check('Legacy GITHUB_SEARCH traces are attributed to explicit GitHub issue metrics', not any(x.get('source')=='GITHUB_SEARCH' for x in summary['source_contribution']) and any(x.get('source')=='GITHUB_ISSUES' and x.get('raw')==2 and x.get('relevant')==1 and x.get('independent_discussions')==1 for x in summary['source_contribution']), summary['source_contribution'])
check('Source failures remain visible separately', any(x['source']=='GDELT_DOC' and x['status']=='FAILED' for x in summary['source_health']))

# Merge path must preserve thread identity from Source Expansion.
base = {'status':'PASS','sources':[],'traces':[],'founder_query':HYPOTHESIS,'language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE'}
exp = {'status':'PASS','sources':[{'source':'LEMMY_PUBLIC','source_family':'LEMMY','status':'SUCCESS','traces':[{
    'source':'LEMMY_PUBLIC','kind':'DISCUSSION','title':'Agent verification','excerpt':'We verify tests before accepting agent completion.','url':'https://lemmy.world/post/7','author':'a',
    'metadata':{'content_unit':'POST','independence_group_key':'lemmy:post:7'},'truth_status':'UNVALIDATED_SEARCH_TRACE'
},{
    'source':'LEMMY_PUBLIC','kind':'DISCUSSION','title':'Comment','excerpt':'Human review is still needed for requirements.','url':'https://lemmy.world/comment/8','author':'b',
    'metadata':{'content_unit':'COMMENT','independence_group_key':'lemmy:post:7'},'truth_status':'UNVALIDATED_SEARCH_TRACE'
}]}], 'plan':{}, 'elapsed_ms':1}
merged = loop.merge_expansion_into_fresh(base, exp)
check('Source Expansion merge preserves independence_group_key', {x['metadata']['independence_group_key'] for x in merged['traces']} == {'lemmy:post:7'}, merged['traces'])

# Fresh-only No-Reddit boundary. Monkeypatch live retrieval; Published Money Trail stub
# would be visible if the observation-only path ever called it.
old_run = loop.run_founder_observation_probe
loop.run_founder_observation_probe = lambda _title, _description='': fresh
try:
    obs = loop.probe_founder_observation_only(title=TITLE, description=DESC)
finally:
    loop.run_founder_observation_probe = old_run
check('G fresh No-Reddit observation does not load historical Published Money Trail', obs['historical_published_evidence_used'] is False and obs['published_money_trail_used'] is False)
check('Fresh-only observation top_traces are relevance-gated', all((x.get('thesis_relevance') or {}).get('countable') for x in obs['fast_probe']['top_traces']))
check('H fresh-only market_truth_writes remains zero', obs['market_truth_writes'] == 0)

# Regular Founder flow must also use relevance-gated top_traces, while retaining
# Published context separately for backward compatibility.
loop.run_founder_observation_probe = lambda _title, _description='': fresh
try:
    regular = asyncio.run(loop.probe_founder_idea(title=TITLE, description=DESC))
finally:
    loop.run_founder_observation_probe = old_run
check('Regular Founder probe top_traces no longer bypass relevance gate', all((x.get('thesis_relevance') or {}).get('countable') for x in regular['fast_probe']['top_traces']))
check('Regular Published context stays separate/backward-compatible', 'published_money_trail' in regular and regular['market_truth_writes'] == 0)

# GDELT bounded retry: one transient NETWORK failure, then success.
old_json = adapters._request_json
calls = []
def flaky_json(url, **kwargs):
    calls.append(url)
    if len(calls) == 1:
        raise adapters.SourceAdapterError('TLS handshake timed out', category='NETWORK')
    return {'articles': []}, {'status_code': 200}
adapters._request_json = flaky_json
try:
    gdelt = adapters.search_gdelt(HYPOTHESIS)
finally:
    adapters._request_json = old_json
check('GDELT retries transient network failure at most once and succeeds', len(calls) == 2 and gdelt['transport']['attempts'] == 2, gdelt['transport'])

# Bluesky transport: official Bluesky AppView host used for unauthenticated search;
# no browser/cookie/auth bypass.
bsky_calls = []
def bsky_json(url, **kwargs):
    bsky_calls.append(url)
    return {'posts': []}, {'status_code': 200}
adapters._request_json = bsky_json
try:
    bsky = adapters.search_bluesky(HYPOTHESIS)
finally:
    adapters._request_json = old_json
check('Bluesky keeps the documented official public AppView host', bsky_calls and bsky_calls[0].startswith('https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?'), bsky_calls)
check('Bluesky 403 policy remains failure-visible with no authentication bypass', bsky['transport'].get('public_read') is True and bsky['transport'].get('search',{}).get('auth_used') is False and 'NO_BYPASS' in str(bsky['transport'].get('search',{}).get('access_contract') or ''))

passed = sum(1 for _, ok, _ in RESULTS if ok)
print('-' * 112)
print(f'RESULT: {passed}/{len(RESULTS)} PASS')
if passed != len(RESULTS):
    raise SystemExit(1)
print('ENGINEERING: PASS')
print('SEMANTIC: PASS')
print('LIVE: NOT_RUN_IN_PACKAGE_ACCEPTANCE')
print('FOUNDER: PENDING_LIVE_RETEST')
print('FINAL_STATUS: SIGNALFORGE_FOUNDER_OBSERVATION_QUALITY_REPAIR_DETERMINISTIC_PASS')
