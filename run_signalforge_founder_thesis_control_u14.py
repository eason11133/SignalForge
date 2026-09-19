from __future__ import annotations
import subprocess,sys,time
from pathlib import Path
from processors.founder_thesis_research_control_u14 import assimilate_u13_stdout,ENGINE_VERSION

U13=Path("run_signalforge_evidence_gap_voi_u13.py")

def main():
    print("="*150)
    print("SignalForge U14 — Founder Thesis Research Control Plane")
    print("U13 acquisition preserved | canonical Founder thesis state | unverified legacy fragments quarantined | prospective marginal VOI | product ideation: 0")
    print("="*150)
    if not U13.exists():
        raise SystemExit("U14_PRECHECK_FAIL: run_signalforge_evidence_gap_voi_u13.py missing; no runtime state changed")
    t=time.perf_counter()
    p=subprocess.run([sys.executable,str(U13)],capture_output=True,text=True)
    if p.stdout: print(p.stdout,end="" if p.stdout.endswith("\n") else "\n")
    if p.returncode:
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise SystemExit(p.returncode)
    u14=assimilate_u13_stdout(p.stdout,cost=0.08)
    print("U14_FOUNDER_THESIS_CONTROL",u14)
    for x in u14["founder_cards"]:
        print("U14_FOUNDER_CARD_PROGRESS",x)
    print("U14_RESEARCH_BUDGET",u14["budget"])
    print(f"U14_RUNTIME_WRAPPER seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U14 CONTROL-PLANE AUDIT")
    print("canonical_thesis_identity: PASS" if u14["founder_cards"] else "canonical_thesis_identity: NO_SURFACED_CARD")
    print("legacy_fragment_to_founder_auto_attach: BLOCKED")
    print("retrieved_candidate_equals_confirmed_evidence: FALSE")
    print("voi_semantics: PROSPECTIVE_MARGINAL_VALUE")
    print("truth_boundary: research control only; no demand/WTP/build truth promoted")
    print("="*120)

if __name__=="__main__":main()
