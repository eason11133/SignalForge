from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_founder_usable_u6_audit import main as audit

async def run():
    print('='*146)
    print('SignalForge Founder-Usable U6 — memory-bounded runtime truth + dependence-aware evidence + Founder discussion-readiness')
    print('Runtime hardening: compact dirty-only observation cache + atomic streaming state/source persistence + incremental recovery | quality contracts preserved | <=2 bounded semantic audits | product ideation: 0')
    print('='*146)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:
            print('U6_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | evidence/recovery/founder quality still working',flush=True)
    else:r=await task
    hm=r.get('hypothesis_formation') or {};sl=r.get('founder_research_shortlist') or {};ro=(r.get('research_objects') or {}).get('counts') or {};sm=r.get('evidence_schema_migration') or {};recf=r.get('evidence_recovery_funnel') or {};rec=recf.get('recovery') or {};inc=(sm.get('incremental_recovery_audit') or (sm.get('post_recovery') or {}).get('incremental_recovery_audit') or {})
    cp=r.get('observation_audit') or {};print('U6_CACHE',{'load':cp.get('cache_load'),'persist':cp.get('cache_persist'),'format':cp.get('cache_format'),'dirty':cp.get('cache_dirty')});print('U6_DISCOVERY',{
        'docs':r.get('docs'),'usable':r.get('usable_observations'),'multi':hm.get('multi_evidence_seed_count'),'accepted_hypotheses':r.get('accepted'),
        'independent_copy_rejected':hm.get('dependency_rejected_count') or hm.get('duplicate_content_rejected') or 0,
        'discussion_cards':len(sl.get('founder_discussion_cards') or []),'shown_hypotheses':len(sl.get('displayed_hypotheses') or []),'shown_user_innovations':len(sl.get('displayed_user_innovation_signals') or []),'shown_direct_leads':len(sl.get('displayed_research_leads') or []),
        'market_states':ro.get('market_states'),'employer_context':ro.get('employer_demand_signals'),'solution_context':ro.get('solution_supply_signals'),
        'recovery_requests':rec.get('requests_this_run'),'recovery_docs_added':rec.get('docs_added'),'incremental_recovery_parsed':inc.get('documents'),'llm_calls':d.llm_calls,'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()

if __name__=='__main__':asyncio.run(run())
