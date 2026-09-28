from __future__ import annotations
import asyncio
import time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_mature_research_adoption_audit import main as audit

async def run():
    print('='*120)
    print('SignalForge Mature Research Adoption A1 — live reflow')
    print('LLM relationship audit: 0 calls | product ideation: 0 | crawler behavior: existing bounded source/recovery contract')
    print('='*120)
    d=OpportunityObservationDiscovery(ai_call_allowance=0,max_persist=12,persist=True)
    print('DISCOVERY_START | bounded retrieve->rerank + fragment-safe research routing')
    task=asyncio.create_task(d.run())
    started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=15)
            break
        except asyncio.TimeoutError:
            print('DISCOVERY_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | still working')
    else:
        r=await task
    hm=r.get('hypothesis_formation') or {}; oa=r.get('observation_audit') or {}
    print('DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'dispositions':oa.get('evidence_dispositions'),'signature_missing_retained':oa.get('signature_missing_need_fragments_retained'),'seeds':hm.get('seed_count'),'stable':hm.get('stable_identity_seed_count'),'incomplete':hm.get('incomplete_identity_seed_count'),'current':r.get('accepted'),'watch':r.get('watch_signal_count'),'research':r.get('evidence_research_count')})
    await rebuild_current_claims()
    await rebuild_current_portfolio()
    rebuild_validation_queue()
    rebuild_calibration()
    rebuild_founder_surface()
    audit()

if __name__=='__main__': asyncio.run(run())
