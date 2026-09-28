from __future__ import annotations

from pathlib import Path


def main() -> int:
    import processors.signalforge_founder_idea_loop as idea_loop

    required = [
        "_bridged_founder_query",
        "_bridged_relevance_query",
        "run_founder_observation_probe",
        "summarize_idea_research_probe",
        "build_founder_research_brief",
        "_research_status",
    ]
    missing = [name for name in required if not hasattr(idea_loop, name)]
    route_source = Path("api/routes/signalforge_research_backlog.py").read_text(encoding="utf-8")
    checks = {
        "fix5_private_contract_present": not missing,
        "batch_uses_deterministic_bridge": "_bridged_founder_query" in route_source and "DETERMINISTIC_BATCH" in route_source,
        "batch_does_not_call_probe_founder_idea": "probe_founder_idea(" not in route_source,
        "batch_declares_zero_ai_calls": '"ai_api_calls": 0' in route_source,
        "batch_does_not_write_market_truth": '"market_truth_writes": 0' in route_source,
    }
    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL"), name)
    if missing:
        print("MISSING", missing)
    if failed:
        return 2
    print("RESEARCH_BACKLOG_V1_2_BATCH_CONTRACT_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
