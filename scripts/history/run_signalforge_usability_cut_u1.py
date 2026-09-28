from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_usability_cut_u1_audit import main as audit

async def run():
    print('='*126)
    print('SignalForge Usability Cut U1 — Founder research shortlist live run')
    print('Semantic relationship/lead audit: <=2 bounded LLM calls | product ideation: 0 | market validation: external outcomes only')
    print('='*126)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:
            print('U1_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | discovery/semantic review still working',flush=True)
    else:r=await task
    hm=r.get('hypothesis_formation') or {}; sl=r.get('founder_research_shortlist') or {}
    print('U1_DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'multi':hm.get('multi_evidence_seed_count'),'research_hypotheses':sl.get('research_hypothesis_count'),'shown_hypotheses':len(sl.get('displayed_hypotheses') or []),'shown_leads':len(sl.get('displayed_research_leads') or []),'llm_calls':d.llm_calls,'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()

if __name__=='__main__':asyncio.run(run())
