from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_usability_cut_u2_audit import main as audit

async def run():
    print('='*132)
    print('SignalForge Usability Cut U2 — feedback-role-separated Founder research surface')
    print('Research adoption: multi-label feedback taxonomy + user-innovation Need-Solution signals | <=2 bounded LLM audits | product ideation: 0')
    print('='*132)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:
            print('U2_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | discovery/quality review still working',flush=True)
    else:r=await task
    hm=r.get('hypothesis_formation') or {};sl=r.get('founder_research_shortlist') or {};ro=(r.get('research_objects') or {}).get('counts') or {}
    print('U2_DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'multi':hm.get('multi_evidence_seed_count'),'accepted_hypotheses':r.get('accepted'),'shown_hypotheses':len(sl.get('displayed_hypotheses') or []),'shown_user_innovations':len(sl.get('displayed_user_innovation_signals') or []),'shown_direct_leads':len(sl.get('displayed_research_leads') or []),'user_innovation_objects':ro.get('user_innovation_signals'),'solution_context_objects':ro.get('solution_supply_signals'),'policy_context_objects':ro.get('policy_contexts'),'llm_calls':d.llm_calls,'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()

if __name__=='__main__':asyncio.run(run())
