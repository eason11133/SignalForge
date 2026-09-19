from __future__ import annotations
import json
from pathlib import Path

CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')

def _cut(v,n=360):
    s=' '.join(str(v or '').split())
    return s[:n]+('...' if len(s)>n else '')

def main():
    print('='*138)
    print('SIGNALFORGE — USABILITY CUT U1 FOUNDER REVIEW')
    print('='*138)
    if not CACHE.exists():
        print('STATUS: FAIL — discovery cache missing');return
    x=json.loads(CACHE.read_text(encoding='utf-8'));sl=x.get('founder_research_shortlist') or {};hyps=sl.get('displayed_hypotheses') or [];leads=sl.get('displayed_research_leads') or []
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'))
    print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('SHORTLIST FILES:',x.get('founder_research_shortlist_paths'))
    print('-'*138)
    print(f'FOUNDER RESEARCH HYPOTHESES: {len(hyps)}')
    for i,h in enumerate(hyps,1):
        print(f'\n[H{i}] {_cut(h.get("problem"),240)}')
        print('  actor/workflow:',h.get('actor'),'/',h.get('workflow'),'| product:',h.get('product') or h.get('product_id') or 'UNKNOWN')
        print('  independent evidence:',h.get('independent_problem_evidence_count'),'| facets:',h.get('facets') or [],'| review_priority:',h.get('review_priority'))
        for e in (h.get('evidence_preview') or [])[:4]:
            print('   -',e.get('ref'),'::',_cut(e.get('text'),300))
        print('  unknowns:',h.get('unknowns') or [])
        print('  semantic_audit:',h.get('semantic_audit') or 'NOT_RUN')
        print('  discussion_id:',h.get('hypothesis_key'))
    print('-'*138)
    print(f'RESEARCH LEADS NEEDING CORROBORATION: {len(leads)}')
    for i,l in enumerate(leads,1):
        print(f'\n[L{i}] {_cut(l.get("problem"),240)}')
        print('  actor/workflow:',l.get('actor'),'/',l.get('workflow'),'| source:',str(l.get('source_family') or '')+':'+str(l.get('source_ref') or ''))
        print('  missing:',l.get('missing_evidence') or ['INDEPENDENT_CORROBORATION'])
        print('  discussion_id:',l.get('research_id'))
    print('-'*138)
    print('PRODUCT USE BOUNDARY: These cards are ready for Founder + ChatGPT discussion. They are not self-certified venture opportunities, build recommendations, willingness-to-pay evidence, or market validation.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.')
    print('='*138)

if __name__=='__main__':main()
