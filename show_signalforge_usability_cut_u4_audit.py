from __future__ import annotations
import json
from pathlib import Path
CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')

def _cut(v,n=380):
    s=' '.join(str(v or '').split());return s[:n]+('...' if len(s)>n else '')

def _frame(v):
    f=v or {};return {k:f.get(k) for k in ('actor','workflow','actions','failure_modes','objects','consequence','workaround','primary_specific_target') if f.get(k) not in (None,'',[],{})}

def main():
    print('='*154);print('SIGNALFORGE — USABILITY CONVERGENCE U4 FOUNDER REVIEW');print('='*154)
    if not CACHE.exists():print('STATUS: FAIL — discovery cache missing');return
    x=json.loads(CACHE.read_text(encoding='utf-8'));sl=x.get('founder_research_shortlist') or {};cards=sl.get('founder_discussion_cards') or [];hyps=sl.get('displayed_hypotheses') or [];ui=sl.get('displayed_user_innovation_signals') or [];leads=sl.get('displayed_research_leads') or []
    sm=x.get('evidence_schema_migration') or {};mig=sm.get('post_recovery') or sm.get('initial') or sm;recf=x.get('evidence_recovery_funnel') or {};rec=recf.get('recovery') or {}
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('PHASE SECONDS:',x.get('phase_seconds'))
    print('SCHEMA MIGRATION:',mig)
    print('IDENTITY / CANONICALIZATION:',x.get('hypothesis_identity_integrity'))
    print('RESEARCH OBJECTS:',(x.get('research_objects') or {}).get('counts'))
    print('PROBLEM FAMILY / RETRIEVAL:',x.get('hypothesis_formation'))
    print('RECOVERY:',{'selection':recf.get('recovery_selection'),'status':rec.get('status'),'requests':rec.get('requests_this_run'),'per_run_budget':rec.get('per_run_budget'),'docs_added':rec.get('docs_added'),'adapter_health':rec.get('adapter_health'),'failures':rec.get('failures')})
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'))
    print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('-'*154);print(f'FOUNDER DISCUSSION CARDS: {len(cards)}')
    for i,c in enumerate(cards,1):
        print(f'\n[D{i}] {c.get("card_type")} · {c.get("discussion_id")}')
        print(' ',_cut(c.get('problem'),360));print('  actor/workflow:',c.get('actor'),'/',c.get('workflow'));print('  Need Frame:',_frame(c.get('need_frame')))
        print('  independent evidence:',c.get('independent_evidence'))
        for e in (c.get('evidence_preview') or [])[:3]:print('   -',e.get('ref'),'[',e.get('feedback_role'),'] ::',_cut(e.get('text'),300))
        if c.get('market_context'):print('  market context:',c.get('market_context'))
        if c.get('why_now_context'):print('  why-now candidates:',c.get('why_now_context'))
        if c.get('user_innovation_context'):print('  user-innovation context:',c.get('user_innovation_context'))
        print('  unknowns:',c.get('unknowns') or []);print('  boundary:',c.get('truth_boundary'))
    print('-'*154);print(f'EVIDENCE-BACKED PROBLEM HYPOTHESES: {len(hyps)} | USER-INNOVATION SIGNALS: {len(ui)} | DIRECT NEED LEADS: {len(leads)}')
    print('QUALITY FILTERED HYPOTHESES:',sl.get('filtered_hypotheses') or [])
    print('PRODUCT USE BOUNDARY: U4 is a Founder research/discussion surface. It canonicalizes problem identity and links only evidence-backed context; it does not self-certify WTP, market attractiveness, why-now causality, product wedges, or external validation.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.');print('='*154)
if __name__=='__main__':main()
