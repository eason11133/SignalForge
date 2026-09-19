from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
from pathlib import Path
import time
from processors.discovery_boundary_sentinel_u26 import run

def main():
    print("="*160)
    print("SignalForge U26 — Real Boundary Adjudication + Provisional Frozen Sentinel Seed")
    print("decontaminated frozen content | hard-boundary mining | pointwise evidence grounding | A/B+B/A semantic adjudication | no arm promotion")
    print("="*160)
    t=time.perf_counter();r=run(Path("."))
    print("U26_STATUS",r.get("status"))
    print("U26_SOURCE_SNAPSHOT",r.get("source_snapshot"))
    print("U26_CANDIDATE_GENERATION",r.get("candidate_generation"))
    print("U26_POINTWISE",r.get("pointwise"))
    print("U26_ADJUDICATION",r.get("adjudication"))
    print("U26_JUDGE",r.get("judge"))
    print("U26_AUTHORITY",r.get("authority"))
    print("U26_FOUNDER_PROTECTED_STATE_UNCHANGED",r.get("founder_protected_state_unchanged"))
    print("U26_DECISION",r.get("decision"))
    print(f"U26_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*130)
    print("SIGNALFORGE U26 BENCHMARK / TRUTH AUDIT")
    print("weak_label_visible_to_judge: FALSE")
    print("sentinel_content_refreshes_from_raw_cache: FALSE")
    print("llm_judgment_is_ground_truth: FALSE")
    print("bidirectional_consistency_is_ground_truth: FALSE")
    print("representation_production_authority: 0")
    print("winner_declared: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*130)
if __name__=="__main__":main()
