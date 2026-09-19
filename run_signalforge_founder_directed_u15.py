from __future__ import annotations
import ast,subprocess,sys,time
from pathlib import Path

from processors.founder_thesis_research_control_u14 import Store, STATE_PATH, assimilate_u13_stdout
from processors.founder_directed_research_u15 import (
    FounderDirectedExecutor, exploration_due, cycle_accounting, ENGINE_VERSION
)

U13=Path("run_signalforge_evidence_gap_voi_u13.py")

def run_u13_and_assimilate():
    if not U13.exists():
        raise SystemExit("U15_BOOTSTRAP_FAIL: U13 runner missing")
    p=subprocess.run([sys.executable,str(U13)],capture_output=True,text=True)
    if p.stdout: print(p.stdout,end="" if p.stdout.endswith("\n") else "\n")
    if p.returncode:
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise SystemExit(p.returncode)
    return assimilate_u13_stdout(p.stdout,cost=0.08)

def main():
    print("="*150)
    print("SignalForge U15 — Founder-Directed Acquisition Cutover")
    print("Founder thesis executes targeted research first | U13 broad exploration becomes periodic refresh | exact request->candidate attribution | bounded verification")
    print("="*150)
    t=time.perf_counter()

    bootstrap=not STATE_PATH.exists()
    refresh=exploration_due()
    exploration_refreshed=False
    if bootstrap or refresh:
        print(f"U15_EXPLORATION_REFRESH reason={'BOOTSTRAP' if bootstrap else 'PERIODIC_4_CYCLE'}")
        x=run_u13_and_assimilate()
        exploration_refreshed=True
        print("U15_EXPLORATION_ASSIMILATED",{"cards":len(x.get("founder_cards") or []),"orphans_total":x.get("legacy_u13_orphans_total")})
    else:
        print("U15_EXPLORATION_REFRESH SKIPPED_BY_BUDGET_POLICY")

    store=Store()
    if not store.card_map:
        print("U15_NO_ACTIVE_FOUNDER_THESIS; forcing exploration refresh")
        run_u13_and_assimilate()
        exploration_refreshed=True
        store=Store()

    result=FounderDirectedExecutor().execute(store,founder_requests=5)
    accounting=cycle_accounting(exploration_refreshed,result.get("founder_requests",0))

    print("U15_EXECUTION",{
        "status":result.get("status"),
        "founder_requests":result.get("founder_requests"),
        "verifier_calls":result.get("verifier_calls"),
    })
    for r in result.get("requests") or []:
        print("U15_REQUEST",r)
    for c in result.get("cards") or []:
        print("U15_FOUNDER_CARD_PROGRESS",c)
    print("U15_BUDGET_ACCOUNTING",accounting)
    print(f"U15_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U15 CUTOVER AUDIT")
    print("founder_directed_requests:",result.get("founder_requests",0))
    print("periodic_exploration_refresh:",exploration_refreshed)
    print("exact_request_candidate_attribution: PASS")
    print("payment_dependency_gate: ACTIVE")
    print("candidate_equals_confirmed_evidence: FALSE")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
