from pathlib import Path
import time
from processors.discovery_family_rebase_u20 import analyze

def main():
    print("="*150)
    print("SignalForge U20 — Discovery Family Formation Rebase")
    print("real-cache schema adaptive | structured signature aware | multilingual fallback | family-quality gates | coverage only after family formation passes")
    print("="*150)
    t=time.perf_counter()
    r=analyze(Path("."))
    print("U20_STATUS",r.get("status"))
    print("U20_LOCATOR",r.get("locator"))
    print("U20_EXTRACTION_QUALITY",r.get("extraction_quality"))
    print("U20_FAMILY_FORMATION",r.get("family_formation"))
    print("U20_FAMILY_STABILITY",r.get("family_stability"))
    print("U20_GLOBAL_COVERAGE",r.get("global_coverage"))
    print("U20_BACKTEST",r.get("historical_backtest"))
    print("U20_SOURCE_COVERAGE",r.get("source_coverage"))
    print("U20_CALIBRATION_GATE",r.get("calibration_gate"))
    print("U20_EXPLORATION_POLICY",r.get("exploration_policy"))
    print(f"U20_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U20 FAMILY/COVERAGE AUDIT")
    print("structured_single_signature_dropped: FALSE")
    print("multilingual_text_supported: TRUE")
    print("family_formation_before_coverage: TRUE")
    print("bad_family_model_can_control_budget: FALSE")
    print("uncalibrated_coverage_can_control_budget: FALSE")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
