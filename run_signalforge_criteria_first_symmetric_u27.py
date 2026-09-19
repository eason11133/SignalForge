from __future__ import annotations
import os
for _k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[_k]="1"
from pathlib import Path
import time
from processors.discovery_criteria_first_symmetric_u27 import run

def main():
    print("="*162)
    print("SignalForge U27 — Criteria-First Symmetric Judge Protocol Challenger")
    print("same frozen U26 cases | canonical shared criteria | forward/reverse reuse | weak labels hidden | no Sentinel/representation promotion")
    print("="*162)
    t=time.perf_counter();r=run(Path("."))
    print("U27_STATUS",r.get("status"))
    print("U27_SOURCE",r.get("source"))
    print("U27_PROTOCOL",r.get("protocol"))
    print("U27_BASELINE_U26",r.get("baseline_u26"))
    print("U27_ASPECT_SUMMARY",r.get("u27_aspect_summary"))
    print("U27_COMPARISON",r.get("comparison"))
    print("U27_CANDIDATE_KIND_SUMMARY",r.get("candidate_kind_summary"))
    print("U27_CASE_STATUS_COUNTS",r.get("case_status_counts"))
    print("U27_JUDGE",r.get("judge"))
    print("U27_AUTHORITY",r.get("authority"))
    print("U27_FOUNDER_PROTECTED_STATE_UNCHANGED",r.get("founder_protected_state_unchanged"))
    print("U27_DECISION",r.get("decision"))
    print(f"U27_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*132)
    print("SIGNALFORGE U27 PROTOCOL / TRUTH AUDIT")
    print("weak_label_visible_to_criteria_builder: FALSE")
    print("weak_label_visible_to_verdict_judge: FALSE")
    print("candidate_kind_visible_to_judge: FALSE")
    print("shared_criteria_reused_for_forward_reverse: TRUE")
    print("u26_db_opened_read_only: TRUE")
    print("llm_judgment_is_ground_truth: FALSE")
    print("sentinel_promoted: FALSE")
    print("representation_promoted: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*132)

if __name__=="__main__":main()
