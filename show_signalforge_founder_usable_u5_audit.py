from __future__ import annotations
import json
from pathlib import Path
CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
def _cut(v,n=360):
    s=' '.join(str(v or '').split());return s[:n]+('...' if len(s)>n else '')
def _frame(v):
    f=v or {};return {k:f.get(k) for k in ('actor','workflow','actions','failure_modes','objects','consequence','workaround','primary_specific_target') if f.get(k) not in (None,'',[],{})}
def main():
    print('='*158);print('SIGNALFORGE — FOUNDER-USABLE U5 REVIEW');print('='*158)
    if not CACHE.exists():print('STATUS: FAIL — discovery cache missing');return
    x=json.loads(CACHE.read_text(encoding='utf-8'));sl=x.get('founder_research_shortlist') or {};cards=sl.get('founder_discussion_cards') or [];sm=x.get('evidence_schema_migration') or {};recf=x.get('evidence_recovery_funnel') or {};rec=recf.get('recovery') or {};hm=x.get('hypothesis_formation') or {};ro=(x.get('research_objects') or {}).get('counts') or {}
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('PHASE SECONDS:',x.get('phase_seconds'))
    print('IDENTITY:',x.get('hypothesis_identity_integrity'))
    print('PROVENANCE / FAMILY:',{'multi_evidence':hm.get('multi_evidence_seed_count'),'dependency_rejected_count':hm.get('dependency_rejected_count'),'duplicate_seed_records_merged':hm.get('duplicate_seed_records_merged'),'independent_source_origins_visible':True})
    print('RESEARCH OBJECTS:',ro)
    print('RECOVERY:',{'selection':recf.get('recovery_selection'),'requests':rec.get('requests_this_run'),'docs_added':rec.get('docs_added'),'adapter_health':rec.get('adapter_health'),'failures':rec.get('failures'),'reddit_request_cap':rec.get('reddit_request_cap'),'market_context_request_cap':rec.get('market_context_request_cap')})
    print('INCREMENTAL RECOVERY PARSE:',sm.get('incremental_recovery_audit') or (sm.get('post_recovery') or {}).get('incremental_recovery_audit'))
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'))
    print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('FOUNDER FILTERS:',{'filtered_hypotheses':sl.get('filtered_hypotheses'),'filtered_leads':sl.get('deterministically_filtered_leads'),'filtered_user_innovations':sl.get('filtered_user_innovations')})
    print('-'*158);print('FOUNDER DISCUSSION CARDS:',len(cards))
    for i,c in enumerate(cards,1):
        print(f'\n[D{i}] {c.get("card_type")} · {c.get("discussion_id")}')
        print(' ',_cut(c.get('problem')));print('  actor/workflow:',c.get('actor'),'/',c.get('workflow'));print('  Need Frame:',_frame(c.get('need_frame')));print('  readiness:',c.get('discussion_readiness'))
        print('  independent evidence/origins:',c.get('independent_evidence'),'/',c.get('independent_source_origins'),'dependency rejected:',c.get('dependency_rejected_count'))
        for e in (c.get('evidence_preview') or [])[:3]:print('   -',e.get('ref'),'[',e.get('feedback_role'),'] ::',_cut(e.get('text'),280))
        if c.get('market_context'):print('  market context:',c.get('market_context'))
        if c.get('solution_context'):print('  solution context:',c.get('solution_context'))
        if c.get('why_now_context'):print('  why-now candidates:',c.get('why_now_context'))
        if c.get('user_innovation_context'):print('  user-innovation context:',c.get('user_innovation_context'))
        print('  unknowns:',c.get('unknowns') or []);print('  boundary:',c.get('truth_boundary'))
    print('-'*158)
    print('FOUNDER-SURFACED:',{'hypotheses':len(sl.get('displayed_hypotheses') or []),'user_innovations':len(sl.get('displayed_user_innovation_signals') or []),'direct_leads':len(sl.get('displayed_research_leads') or [])})
    print('PRODUCT USE BOUNDARY: U5 is usable only as a Founder opportunity-research/discussion surface. Cards are evidence-role and discussion-readiness filtered; WTP, market attractiveness, causal why-now, product wedges and external validation are not self-certified.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.');print('='*158)
if __name__=='__main__':main()
