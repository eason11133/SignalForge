from __future__ import annotations
import json
from pathlib import Path
CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')

def _cut(v,n=380):
    s=' '.join(str(v or '').split());return s[:n]+('...' if len(s)>n else '')

def _frame(v):
    f=v or {}
    return {k:f.get(k) for k in ('actor','workflow','actions','failure_modes','objects','consequence','workaround','primary_specific_target') if f.get(k) not in (None,'',[],{})}

def main():
    print('='*150);print('SIGNALFORGE — USABILITY CUT U3 FOUNDER REVIEW');print('='*150)
    if not CACHE.exists():print('STATUS: FAIL — discovery cache missing');return
    x=json.loads(CACHE.read_text(encoding='utf-8'));sl=x.get('founder_research_shortlist') or {};hyps=sl.get('displayed_hypotheses') or [];ui=sl.get('displayed_user_innovation_signals') or [];leads=sl.get('displayed_research_leads') or []
    sm=x.get('evidence_schema_migration') or {};mig=sm.get('post_recovery') or sm.get('initial') or sm
    recf=x.get('evidence_recovery_funnel') or {};rec=recf.get('recovery') or {};sel=recf.get('recovery_selection') or {}
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('SCHEMA MIGRATION:',mig)
    print('RESEARCH OBJECTS:',(x.get('research_objects') or {}).get('counts'))
    print('PROBLEM FAMILY / RETRIEVAL:',x.get('hypothesis_formation'))
    print('RECOVERY SELECTION:',sel)
    print('RECOVERY RESULT:',{'status':rec.get('status'),'requests':rec.get('requests_this_run'),'docs_added':rec.get('docs_added'),'adapter_health':rec.get('adapter_health'),'failures':rec.get('failures'),'anchors':rec.get('anchors')})
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'))
    print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('SHORTLIST FILES:',x.get('founder_research_shortlist_paths'))
    print('-'*150);print(f'EVIDENCE-BACKED PROBLEM HYPOTHESES: {len(hyps)}')
    for i,h in enumerate(hyps,1):
        print(f'\n[H{i}] {_cut(h.get("problem"),280)}');print('  feedback role:',h.get('feedback_role'),'| actor/workflow:',h.get('actor'),'/',h.get('workflow'),'| product:',h.get('product') or h.get('product_id') or 'UNKNOWN');print('  Need Frame:',_frame(h.get('need_frame')));print('  independent evidence:',h.get('independent_problem_evidence_count'),'| review_priority:',h.get('review_priority'))
        for e in (h.get('evidence_preview') or [])[:4]:print('   -',e.get('ref'),'[',e.get('feedback_role'),'] ::',_cut(e.get('text'),320))
        if h.get('related_user_innovation_context'):print('  related user-innovation context:',h.get('related_user_innovation_context'))
        print('  unknowns:',h.get('unknowns') or []);print('  discussion_id:',h.get('hypothesis_key'))
    print('-'*150);print(f'USER-INNOVATION / NEED-SOLUTION SIGNALS: {len(ui)}')
    for i,u in enumerate(ui,1):
        print(f'\n[U{i}] {_cut(u.get("text"),320)}');print('  actor/workflow:',u.get('actor'),'/',u.get('workflow'),'| evidence:',u.get('evidence_ref'));print('  Need Frame:',_frame(u.get('need_frame')));print('  truth:',u.get('truth_label'));print('  discussion_id:',u.get('signal_id'))
    print('-'*150);print(f'DIRECT NEED LEADS NEEDING CORROBORATION: {len(leads)}')
    for i,l in enumerate(leads,1):
        print(f'\n[L{i}] {_cut(l.get("problem"),300)}');print('  feedback role:',l.get('feedback_role'),'| actor/workflow:',l.get('actor'),'/',l.get('workflow'),'| source:',str(l.get('source_family') or '')+':'+str(l.get('source_ref') or ''));print('  Need Frame:',_frame(l.get('need_frame')));print('  missing:',l.get('missing_evidence') or ['INDEPENDENT_CORROBORATION']);
        if l.get('related_user_innovation_context'):print('  related user-innovation context:',l.get('related_user_innovation_context'))
        print('  discussion_id:',l.get('research_id'))
    print('-'*150);print('QUALITY FILTERED HYPOTHESES:',sl.get('filtered_hypotheses') or [])
    print('PRODUCT USE BOUNDARY: U3 separates need evidence, user-built Need–Solution signals, solution/supply context, policy context and raw market state. Structural similarity assists retrieval only; no card self-certifies market attractiveness, WTP, a product wedge, or market validation.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.');print('='*150)
if __name__=='__main__':main()
