from pathlib import Path
from processors.discovery_boundary_diagnostic_u26_1 import analyze

def main():
    print("="*156)
    print("SignalForge U26.1 — Boundary Adjudication Failure Diagnostic (READ ONLY)")
    print("="*156)
    r=analyze(Path("."))
    print("U26_1_STATUS",r.get("status"))
    print("U26_1_ROOT_CAUSES",r.get("root_cause_counts"))
    print("U26_1_INSUFFICIENT_BREAKDOWN",r.get("insufficient_breakdown"))
    print("U26_1_ASPECT_SUMMARY",r.get("aspect_summary"))
    print("U26_1_CANDIDATE_KIND_SUMMARY",r.get("candidate_kind_summary"))
    print("U26_1_EXAMPLES",r.get("examples"))
    print("U26_1_DECISION",r.get("decision"))
    print("="*126)
    print("llm_calls: 0")
    print("u26_db_modified: FALSE")
    print("sentinel_promoted: FALSE")
    print("representation_authority_changed: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*126)

if __name__=="__main__": main()
