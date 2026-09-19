from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from processors.signalforge_research_backlog import (
    add_ideas,
    backlog_view,
    load_store,
    run_continuous_session,
)


def result_no_signal():
    return {
        "status": "RESEARCH_READY",
        "research_brief": {
            "summary": {
                "useful_result_count": 0,
                "human_comment_count": 0,
                "product_or_service_count": 0,
                "repo_solution_count": 0,
                "supporting_evidence_count": 0,
                "counter_evidence_count": 0,
            },
            "human_comments": [], "similar_products": [], "repo_solutions": [],
            "supporting_evidence": [], "counter_evidence": [], "gaps": [],
            "search": {"successful_sources": ["HN", "GITHUB"], "failed_sources": []},
        },
        "market_truth_writes": 0,
    }


async def fake_research(title: str, description: str):
    return result_no_signal()


async def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="sf-v13-continuous-") as tmp:
        repo = Path(tmp)
        ideas = [{"name": f"Idea {i:03d}", "description": f"Problem direction {i:03d}"} for i in range(30)]
        added = add_ideas(repo, ideas)
        checks["imports_multi_batch_directions"] = added.get("total") == 30
        first = await run_continuous_session(repo, research_fn=fake_research, batch_size=10, session_job_cap=5000, delay_seconds=0)
        checks["batches_chain_without_reclick"] = first.get("jobs_completed") == 30
        checks["three_batches_chain"] = first.get("batches_completed") == 3
        checks["queue_drains_to_idle"] = first.get("status") == "IDLE" and not first.get("pending_after_session")
        checks["all_items_receive_baseline_once"] = all((row.get("research_count") == 1) for row in backlog_view(repo, limit=500)["items"])

    with tempfile.TemporaryDirectory(prefix="sf-v13-cap-") as tmp:
        repo = Path(tmp)
        ideas = [{"name": f"Cap Idea {i:03d}", "description": f"Cap problem {i:03d}"} for i in range(25)]
        add_ideas(repo, ideas)
        capped = await run_continuous_session(repo, research_fn=fake_research, batch_size=5, session_job_cap=12, delay_seconds=0)
        pending_before = sum(1 for row in backlog_view(repo, limit=500)["items"] if row.get("auto_status") == "NEW")
        checks["safety_cap_preserves_pending_work"] = capped.get("status") == "SAFETY_CAP_REACHED" and capped.get("jobs_completed") == 12 and pending_before == 13
        resumed = await run_continuous_session(repo, research_fn=fake_research, batch_size=5, session_job_cap=5000, delay_seconds=0)
        checks["next_session_resumes_pending_without_reset"] = resumed.get("status") == "IDLE" and resumed.get("jobs_completed") == 13 and all(row.get("research_count") == 1 for row in backlog_view(repo, limit=500)["items"])

    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items(): print(("PASS" if ok else "FAIL"), name)
    print(f"TOTAL={len(checks)} PASS={len(checks)-len(failed)} FAIL={len(failed)}")
    if failed:
        print("FAILED", failed)
        return 2
    print("RESEARCH_BACKLOG_V1_3_CONTINUOUS_AUTOPILOT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
