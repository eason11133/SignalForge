from __future__ import annotations

import asyncio
import os
from urllib.parse import parse_qs, urlparse

import processors.signalforge_founder_idea_loop as sf

IDEA = "AI coding agents 完成工作後，使用者很難快速確認它到底有沒有真的做對、做完"

calls: list[str] = []

def fake_request_json(url: str, **kwargs):
    calls.append(url)
    p = urlparse(url)
    qs = parse_qs(p.query)
    if 'hn.algolia.com' in p.netloc and p.path.endswith('/api/v1/search') and qs.get('tags') == ['comment']:
        return {"hits": [{
            "objectID": "49317798",
            "story_id": "49317589",
            "story_title": "Is this the end of human code review?",
            "comment_text": "Think we are close to the point where we will no longer need to prompt AI to refactor or review the refactoring if it is done within tight constraints. But when functionality changes may be acceptable as part of it, it is less clear - in my experience AI is not at a point yet where it can always be trusted to understand what the requirements are. That is where human review is still useful and in many cases essential.",
            "author": "alertchecker",
            "created_at": "2026-08-16T07:46:26.000Z",
        }, {
            "objectID": "49576060",
            "story_id": "49572875",
            "story_title": "GPT-6 Astra in code review: Gains, privacy, and cost",
            "comment_text": "The AI code review tool has poor results and is not worth the noise and friction it causes developers.",
            "author": "critic",
            "created_at": "2026-09-06T12:00:00Z",
        }]}, {"status_code": 200, "elapsed_ms": 4}
    if 'hn.algolia.com' in p.netloc and p.path.endswith('/api/v1/search'):
        return {"hits": [{
            "objectID": "47217890", "story_id": "47217890",
            "title": "Show HN: AgentTeams – Traceable AI coding workflows",
            "story_text": "AI coding agents ship code quickly. AgentTeams adds completion reports and verification summaries.",
            "author": "rlarua", "created_at": "2026-03-02T13:45:50Z", "points": 2, "num_comments": 0,
        }, {
            "objectID": "48931713", "story_id": "48931713",
            "title": "The Missed Reality: Code Review Wasn't Built for the AI Era",
            "story_text": "AI generates code faster than our capacity to review it. Reviewers rarely verify whether original acceptance criteria were met or whether an agent deviated from scope.",
            "author": "axsdrizz", "created_at": "2026-08-01T00:00:00Z", "points": 2, "num_comments": 5,
        }]}, {"status_code": 200, "elapsed_ms": 4}
    if 'hn.algolia.com' in p.netloc and '/api/v1/items/' in p.path:
        sid = p.path.rsplit('/', 1)[-1]
        titles = {
            "49317589": "Is this the end of human code review?",
            "49572875": "GPT-6 Astra in code review: Gains, privacy, and cost",
            "48931713": "The Missed Reality: Code Review Wasn't Built for the AI Era",
            "47217890": "Show HN: AgentTeams – Traceable AI coding workflows",
        }
        return {"id": sid, "title": titles.get(sid, "HN discussion"), "children": []}, {"status_code": 200, "elapsed_ms": 3}
    if 'api.stackexchange.com' in p.netloc:
        return {"items": [], "quota_remaining": 200}, {"status_code": 200, "elapsed_ms": 3}
    if 'api.github.com' in p.netloc and p.path == '/search/issues':
        return {"items": []}, {"status_code": 200, "elapsed_ms": 3}
    if 'api.github.com' in p.netloc and p.path == '/search/repositories':
        return {"items": [{
            "full_name": "ShreyaKulkarni-projects/groundtruth",
            "name": "groundtruth",
            "description": "A verification layer for AI coding agents that checks claimed completion against real tests and diffs.",
            "html_url": "https://github.com/ShreyaKulkarni-projects/groundtruth",
            "owner": {"login": "ShreyaKulkarni-projects"},
            "stargazers_count": 3, "forks_count": 0, "language": "Python", "license": {"spdx_id": "MIT"},
        }]}, {"status_code": 200, "elapsed_ms": 3}
    raise AssertionError(f"unhandled URL {url}")

def fake_expansion(hypothesis, queries, max_queries=3):
    # Mirror the user's current environment: optional expansion sources can fail,
    # but useful base-source evidence should still be returned as ready.
    return {
        "sources": [
            {"source": "GDELT_DOC", "status": "FAILED", "count": 0, "error": "timeout", "traces": []},
            {"source": "BLUESKY_PUBLIC_SEARCH", "status": "FAILED", "count": 0, "error": "HTTP 403", "traces": []},
        ],
        "traces": [],
    }

orig_request = sf._request_json
orig_expansion = sf.run_source_expansion_queries
old_llm = os.environ.get('SIGNALFORGE_USE_LLM_RELEVANCE')
os.environ['SIGNALFORGE_USE_LLM_RELEVANCE'] = '0'
sf._request_json = fake_request_json
sf.run_source_expansion_queries = fake_expansion
try:
    result = asyncio.run(sf.probe_founder_idea(title=IDEA))
finally:
    sf._request_json = orig_request
    sf.run_source_expansion_queries = orig_expansion
    if old_llm is None:
        os.environ.pop('SIGNALFORGE_USE_LLM_RELEVANCE', None)
    else:
        os.environ['SIGNALFORGE_USE_LLM_RELEVANCE'] = old_llm

brief = result.get('research_brief') or {}
summary = brief.get('summary') or {}
errors: list[str] = []
if result.get('status') != 'RESEARCH_READY':
    errors.append(f"status={result.get('status')}")
if int(summary.get('human_comment_count') or 0) < 1:
    errors.append('no human comment')
if int(summary.get('product_or_service_count') or 0) < 1:
    errors.append('no product/pitch')
if int(summary.get('repo_solution_count') or 0) < 1:
    errors.append('no repo solution')
if int(summary.get('supporting_evidence_count') or 0) < 1:
    errors.append('no supporting evidence')
if int(summary.get('counter_evidence_count') or 0) < 1:
    errors.append('no counter evidence')
if not any(x.get('url') == 'https://news.ycombinator.com/item?id=49317798' for x in brief.get('human_comments') or []):
    errors.append('captured HN comment missing from Founder brief')
if not any(x.get('url') == 'https://news.ycombinator.com/item?id=47217890' for x in brief.get('similar_products') or []):
    errors.append('AgentTeams root missing from product lane')
if any(x.get('url') == 'https://news.ycombinator.com/item?id=47217890' for x in brief.get('human_comments') or []):
    errors.append('AgentTeams root leaked into human comments')
if not any('tags=comment' in x for x in calls):
    errors.append('HN comment recall query never executed')

print('E2E_STATUS', result.get('status'))
print('E2E_COUNTS', {
    'comments': summary.get('human_comment_count'),
    'products': summary.get('product_or_service_count'),
    'repos': summary.get('repo_solution_count'),
    'supporting': summary.get('supporting_evidence_count'),
    'counter': summary.get('counter_evidence_count'),
})
print('E2E_HN_RECALL', next((u for u in calls if 'tags=comment' in u), None))
print('E2E_GAPS', brief.get('gaps'))
if errors:
    print('E2E_FAILED', errors)
    raise SystemExit(1)
print('E2E_REPLAY_OK')
