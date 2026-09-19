from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_mature_research_adoption_a2_audit import main as audit

async def run():
    print('='*124)
    print('SignalForge Mature Research Adoption A2 — balanced corroboration + diversified recovery live reflow')
    print('LLM relationship audit: 0 calls | product ideation: 0 | frontier opportunity linkage: not self-certified')
    print('='*124)
    d=OpportunityObservationDiscovery(ai_call_allowance=0,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:
            print('A2_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | discovery still working',flush=True)
    else:r=await task
    hm=r.get('hypothesis_formation') or {};oa=r.get('observation_audit') or {};ret=hm.get('retrieval') or {}
    print('A2_DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'signature_missing_retained':oa.get('signature_missing_need_fragments_retained'),'seeds':hm.get('seed_count'),'multi':hm.get('multi_evidence_seed_count'),'misc':hm.get('misc_backlog_count'),'current':r.get('accepted'),'watch':r.get('watch_signal_count'),'research':r.get('evidence_research_count'),'retrieval_pairs':ret.get('candidate_pairs'),'retrieval_coverage':ret.get('coverage')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()

if __name__=='__main__':asyncio.run(run())
