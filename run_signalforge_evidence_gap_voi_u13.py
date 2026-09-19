from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_evidence_gap_voi_u13_audit import main as audit

async def run():
    print('='*164)
    print('SignalForge Evidence-Gap VOI U13 — card-linked evidence attribution + value-of-information acquisition')
    print('U9/U10/U11/U12 Founder semantic gate preserved | recovery is card/gap attributable | retrieved evidence != gap closure | product ideation: 0')
    print('='*164)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:print('U13_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | card-linked evidence acquisition still working',flush=True)
    else:r=await task
    funnel=r.get('evidence_recovery_funnel') or {};rec=funnel.get('recovery') or {};assim=funnel.get('assimilation') or {};cp=r.get('observation_audit') or {};hm=r.get('hypothesis_formation') or {};sl=r.get('founder_research_shortlist') or {};graph=r.get('graph') or {};ledger=funnel.get('evidence_gap_ledger') or {}
    print('U13_CACHE',{'load':cp.get('cache_load'),'hits':cp.get('cache_hits'),'misses':cp.get('cache_misses'),'persist':cp.get('cache_persist')})
    print('U13_RUNTIME',{'phase_seconds':r.get('phase_seconds'),'graph_cache':graph.get('cache'),'graph_nodes':graph.get('nodes'),'graph_edges':graph.get('edges')})
    print('U13_ASSIMILATION',assim)
    print('U13_ACQUISITION',{'requests':rec.get('requests_this_run'),'docs_added':rec.get('docs_added'),'query_memory':rec.get('query_memory'),'adapter_health':rec.get('adapter_health')})
    print('U13_EVIDENCE_GAPS',{'rows':ledger.get('rows') or [],'truth_boundary':ledger.get('truth_boundary')})
    surfaced=[]
    for c in sl.get('founder_discussion_cards') or []:
        surfaced.append({'id':c.get('discussion_id'),'type':c.get('card_type'),'gap_progress':c.get('evidence_gap_progress') or [],'best_next_evidence':c.get('best_next_evidence_plan') or {}})
    print('U13_FOUNDER_CARD_PROGRESS',surfaced)
    print('U13_DISCOVERY',{'docs':r.get('docs'),'usable':r.get('usable_observations'),'multi':hm.get('multi_evidence_seed_count'),'accepted':r.get('accepted'),'discussion_cards':len(sl.get('founder_discussion_cards') or []),'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()
if __name__=='__main__':asyncio.run(run())
