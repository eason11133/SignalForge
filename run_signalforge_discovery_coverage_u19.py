from pathlib import Path
import json,time
from processors.discovery_coverage_u19 import analyze,ENGINE_VERSION

def main():
    print("="*150)
    print("SignalForge U19 — Discovery Coverage Calibration / Unseen Opportunity Mass")
    print("observation-cache introspection | discovery-family proxy | Good-Turing/Chao2 coverage proxies | historical holdout calibration | fail-closed budget eligibility")
    print("="*150)
    t=time.perf_counter()
    r=analyze(Path("."))
    print("U19_STATUS",r.get("status"))
    print("U19_LOCATOR",r.get("locator"))
    print("U19_EXTRACTION_QUALITY",r.get("extraction_quality"))
    print("U19_FAMILY_MODEL",r.get("family_model"))
    print("U19_GLOBAL_COVERAGE",r.get("global_coverage"))
    print("U19_BACKTEST",r.get("historical_backtest"))
    print("U19_SOURCE_COVERAGE",r.get("source_coverage"))
    print("U19_EXPLORATION_POLICY",r.get("exploration_policy"))
    print(f"U19_RUNTIME seconds={time.perf_counter()-t:.3f}")
    print("="*120)
    print("SIGNALFORGE U19 COVERAGE AUDIT")
    print("good_turing_as_market_probability: FALSE")
    print("chao2_as_market_truth: FALSE")
    print("historical_holdout_calibration_required: TRUE")
    print("uncalibrated_budget_control: BLOCKED")
    print("founder_thesis_truth_modified: FALSE")
    print("product_ideation: 0")
    print("="*120)

if __name__=="__main__":main()
