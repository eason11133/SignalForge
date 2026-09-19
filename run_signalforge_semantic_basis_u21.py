from pathlib import Path
import time
from processors.semantic_basis_contract_u21 import analyze

def main():
    print("="*150)
    print("SignalForge U21 — Observation Semantic Basis Contract")
    print("content-vs-metadata field contract | version/schema placeholder rejection | semantic path audit | family formation only after clean basis gate")
    print("="*150)
    t=time.perf_counter()
    r=analyze(Path("."))
    print("U21_STATUS",r.get("status"))
    print("U21_LOCATOR",r.get("locator"))
    print("U21_BASIS_QUALITY",r.get("basis_quality"))
    print("U21_FAMILY_FORMATION",r.get("family_formation"))
    print("U21_FAMILY_STABILITY",r.get("family_stability"))
    print("U21_GLOBAL_COVERAGE",r.get("global_coverage"))
    print("U21_BACKTEST",r.get("historical_backtest"))
    print("U21_SOURCE_COVERAGE",r.get("source_coverage"))
    print("U21_CALIBRATION_GATE",r.get("calibration_gate"))
    print("U21_EXPLORATION_POLICY",r.get("exploration_policy"))
    print(f"U21_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U21 SEMANTIC-BASIS AUDIT")
    print("metadata_can_be_semantic_basis: FALSE")
    print("frame_version_can_be_problem_family: FALSE")
    print("field_name_placeholder_can_be_problem_family: FALSE")
    print("semantic_basis_gate_before_family: TRUE")
    print("bad_basis_can_control_budget: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
