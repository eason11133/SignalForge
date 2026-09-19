from __future__ import annotations
import json
from pathlib import Path
CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')

def _cut(v,n=380):
    s=' '.join(str(v or '').split());return s[:n]+('...' if len(s)>n else '')

def main():
    print('='*142);print('SIGNALFORGE — USABILITY CUT U2 FOUNDER REVIEW');print('='*142)
    if not CACHE.exists():print('STATUS: FAIL — discovery cache missing');return
    x=json.loads(CACHE.read_text(encoding='utf-8'));sl=x.get('founder_research_shortlist') or {};hyps=sl.get('displayed_hypotheses') or [];ui=sl.get('displayed_user_innovation_signals') or [];leads=sl.get('displayed_research_leads') or []
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('RESEARCH OBJECTS:',(x.get('research_objects') or {}).get('counts'))
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'))
    print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('SHORTLIST FILES:',x.get('founder_research_shortlist_paths'))
    print('-'*142);print(f'EVIDENCE-BACKED PROBLEM HYPOTHESES: {len(hyps)}')
    for i,h in enumerate(hyps,1):
        print(f'\n[H{i}] {_cut(h.get("problem"),260)}');print('  feedback role:',h.get('feedback_role'),'| actor/workflow:',h.get('actor'),'/',h.get('workflow'),'| product:',h.get('product') or h.get('product_id') or 'UNKNOWN');print('  independent evidence:',h.get('independent_problem_evidence_count'),'| review_priority:',h.get('review_priority'))
        for e in (h.get('evidence_preview') or [])[:4]:print('   -',e.get('ref'),'[',e.get('feedback_role'),'] ::',_cut(e.get('text'),300))
        print('  unknowns:',h.get('unknowns') or []);print('  discussion_id:',h.get('hypothesis_key'))
    print('-'*142);print(f'USER-INNOVATION / NEED-SOLUTION SIGNALS: {len(ui)}')
    for i,u in enumerate(ui,1):
        print(f'\n[U{i}] {_cut(u.get("text"),300)}');print('  actor/workflow:',u.get('actor'),'/',u.get('workflow'),'| evidence:',u.get('evidence_ref'));print('  truth:',u.get('truth_label'));print('  discussion_id:',u.get('signal_id'))
    print('-'*142);print(f'DIRECT NEED LEADS NEEDING CORROBORATION: {len(leads)}')
    for i,l in enumerate(leads,1):
        print(f'\n[L{i}] {_cut(l.get("problem"),280)}');print('  feedback role:',l.get('feedback_role'),'| actor/workflow:',l.get('actor'),'/',l.get('workflow'),'| source:',str(l.get('source_family') or '')+':'+str(l.get('source_ref') or ''));print('  missing:',l.get('missing_evidence') or ['INDEPENDENT_CORROBORATION']);print('  discussion_id:',l.get('research_id'))
    print('-'*142);print('QUALITY FILTERED HYPOTHESES:',sl.get('filtered_hypotheses') or [])
    print('PRODUCT USE BOUNDARY: These are separated research signals for Founder + ChatGPT discussion. No card self-certifies market attractiveness, willingness-to-pay, a product wedge, or market validation.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.');print('='*142)
if __name__=='__main__':main()
