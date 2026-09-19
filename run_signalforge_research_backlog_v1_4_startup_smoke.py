from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path


async def main() -> int:
    import api.routes.signalforge_research_backlog as route
    from processors.signalforge_research_backlog import add_ideas, load_store, save_store

    original_root = route._REPO_ROOT
    original_sync = route._sync_live_backlog
    original_research = route._research_deterministic_batch
    original_worker = route._worker_task
    original_supervisor = route._autopilot_task

    with tempfile.TemporaryDirectory(prefix="signalforge-startup-smoke-") as tmp:
        repo = Path(tmp)
        route._REPO_ROOT = repo
        route._worker_task = None
        route._autopilot_task = None

        async def scratch_sync():
            return {"status": "SCRATCH_SYNC_OK", "source_counts": {"problem_candidates": 0, "opportunities": 0}, "market_truth_writes": 0}

        async def healthy(_title: str, _description: str):
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

        route._sync_live_backlog = scratch_sync
        route._research_deterministic_batch = healthy

        add_ideas(repo, [{"name": "Startup recovery", "description": "Restart must requeue an interrupted lane without opening the Dashboard"}])
        before = load_store(repo)
        item_id = before["order"][0]
        item = before["items"][item_id]
        item["auto_status"] = "RESEARCHING"
        item["next_job"] = "BASELINE"
        item["latest_change"] = "RESEARCH_BASELINE_STARTED"
        before["worker"]["status"] = "RUNNING"
        before["worker"]["current_item_id"] = item_id
        before["worker"]["current_job"] = "BASELINE"
        save_store(repo, before)

        await route._research_backlog_startup_autopilot()
        for _ in range(300):
            await asyncio.sleep(0.01)
            if route._worker_task is not None and route._worker_task.done():
                break

        after = load_store(repo)
        after_item = after["items"][item_id]
        checks = {
            "startup_created_worker_without_dashboard": route._worker_task is not None,
            "startup_worker_completed": route._worker_task is not None and route._worker_task.done(),
            "interrupted_lane_was_researched": len(after_item.get("history") or []) == 1,
            "interrupted_lane_did_not_stay_researching": after_item.get("auto_status") == "PARKED_NO_PUBLIC_SIGNAL",
            "market_truth_writes_zero": int(after.get("market_truth_writes") or 0) == 0,
        }

        if route._autopilot_task is not None and not route._autopilot_task.done():
            route._autopilot_task.cancel()
            try:
                await route._autopilot_task
            except asyncio.CancelledError:
                pass

        route._REPO_ROOT = original_root
        route._sync_live_backlog = original_sync
        route._research_deterministic_batch = original_research
        route._worker_task = original_worker
        route._autopilot_task = original_supervisor

        for name, ok in checks.items():
            print(("PASS" if ok else "FAIL"), name)
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            print("RESEARCH_BACKLOG_V1_4_STARTUP_SMOKE_FAIL", failed)
            return 2
        print("RESEARCH_BACKLOG_V1_4_STARTUP_SMOKE_PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
