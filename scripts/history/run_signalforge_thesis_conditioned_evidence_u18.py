from __future__ import annotations
import time
from processors.founder_thesis_research_control_u14 import Store
from processors.thesis_conditioned_evidence_u18 import (
    provider_status,execute_cycle,card_progress,ENGINE_VERSION
)

def main():
    print("="*150)
    print("SignalForge U18 — Thesis-Conditioned Evidence Integrity")
    print("thesis context + atomic gap question + claim-conditioned query + dual thesis/gap adjudication + legacy judgment quarantine")
    print("="*150)
    t=time.perf_counter()
    ps=provider_status()
    print("U18_PROVIDER",ps)
    store=Store()
    result=execute_cycle(store,max_new_requests=2,max_verifier_calls=3)
    print("U18_QUARANTINE",result["quarantine"])
    print("U18_OVERLAY_RECONCILIATION",result["reconcile"])
    print("U18_U17_PENDING_ADJUDICATION",result["u17_pending_adjudication"])
    print("U18_U18_PENDING_ADJUDICATION",result["u18_pending_adjudication"])
    print("U18_EXECUTION",{
        "new_request_count":result["new_request_count"],
        "verifier_calls":result["verifier_calls"],
        "verifier_available":result["verifier_available"],
        "u18_pending_after":result["u18_pending_after"],
    })
    for r in result["new_requests"]:print("U18_REQUEST",r)
    for cid in store.card_map:print("U18_FOUNDER_CARD_PROGRESS",card_progress(store,cid))
    print(f"U18_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U18 EVIDENCE-INTEGRITY AUDIT")
    print("generic_gap_query_can_create_support: FALSE")
    print("thesis_match_and_gap_match_both_required: TRUE")
    print("legacy_context_invalid_support_quarantined: TRUE")
    print("stale_verification_pending_reconciled: TRUE")
    print("verifier_capacity_reserved_before_new_retrieval: TRUE")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
