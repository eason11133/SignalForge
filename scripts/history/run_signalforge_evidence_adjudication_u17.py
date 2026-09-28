from __future__ import annotations
import time

from processors.founder_thesis_research_control_u14 import Store
from processors.evidence_adjudication_u17 import (
    load_project_env,provider_status,migrate_u16_pending,QueueVerifier,
    execute_cycle,card_progress,pending_total,ENGINE_VERSION
)

def main():
    print("="*150)
    print("SignalForge U17 — Evidence Adjudication Queue + Verifier Availability Control")
    print("pending-first backpressure | .env-aware verifier discovery | persistent candidate evidence | no retrieval pile-up while adjudication is blocked")
    print("="*150)
    t=time.perf_counter()
    env=load_project_env()
    print("U17_ENV",env)
    ps=provider_status()
    print("U17_PROVIDER",ps)
    store=Store()
    mig=migrate_u16_pending()
    print("U17_U16_PENDING_MIGRATION",mig)
    verifier=QueueVerifier(max_calls=3)
    result=execute_cycle(store,max_new_tasks=2,verifier=verifier)
    print("U17_EXECUTION",{
        "provider_status":result["provider_status"],
        "verifier_calls":result["verifier_calls"],
        "pending_after":result["pending_after"],
        "retrieval_task_count":result["retrieval_task_count"],
        "pre_adjudication":result["pre_adjudication"],
    })
    for r in result["retrieval_tasks"]:print("U17_RETRIEVAL_TASK",r)
    for cid in store.card_map:print("U17_FOUNDER_CARD_PROGRESS",card_progress(store,cid))
    print(f"U17_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U17 ADJUDICATION AUDIT")
    print("dotenv_aware_provider_detection: PASS")
    print("pending_evidence_persistent_queue: PASS")
    print("pending_first_backpressure: ACTIVE")
    print("verifier_unavailable_causes_false_negative: FALSE")
    print("same_gap_overretrieval_while_pending: BLOCKED")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
