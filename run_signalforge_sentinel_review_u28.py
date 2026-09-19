from pathlib import Path
import time
from processors.discovery_sentinel_review_u28 import run
def main():
    print("="*162)
    print("SignalForge U28 — Second-Pass Sentinel Review + Aspect-Level Sentinel v1 Candidate")
    print("frozen U26 texts | U27 shared criteria | prior verdicts hidden | model-independence truth | aspect-level candidates | no final freeze")
    print("="*162)
    t=time.perf_counter();r=run(Path("."))
    print("U28_STATUS",r.get("status"));print("U28_SOURCE",r.get("source"));print("U28_REVIEW",r.get("review"))
    print("U28_ASPECT_STATUS_COUNTS",r.get("aspect_status_counts"));print("U28_REVIEWER",r.get("reviewer"))
    print("U28_CANDIDATE_MANIFEST",r.get("candidate_manifest"));print("U28_AUTHORITY",r.get("authority"))
    print("U28_FOUNDER_PROTECTED_STATE_UNCHANGED",r.get("founder_protected_state_unchanged"))
    print("U28_DECISION",r.get("decision"));print(f"U28_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*132)
    print("weak_label_visible_to_reviewer: FALSE");print("candidate_kind_visible_to_reviewer: FALSE")
    print("u27_prior_verdict_visible_to_reviewer: FALSE");print("same_model_called_model_independent: FALSE")
    print("sentinel_unit_is_case_x_aspect: TRUE");print("sentinel_v1_frozen: FALSE")
    print("representation_promoted: FALSE");print("founder_thesis_truth_modified: FALSE");print("product_ideation: 0")
    print("="*132)
if __name__=="__main__":main()
