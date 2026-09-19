from __future__ import annotations
import asyncio,time,json
from pathlib import Path
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_adaptive_evidence_u11_audit import main as audit

async def run():
    print('='*160)
    print('SignalForge Adaptive Evidence U11 — relevance feedback + MMR diversity + empirical source yield')
    print('U9/U10 Founder semantic gate preserved | acquisition policy only | product ideation: 0')
    print('='*160)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:print('U11_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | adaptive evidence acquisition still working',flush=True)
    else:r=await task
    sl=r.get('founder_research_shortlist') or {};rec=((r.get('evidence_recovery_funnel') or {}).get('recovery') or {});cp=r.get('observation_audit') or {};hm=r.get('hypothesis_formation') or {}
    print('U11_CACHE',{'load':cp.get('cache_load'),'hits':cp.get('cache_hits'),'misses':cp.get('cache_misses'),'persist':cp.get('cache_persist')})
    print('U11_ACQUISITION',{'requests':rec.get('requests_this_run'),'docs_added':rec.get('docs_added'),'query_memory':rec.get('query_memory'),'adapter_health':rec.get('adapter_health')})
    print('U11_DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'multi':hm.get('multi_evidence_seed_count'),'accepted':r.get('accepted'),'discussion_cards':len(sl.get('founder_discussion_cards') or []),'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()
if __name__=='__main__':asyncio.run(run())
