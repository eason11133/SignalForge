from __future__ import annotations
import json
from pathlib import Path
CACHE=Path('.radar_runtime/opportunity_hypothesis_discovery_r1.json')
def _cut(v,n=380):
    s=' '.join(str(v or '').split());return s[:n]+('...' if len(s)>n else '')
def _frame(v):
    f=v or {};return {k:f.get(k) for k in ('actor','workflow','actions','failure_modes','objects','consequence','workaround','primary_specific_target') if f.get(k) not in (None,'',[],{})}
def main():
    print('='*170);print('SIGNALFORGE — FOUNDER-USABLE U8 REVIEW');print('='*170)
    if not CACHE.exists():print('STATUS: FAIL — discovery cache missing');return
    with CACHE.open('r',encoding='utf-8') as f:x=json.load(f)
    sl=x.get('founder_research_shortlist') or {};cards=sl.get('founder_discussion_cards') or [];sm=x.get('evidence_schema_migration') or {};recf=x.get('evidence_recovery_funnel') or {};rec=recf.get('recovery') or {};hm=x.get('hypothesis_formation') or {};ro=(x.get('research_objects') or {}).get('counts') or {};oa=x.get('observation_audit') or {}
    print('STATUS:',sl.get('status'))
    print('DISCOVERY:',{'docs':x.get('docs'),'usable':x.get('usable_observations'),'accepted_research_hypotheses':x.get('accepted'),'watch':x.get('watch_signal_count'),'research':x.get('evidence_research_count')})
    print('CACHE / SCHEMA:',{'cache_load':oa.get('cache_load'),'cache_hits':oa.get('cache_hits'),'cache_misses':oa.get('cache_misses'),'schema_upgrades':oa.get('schema_upgrades'),'cache_persist':oa.get('cache_persist')})
    print('PHASE SECONDS:',x.get('phase_seconds'));print('IDENTITY:',x.get('hypothesis_identity_integrity'))
    print('RESEARCH OBJECTS:',ro)
    print('RECOVERY:',{'selection':recf.get('recovery_selection'),'requests':rec.get('requests_this_run'),'docs_added':rec.get('docs_added'),'adapter_health':rec.get('adapter_health'),'failures':rec.get('failures'),'truth_contract':rec.get('truth_contract')})
    print('SEMANTIC RELATIONSHIP AUDIT:',x.get('relationship_audit'));print('RESEARCH LEAD AUDIT:',x.get('lead_audit'))
    print('FOUNDER FILTERS:',{'filtered_hypotheses':sl.get('filtered_hypotheses'),'filtered_leads':sl.get('deterministically_filtered_leads'),'filtered_user_innovations':sl.get('filtered_user_innovations')})
    print('-'*170);print('FOUNDER DISCUSSION CARDS:',len(cards))
    for i,c in enumerate(cards,1):
        print(f'\n[D{i}] {c.get("card_type")} · {c.get("discussion_id")}')
        print(' ',_cut(c.get('problem')));print('  actor/workflow:',c.get('actor'),'/',c.get('workflow'));print('  Need Frame:',_frame(c.get('need_frame')));print('  readiness:',c.get('discussion_readiness'))
        if c.get('diffusion_gap_assessment'):print('  diffusion/commercialization gap:',c.get('diffusion_gap_assessment'))
        print('  independent evidence/origins:',c.get('independent_evidence'),'/',c.get('independent_source_origins'),'dependency rejected:',c.get('dependency_rejected_count'))
        for e in (c.get('evidence_preview') or [])[:3]:print('   -',e.get('ref'),'[',e.get('feedback_role'),'] ::',_cut(e.get('text'),300))
        if c.get('market_context'):print('  market context:',c.get('market_context'))
        if c.get('solution_context'):print('  solution context:',c.get('solution_context'))
        if c.get('why_now_context'):print('  why-now candidates:',c.get('why_now_context'))
        print('  unknowns:',c.get('unknowns') or []);print('  boundary:',c.get('truth_boundary'))
    print('-'*170)
    print('FOUNDER-SURFACED:',{'hypotheses':len(sl.get('displayed_hypotheses') or []),'user_innovations':len(sl.get('displayed_user_innovation_signals') or []),'direct_leads':len(sl.get('displayed_research_leads') or []),'market_states':ro.get('market_states')})
    print('PRODUCT USE BOUNDARY: U8 surfaces only source-intent-correct Need-Solution/problem research. Diffusion/commercialization gaps are candidates until independent recurrence and peer adoption/diffusion evidence exist.')
    print('LIVE MARKET VALIDATION: remains UNVALIDATED until external outcomes exist.');print('='*170)
if __name__=='__main__':main()
