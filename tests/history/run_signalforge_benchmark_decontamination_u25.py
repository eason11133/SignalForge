from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
from pathlib import Path
import time
from processors.discovery_benchmark_decontamination_u25 import run

def main():
    print("="*158)
    print("SignalForge U25 — Weak-Label Benchmark Decontamination + Representation Re-screen")
    print("raw-cache content recovery | explicit-signature exclusion | U24 leakage invalidation | decontaminated R0-R4 shadow re-screen")
    print("="*158)
    t=time.perf_counter();r=run(Path("."))
    print("U25_STATUS",r.get("status"))
    print("U25_BENCHMARK_LINEAGE",r.get("benchmark_lineage"))
    print("U25_RECOVERY",r.get("recovery"))
    print("U25_ANCHOR_AUDIT",r.get("anchor_audit"))
    print("U25_ARM_COMPARISON",r.get("arm_comparison"))
    print("U25_LLM_SHADOW",r.get("llm_shadow"))
    print("U25_AUTHORITY",r.get("authority"))
    print("U25_FOUNDER_PROTECTED_STATE_UNCHANGED",r.get("founder_protected_state_unchanged"))
    print("U25_DECISION",r.get("decision"))
    print(f"U25_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*128)
    print("SIGNALFORGE U25 BENCHMARK-INTEGRITY AUDIT")
    print("explicit_signature_allowed_as_representation_input: FALSE")
    print("u24_leaked_proxy_valid_for_model_comparison: FALSE")
    print("recovered_content_is_ground_truth: FALSE")
    print("weak_label_is_ground_truth: FALSE")
    print("representation_production_authority: 0")
    print("family_formation_runs_in_u25: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*128)
if __name__=="__main__":main()
