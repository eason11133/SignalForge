from __future__ import annotations
import asyncio,time
from processors.transition_gap_discovery import OpportunityObservationDiscovery
from processors.current_opportunity_claims import rebuild_current_claims
from processors.current_opportunity_portfolio import rebuild_current_portfolio
from processors.opportunity_validation_pipeline import rebuild_validation_queue
from processors.opportunity_calibration import rebuild_calibration
from processors.founder_opportunity_surface import rebuild_founder_surface
from show_signalforge_usability_cut_u4_audit import main as audit

async def run():
    print('='*144)
    print('SignalForge Usability Convergence Cut U4 — canonical identity + bounded evidence + persistent recovery + Founder discussion cards')
    print('Research adoption: entity-resolution canonicalization + bounded feedback semantics + Need/Market/Enabler separation + <=2 relationship/lead audits | product ideation: 0')
    print('='*144)
    d=OpportunityObservationDiscovery(ai_call_allowance=2,max_persist=12,persist=True)
    task=asyncio.create_task(d.run());started=time.perf_counter()
    while not task.done():
        try:
            r=await asyncio.wait_for(asyncio.shield(task),timeout=20);break
        except asyncio.TimeoutError:
            print('U4_HEARTBEAT',round(time.perf_counter()-started,1),'seconds | discovery/quality review still working',flush=True)
    else:r=await task
    hm=r.get('hypothesis_formation') or {};sl=r.get('founder_research_shortlist') or {};ro=(r.get('research_objects') or {}).get('counts') or {};sm=r.get('evidence_schema_migration') or {}
    mig=(sm.get('post_recovery') or sm.get('initial') or sm);rec=(r.get('evidence_recovery_funnel') or {}).get('recovery') or {};ii=r.get('hypothesis_identity_integrity') or {}
    print('U4_DISCOVERY',{
        'docs':r.get('docs'),'usable':r.get('usable_observations'),'cache_hits':(r.get('observation_audit') or {}).get('cache_hits'),'cache_misses':(r.get('observation_audit') or {}).get('cache_misses'),
        'stale_schema':mig.get('stale_rows_before_migration'),'multi':hm.get('multi_evidence_seed_count'),'canonical_seed_count':hm.get('canonical_seed_count'),'canonical_merge':hm.get('duplicate_seed_records_merged'),
        'accepted_hypotheses':r.get('accepted'),'unique_hypothesis_keys':ii.get('unique_hypothesis_keys'),'discussion_cards':len(sl.get('founder_discussion_cards') or []),
        'shown_hypotheses':len(sl.get('displayed_hypotheses') or []),'shown_user_innovations':len(sl.get('displayed_user_innovation_signals') or []),'shown_direct_leads':len(sl.get('displayed_research_leads') or []),
        'market_state_objects':ro.get('market_states'),'external_enablers':ro.get('external_enablers'),'recovery_requests':rec.get('requests_this_run'),'recovery_docs_added':rec.get('docs_added'),'llm_calls':d.llm_calls,'state':r.get('operational_evidence_state')})
    await rebuild_current_claims();await rebuild_current_portfolio();rebuild_validation_queue();rebuild_calibration();rebuild_founder_surface();audit()

if __name__=='__main__':asyncio.run(run())
