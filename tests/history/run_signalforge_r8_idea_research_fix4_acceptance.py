from __future__ import annotations

from processors import signalforge_founder_idea_loop as sf

checks=[]
def ck(name, ok, detail=''):
    checks.append((name,bool(ok),str(detail)))
    print(('GREEN' if ok else 'RED  '), name, detail)

orig = sf._request_json
calls=[]

def fake_request_json(url, *args, **kwargs):
    calls.append(url)
    if '/api/v1/search?' in url:
        return {
            'hits': [
                {
                    # Real-world regression shape: root story can carry story_id.
                    'title': 'Show HN: AgentTeams – Traceable AI coding workflows',
                    'story_text': 'AI coding agents ship code quickly. We built AgentTeams with completion reports and verification summaries.',
                    'objectID': '47217890',
                    'story_id': '47217890',
                    'author': 'maker',
                    'created_at': '2026-03-02T13:45:50Z',
                    'points': 10,
                    'num_comments': 1,
                },
                {
                    'story_title': 'Show HN: AgentTeams – Traceable AI coding workflows',
                    'comment_text': 'We use coding agents and still verify completion manually.',
                    'objectID': '47218000',
                    'story_id': '47217890',
                    'author': 'buyer',
                    'created_at': '2026-03-02T14:00:00Z',
                },
            ]
        }, {'status_code': 200, 'elapsed_ms': 1}
    if '/api/v1/items/47217890' in url:
        return {
            'id': 47217890,
            'title': 'Show HN: AgentTeams – Traceable AI coding workflows',
            'children': []
        }, {'status_code': 200, 'elapsed_ms': 1}
    if '/api/v1/items/47218000' in url:
        return {'id':47218000,'children':[]}, {'status_code':200,'elapsed_ms':1}
    raise AssertionError(url)

sf._request_json = fake_request_json
try:
    result = sf._search_hn('AI coding agents completion verification')
finally:
    sf._request_json = orig

traces = result.get('traces') or []
root = next((x for x in traces if str(x.get('url') or '').endswith('47217890')), None)
comment = next((x for x in traces if str(x.get('url') or '').endswith('47218000')), None)
ck('Algolia root with story_id==objectID is POST', bool(root) and root.get('content_unit')=='POST', root)
ck('Algolia child with distinct objectID is COMMENT', bool(comment) and comment.get('content_unit')=='COMMENT', comment)

fresh = {
    'status':'PASS',
    'founder_query':'AI coding agents completion verification',
    'relevance_query':'AI coding agents completion verification',
    'language_coverage':'SUPPORTED_BY_CURRENT_QUERY_BRIDGE',
    'sources':[{'source':'HACKER_NEWS_ALGOLIA','status':'SUCCESS','count':len(traces)}],
    'traces':traces,
}
summary = sf.summarize_idea_research_probe(fresh)
conv = summary.get('founder_primary_conversations') or []
products = summary.get('founder_solution_traces') or []
ck('real-shaped Show HN root cannot enter human comments', all(x.get('url') != root.get('url') for x in conv), conv)
ck('real-shaped Show HN root enters solution lane', any(x.get('url') == root.get('url') for x in products), products)
ck('real-shaped HN child remains human comment', any(x.get('url') == comment.get('url') for x in conv), conv)

# Historical malformed row defense: even if a root arrived mislabeled COMMENT,
# equal story/object ids plus no child id still identify the maker pitch.
malformed_root = dict(root)
malformed_root['content_unit']='COMMENT'
malformed_root['metadata']=dict(malformed_root.get('metadata') or {}, content_unit='COMMENT')
ck('historical root mislabeled COMMENT is still recognized as pitch', sf._looks_like_solution_pitch(malformed_root), malformed_root)

true_child = dict(comment)
true_child['title']='Show HN: AgentTeams – Traceable AI coding workflows'
ck('true Show HN child is never promoted to maker pitch', not sf._looks_like_solution_pitch(true_child), true_child)

print('-'*96)
passed=sum(1 for _,ok,_ in checks if ok)
print(f'IDEA_RESEARCH_FIX4_ACCEPTANCE: {passed}/{len(checks)} GREEN')
if passed != len(checks):
    raise SystemExit(1)
