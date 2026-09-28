from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from processors.signalforge_research_backlog import (
    acknowledge_handoff,
    add_ideas,
    auto_run_allowed,
    backlog_detail,
    backlog_view,
    has_pending_work,
    load_store,
    run_batch,
    run_continuous_session,
    save_store,
    sync_backlog,
    _coverage_for_item,
    _job_prompt,
)


def source_limited_partial():
    return {
        "status": "RESEARCH_PARTIAL",
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
            "supporting_evidence": [], "counter_evidence": [],
            "gaps": ["GitHub source failed"],
            "search": {
                "successful_sources": ["HN"],
                "failed_sources": [{"source": "GITHUB", "error": "temporary 503"}],
            },
        },
        "market_truth_writes": 0,
    }




def transport_failed():
    return {
        "status": "SEARCH_FAILED",
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
            "supporting_evidence": [], "counter_evidence": [],
            "gaps": ["All public sources failed"],
            "search": {
                "successful_sources": [],
                "failed_sources": [
                    {"source": "HN", "error": "timeout"},
                    {"source": "GITHUB", "error": "503"},
                ],
            },
        },
        "market_truth_writes": 0,
    }

def no_signal_complete():
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


async def main() -> int:
    checks: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(prefix="sf-v14-source-recovery-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Recovery idea", "description": "Temporary source outage should recover later"}])

        async def limited(_title: str, _description: str):
            return source_limited_partial()

        first = await run_batch(repo, research_fn=limited, max_jobs=1, delay_seconds=0)
        detail = backlog_detail(repo, "idea-" + __import__("hashlib").sha256("recovery idea temporary source outage should recover later".encode()).hexdigest()[:18])
        # Find the only item without depending on the item-id implementation.
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        checks["source_limited_stays_same_lane"] = item.get("auto_status") == "SOURCE_LIMITED" and item.get("next_job") == "BASELINE"
        checks["source_limited_does_not_complete_baseline"] = "BASELINE" not in (item.get("research_coverage") or {}).get("completed_jobs", [])
        checks["source_retry_is_cooldown_bounded"] = int(item.get("source_retry_count") or 0) == 1 and bool(item.get("source_retry_after")) and not has_pending_work(repo)

        # Make the cooldown due without sleeping, then verify the same lane is eligible again.
        item["source_retry_after"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        save_store(repo, store)
        checks["due_source_retry_returns_to_queue"] = has_pending_work(repo)

        async def recovered(_title: str, _description: str):
            return no_signal_complete()

        second = await run_batch(repo, research_fn=recovered, max_jobs=1, delay_seconds=0)
        store2 = load_store(repo)
        item2 = store2["items"][item_id]
        checks["recovered_lane_completes_normally"] = item2.get("auto_status") == "PARKED_NO_PUBLIC_SIGNAL" and "BASELINE" in (item2.get("research_coverage") or {}).get("completed_jobs", [])
        checks["successful_retry_clears_failure_streak"] = int(item2.get("source_retry_count") or 0) == 0 and item2.get("source_retry_after") is None

        current_detail = backlog_detail(repo, item_id)["item"]
        old_hash = current_detail.get("handoff_hash")
        changed = load_store(repo)
        changed["items"][item_id]["why"] = "Background research changed this handoff after the UI loaded it."
        save_store(repo, changed)
        stale = acknowledge_handoff(repo, item_id, expected_hash=old_hash)
        checks["stale_handoff_cannot_exit_founder_inbox"] = stale.get("status") == "STALE_HANDOFF" and load_store(repo)["items"][item_id].get("founder_reviewed_at") is None
        missing_hash = acknowledge_handoff(repo, item_id, expected_hash=None)
        checks["handoff_ack_requires_exact_hash"] = missing_hash.get("status") == "HANDOFF_HASH_REQUIRED" and load_store(repo)["items"][item_id].get("founder_reviewed_at") is None

    with tempfile.TemporaryDirectory(prefix="sf-v14-migrate-limited-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Legacy limited", "description": "Old source-limited records must recover"}])
        legacy = load_store(repo)
        legacy_id = legacy["order"][0]
        legacy_item = legacy["items"][legacy_id]
        legacy_item["auto_status"] = "SOURCE_LIMITED"
        legacy_item["next_job"] = None
        legacy_item.pop("source_retry_after", None)
        legacy_item.pop("source_retry_job", None)
        legacy_item["history"] = [{
            "job": "BASELINE",
            "status": "RESEARCH_PARTIAL",
            "coverage_complete": True,
            "coverage_reason": "RESEARCH_RESULT_COMPLETED",
            "counts": {"useful": 0},
        }]
        save_store(repo, legacy)
        migrated = load_store(repo)
        migrated_item = migrated["items"][legacy_id]
        checks["legacy_source_limited_recovers_lane"] = migrated_item.get("next_job") == "BASELINE" and migrated_item.get("source_retry_job") == "BASELINE"
        checks["legacy_source_limited_is_reclassified_incomplete"] = migrated_item["history"][-1].get("coverage_complete") is False and migrated_item["history"][-1].get("coverage_reason") == "MIGRATED_SOURCE_LIMITED_NOT_COMPLETE"
        checks["legacy_source_limited_becomes_retryable"] = has_pending_work(repo)

    with tempfile.TemporaryDirectory(prefix="sf-v14-crash-repair-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Crash idea", "description": "API restart must not orphan in-flight research"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["auto_status"] = "RESEARCHING"
        item["next_job"] = "BASELINE"
        worker = store["worker"]
        worker["status"] = "RUNNING"
        worker["current_item_id"] = item_id
        worker["current_job"] = "BASELINE"
        save_store(repo, store)
        repaired = load_store(repo, repair_worker=True)
        repaired_item = repaired["items"][item_id]
        checks["api_restart_requeues_interrupted_baseline"] = repaired["worker"]["status"] == "INTERRUPTED" and repaired_item.get("auto_status") == "NEW" and repaired_item.get("next_job") == "BASELINE"
        checks["requeued_item_is_immediately_pending"] = has_pending_work(repo)

        # Same contract for a later research lane.
        repaired_item["auto_status"] = "RESEARCHING"
        repaired_item["next_job"] = "CURRENT_SOLUTIONS"
        repaired["worker"]["status"] = "RUNNING"
        repaired["worker"]["current_item_id"] = item_id
        repaired["worker"]["current_job"] = "CURRENT_SOLUTIONS"
        save_store(repo, repaired)
        repaired2 = load_store(repo, repair_worker=True)
        repaired_item2 = repaired2["items"][item_id]
        checks["api_restart_requeues_interrupted_deep_lane"] = repaired_item2.get("auto_status") == "AUTO_RESEARCH" and repaired_item2.get("next_job") == "CURRENT_SOLUTIONS"

        # A failed/crashed persistence sequence can clear the worker marker but leave the item RESEARCHING.
        # Repair must scan the items themselves instead of trusting worker.status/current_item_id only.
        orphan = load_store(repo)
        orphan_item = orphan["items"][item_id]
        orphan_item["auto_status"] = "RESEARCHING"
        orphan_item["next_job"] = "PAID_DISSATISFACTION"
        orphan_item["latest_change"] = "RESEARCH_PAID_DISSATISFACTION_STARTED"
        orphan["worker"]["status"] = "FAILED"
        orphan["worker"]["current_item_id"] = None
        orphan["worker"]["current_job"] = None
        save_store(repo, orphan)
        orphan_repaired = load_store(repo, repair_worker=True)
        orphan_item2 = orphan_repaired["items"][item_id]
        checks["orphan_researching_item_recovers_without_running_worker_marker"] = (
            orphan_item2.get("auto_status") == "AUTO_RESEARCH"
            and orphan_item2.get("next_job") == "PAID_DISSATISFACTION"
            and item_id in (orphan_repaired.get("worker") or {}).get("recovered_item_ids", [])
        )


    with tempfile.TemporaryDirectory(prefix="sf-v14-negative-coverage-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Thin coverage", "description": "Negative decisions must not rely on one surviving source"}])
        store = load_store(repo)
        item_id = store["order"][0]

        async def weak_partial(_title: str, _description: str):
            result = source_limited_partial()
            result["research_brief"]["summary"]["useful_result_count"] = 1
            result["research_brief"]["summary"]["product_or_service_count"] = 1
            result["research_brief"]["similar_products"] = [{"title": "One weak product", "source": "HN", "url": "https://example.invalid/weak"}]
            return result

        await run_batch(repo, research_fn=weak_partial, max_jobs=1, delay_seconds=0)
        item = load_store(repo)["items"][item_id]
        checks["weak_single_trace_with_thin_coverage_retries"] = item.get("auto_status") == "SOURCE_LIMITED" and item.get("next_job") == "BASELINE"
        checks["thin_coverage_weak_trace_does_not_complete_baseline"] = "BASELINE" not in (item.get("research_coverage") or {}).get("completed_jobs", [])

        # Force the same item into paid-dissatisfaction and verify absence is not trusted on thin coverage.
        store = load_store(repo)
        item = store["items"][item_id]
        item["auto_status"] = "AUTO_RESEARCH"
        item["next_job"] = "PAID_DISSATISFACTION"
        item["source_retry_after"] = None
        item["source_retry_count"] = 0
        save_store(repo, store)
        await run_batch(repo, research_fn=limited, max_jobs=1, delay_seconds=0)
        paid_item = load_store(repo)["items"][item_id]
        checks["paid_absence_with_thin_coverage_retries"] = paid_item.get("auto_status") == "SOURCE_LIMITED" and paid_item.get("next_job") == "PAID_DISSATISFACTION"

        # Repeated entries for the same source must not fake multi-source coverage.
        duplicate_source = source_limited_partial()
        duplicate_source["research_brief"]["search"]["successful_sources"] = ["HN", "HN"]
        store = load_store(repo)
        item = store["items"][item_id]
        item["auto_status"] = "NEW"
        item["next_job"] = "BASELINE"
        item["source_retry_after"] = None
        item["source_retry_count"] = 0
        item["history"] = []
        save_store(repo, store)

        async def duplicate_success(_title: str, _description: str):
            return duplicate_source

        await run_batch(repo, research_fn=duplicate_success, max_jobs=1, delay_seconds=0)
        duplicate_item = load_store(repo)["items"][item_id]
        checks["duplicate_success_source_names_do_not_fake_coverage"] = duplicate_item.get("auto_status") == "SOURCE_LIMITED"

    with tempfile.TemporaryDirectory(prefix="sf-v14-retry-backoff-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Backoff idea", "description": "Repeated outages must eventually cool down to weekly probes"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["auto_status"] = "SOURCE_LIMITED"
        item["next_job"] = "BASELINE"
        item["source_retry_count"] = 6
        item["source_retry_after"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        save_store(repo, store)
        await run_batch(repo, research_fn=limited, max_jobs=1, delay_seconds=0)
        after = load_store(repo)["items"][item_id]
        retry_at = datetime.fromisoformat(str(after.get("source_retry_after")).replace("Z", "+00:00"))
        delay_days = (retry_at - datetime.now(timezone.utc)).total_seconds() / 86400
        checks["repeated_outages_backoff_to_weekly_probe"] = int(after.get("source_retry_count") or 0) == 7 and 6.9 <= delay_days <= 7.1


    with tempfile.TemporaryDirectory(prefix="sf-v14-canonical-refresh-") as tmp:
        repo = Path(tmp)
        sync_backlog(repo, candidates=[{
            "id": 1, "canonical_key": "old-key", "title": "Same opportunity",
            "problem_statement": "A shared problem",
        }])
        sync_backlog(
            repo,
            candidates=[{
                "id": 1, "canonical_key": "new-key", "title": "Same opportunity",
                "problem_statement": "A shared problem",
            }],
            opportunities=[{
                "id": 99, "canonical_key": "new-key", "title": "Same opportunity",
                "problem_statement": "A shared problem",
            }],
        )
        refreshed = load_store(repo)
        checks["canonical_refresh_does_not_split_same_sync_thread"] = len(refreshed.get("order") or []) == 1 and len(refreshed.get("items") or {}) == 1
        only = refreshed["items"][refreshed["order"][0]]
        checks["canonical_refresh_keeps_opportunity_as_alias"] = only.get("canonical_key") == "new-key" and any(str(a.get("source_kind")) == "OPPORTUNITY" for a in (only.get("aliases") or []))

    with tempfile.TemporaryDirectory(prefix="sf-v14-global-circuit-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": f"Outage idea {i}", "description": "A global outage should not be multiplied across the whole backlog"} for i in range(300)])

        async def globally_limited(_title: str, _description: str):
            return transport_failed()

        circuit_batch = await run_batch(repo, research_fn=globally_limited, max_jobs=300, delay_seconds=0)
        circuit_store = load_store(repo)
        circuit_automation = circuit_store.get("automation") or {}
        remaining_new = sum(1 for item in (circuit_store.get("items") or {}).values() if isinstance(item, dict) and item.get("auto_status") == "NEW")
        checks["global_outage_opens_circuit_before_hitting_entire_backlog"] = (
            circuit_batch.get("status") == "SOURCE_CIRCUIT_OPEN"
            and int(circuit_batch.get("jobs_completed") or 0) == 6
            and remaining_new == 294
        )
        checks["global_source_circuit_blocks_immediate_autopilot_restart"] = (
            not auto_run_allowed(repo)
            and int(circuit_automation.get("source_circuit_open_count") or 0) == 1
            and bool(circuit_automation.get("source_circuit_retry_after"))
        )

        # Once the cooldown is due, a healthy research result clears the global circuit state.
        circuit_store["automation"]["source_circuit_retry_after"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        save_store(repo, circuit_store)
        checks["global_source_circuit_becomes_retryable_after_cooldown"] = auto_run_allowed(repo)
        healthy = await run_batch(repo, research_fn=lambda _t, _d: asyncio.sleep(0, result=no_signal_complete()), max_jobs=1, delay_seconds=0)
        healthy_store = load_store(repo)
        checks["healthy_result_clears_global_source_circuit"] = (
            healthy.get("jobs_completed") == 1
            and int((healthy_store.get("automation") or {}).get("source_circuit_open_count") or 0) == 0
            and (healthy_store.get("automation") or {}).get("source_circuit_retry_after") is None
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-soft-limited-no-global-circuit-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": f"Thin coverage {i}", "description": "One surviving source should retry per item without pausing the whole backlog"} for i in range(12)])

        async def thin_but_reachable(_title: str, _description: str):
            return source_limited_partial()

        soft_batch = await run_batch(repo, research_fn=thin_but_reachable, max_jobs=12, delay_seconds=0)
        soft_store = load_store(repo)
        soft_automation = soft_store.get("automation") or {}
        checks["thin_coverage_does_not_open_global_source_circuit"] = (
            int(soft_batch.get("jobs_completed") or 0) == 12
            and soft_batch.get("status") != "SOURCE_CIRCUIT_OPEN"
            and int(soft_automation.get("source_circuit_open_count") or 0) == 0
            and soft_automation.get("source_circuit_retry_after") is None
        )
        checks["thin_coverage_still_uses_per_item_backoff"] = all(
            isinstance(item, dict)
            and item.get("auto_status") == "SOURCE_LIMITED"
            and int(item.get("source_retry_count") or 0) == 1
            for item in (soft_store.get("items") or {}).values()
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-continuous-circuit-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": f"Continuous outage {i}", "description": "Continuous sessions must honor the global source circuit"} for i in range(80)])

        async def continuous_limited(_title: str, _description: str):
            return transport_failed()

        continuous = await run_continuous_session(
            repo, research_fn=continuous_limited, batch_size=50, session_job_cap=5000, delay_seconds=0
        )
        continuous_store = load_store(repo)
        checks["continuous_session_stops_when_global_source_circuit_opens"] = (
            continuous.get("status") == "SOURCE_CIRCUIT_OPEN"
            and int(continuous.get("jobs_completed") or 0) == 6
            and bool(continuous.get("pending_after_session"))
            and (continuous_store.get("worker") or {}).get("status") == "SOURCE_CIRCUIT_OPEN"
        )


    with tempfile.TemporaryDirectory(prefix="sf-v14-small-batch-circuit-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": f"Small batch outage {i}", "description": "Circuit streak must survive batch boundaries"} for i in range(40)])

        async def small_batch_limited(_title: str, _description: str):
            return transport_failed()

        small_batch = await run_continuous_session(
            repo, research_fn=small_batch_limited, batch_size=2, session_job_cap=30, delay_seconds=0
        )
        small_store = load_store(repo)
        checks["global_source_streak_survives_small_batch_boundaries"] = (
            small_batch.get("status") == "SOURCE_CIRCUIT_OPEN"
            and int(small_batch.get("jobs_completed") or 0) == 6
            and int((small_store.get("automation") or {}).get("source_circuit_open_count") or 0) == 1
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-retry-fairness-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [
            {"name": "Retry first", "description": "This source-limited retry is due"},
            {"name": "Promising second", "description": "This already has signal and needs deep research"},
        ])
        store = load_store(repo)
        retry_id, promising_id = store["order"][:2]
        retry_item = store["items"][retry_id]
        retry_item["auto_status"] = "SOURCE_LIMITED"
        retry_item["next_job"] = "BASELINE"
        retry_item["source_retry_after"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        promising_item = store["items"][promising_id]
        promising_item["auto_status"] = "AUTO_RESEARCH"
        promising_item["next_job"] = "CURRENT_SOLUTIONS"
        save_store(repo, store)
        called: list[str] = []

        async def capture_order(title: str, _description: str):
            called.append(title)
            return no_signal_complete()

        await run_batch(repo, research_fn=capture_order, max_jobs=1, delay_seconds=0)
        checks["promising_auto_research_is_not_starved_by_due_source_retries"] = called == ["Promising second"]
        retry_after = load_store(repo)["items"][retry_id]
        checks["deprioritized_source_retry_remains_pending"] = retry_after.get("auto_status") == "SOURCE_LIMITED" and has_pending_work(repo)



    with tempfile.TemporaryDirectory(prefix="sf-v14-deep-lane-wave-fairness-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [
            {"name": "Lane wave A", "description": "Promising direction A"},
            {"name": "Lane wave B", "description": "Promising direction B"},
            {"name": "Lane wave C", "description": "Promising direction C"},
        ])
        store = load_store(repo)
        store["automation"]["initial_baseline_wave_complete"] = True
        for item_id in store["order"]:
            item = store["items"][item_id]
            item["auto_status"] = "AUTO_RESEARCH"
            item["next_job"] = "CURRENT_SOLUTIONS"
        save_store(repo, store)
        lane_calls: list[str] = []

        async def lane_capture(title: str, _description: str):
            lane_calls.append(title)
            return no_signal_complete()

        await run_batch(repo, research_fn=lane_capture, max_jobs=3, delay_seconds=0)
        lane_store = load_store(repo)
        checks["deep_research_advances_breadth_first_by_lane"] = lane_calls == ["Lane wave A", "Lane wave B", "Lane wave C"]
        checks["one_opportunity_cannot_consume_next_lane_before_peers"] = all(
            isinstance(lane_store["items"][item_id], dict)
            and lane_store["items"][item_id].get("next_job") == "PAID_DISSATISFACTION"
            for item_id in lane_store["order"]
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-post-initial-arrival-fairness-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Promising anchor", "description": "Existing signal should not starve forever behind newly arriving candidates"}])
        # Drain the one-item initial wave so later NEW rows are true post-initial arrivals.
        await run_batch(repo, research_fn=lambda _t, _d: asyncio.sleep(0, result=no_signal_complete()), max_jobs=1, delay_seconds=0)
        store = load_store(repo)
        anchor_id = store["order"][0]
        anchor = store["items"][anchor_id]
        anchor["auto_status"] = "AUTO_RESEARCH"
        anchor["next_job"] = "CURRENT_SOLUTIONS"
        anchor["needs_founder"] = False
        save_store(repo, store)
        add_ideas(repo, [
            {"name": f"New arrival {i}", "description": "Continuous upstream candidate feed"}
            for i in range(8)
        ])
        called: list[str] = []

        async def fair_capture(title: str, _description: str):
            called.append(title)
            return no_signal_complete()

        await run_batch(repo, research_fn=fair_capture, max_jobs=4, delay_seconds=0)
        fairness_store = load_store(repo)
        checks["post_initial_new_arrivals_have_bounded_burst"] = (
            called[:3] == ["New arrival 0", "New arrival 1", "New arrival 2"]
            and called[3:4] == ["Promising anchor"]
        )
        checks["deep_research_resets_post_initial_new_burst_budget"] = (
            int((fairness_store.get("automation") or {}).get("post_initial_new_since_deep") or 0) == 0
            and bool((fairness_store.get("automation") or {}).get("initial_baseline_wave_complete"))
        )
        checks["remaining_new_arrivals_stay_pending_after_fairness_yield"] = (
            sum(1 for item in (fairness_store.get("items") or {}).values() if isinstance(item, dict) and item.get("auto_status") == "NEW") == 5
            and has_pending_work(repo)
        )


    with tempfile.TemporaryDirectory(prefix="sf-v14-founder-inbox-global-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [
            {"name": "Founder visible A", "description": "Needs Founder review"},
            {"name": "Founder visible B", "description": "Also needs Founder review"},
        ])
        store = load_store(repo)
        first_id, second_id = store["order"][:2]
        for item_id in (first_id, second_id):
            item = store["items"][item_id]
            item["auto_status"] = "REVIEW_READY"
            item["current_call"] = "公開研究已收斂到值得看"
            item["needs_founder"] = True
            item["research_coverage"] = {"completed_jobs": ["BASELINE"], "unique_evidence": 2, "review_priority": 12}
            item["review_priority"] = 12
        save_store(repo, store)

        filtered = backlog_view(repo, q="this query matches nothing", limit=50)
        checks["founder_inbox_is_not_hidden_by_list_search_filter"] = (
            int(filtered.get("filtered") or 0) == 0
            and len(filtered.get("founder_inbox") or []) == 2
            and int(filtered.get("founder_attention_total") or 0) == 2
        )

        first_detail = backlog_detail(repo, first_id).get("item") or {}
        ack = acknowledge_handoff(repo, first_id, expected_hash=first_detail.get("handoff_hash"))
        after_ack = backlog_view(repo, limit=50)
        inbox_ids = [row.get("id") for row in (after_ack.get("founder_inbox") or [])]
        checks["acknowledged_review_ready_item_leaves_real_attention_count"] = (
            ack.get("status") == "ACKNOWLEDGED"
            and int(after_ack.get("counts", {}).get("REVIEW_READY") or 0) == 2
            and int(after_ack.get("founder_attention_total") or 0) == 1
            and first_id not in inbox_ids
            and second_id in inbox_ids
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-noop-sync-") as tmp:
        repo = Path(tmp)
        candidate = {
            "id": 1, "canonical_key": "stable-key", "title": "Stable candidate",
            "problem_statement": "Repeated live sync should be a true no-op when nothing changed",
        }
        first_sync = sync_backlog(
            repo, candidates=[candidate],
            sync_metadata={"source_counts": {"problem_candidates": 1, "opportunities": 0}, "import_warnings": []},
        )
        store_path = repo / ".radar_runtime" / "idea_research_backlog_v1.json"
        before_bytes = store_path.read_bytes()
        before_store = load_store(repo)
        item_id = before_store["order"][0]
        before_item_updated = before_store["items"][item_id].get("updated_at")
        second_sync = sync_backlog(
            repo, candidates=[candidate],
            sync_metadata={"source_counts": {"problem_candidates": 1, "opportunities": 0}, "import_warnings": []},
        )
        after_bytes = store_path.read_bytes()
        after_store = load_store(repo)
        checks["identical_live_sync_does_not_rewrite_persistent_store"] = bool(first_sync.get("persisted")) and not bool(second_sync.get("persisted")) and before_bytes == after_bytes
        checks["identical_live_sync_does_not_touch_item_updated_at"] = before_item_updated == after_store["items"][item_id].get("updated_at") and int(second_sync.get("refreshed") or 0) == 0

        changed_candidate = dict(candidate)
        changed_candidate["problem_statement"] = "The live DB description actually changed"
        third_sync = sync_backlog(
            repo, candidates=[changed_candidate],
            sync_metadata={"source_counts": {"problem_candidates": 1, "opportunities": 0}, "import_warnings": []},
        )
        checks["material_live_sync_change_is_persisted_once"] = bool(third_sync.get("persisted")) and int(third_sync.get("refreshed") or 0) == 1 and store_path.read_bytes() != after_bytes

    with tempfile.TemporaryDirectory(prefix="sf-v14-store-recovery-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Durable history", "description": "Persistent research should survive a corrupt primary JSON"}])
        first = load_store(repo)
        item_id = first["order"][0]
        first["items"][item_id]["why"] = "snapshot-one"
        save_store(repo, first)
        second = load_store(repo)
        second["items"][item_id]["why"] = "snapshot-two"
        save_store(repo, second)
        store_path = repo / ".radar_runtime" / "idea_research_backlog_v1.json"
        backup_path = repo / ".radar_runtime" / "idea_research_backlog_v1.json.bak"
        checks["previous_valid_store_snapshot_is_kept"] = backup_path.exists()
        store_path.write_text("{ definitely not json", encoding="utf-8")
        recovered = load_store(repo)
        checks["corrupt_primary_recovers_from_previous_valid_backup"] = (
            recovered["items"][item_id].get("why") == "snapshot-one"
            and bool(recovered.get("storage_recovered_from_backup_at"))
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-store-failclosed-") as tmp:
        repo = Path(tmp)
        store_path = repo / ".radar_runtime" / "idea_research_backlog_v1.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("not-json", encoding="utf-8")
        blocked = load_store(repo)
        write_blocked = False
        try:
            save_store(repo, blocked)
        except RuntimeError:
            write_blocked = True
        checks["unreadable_store_without_backup_fails_closed_on_write"] = bool(blocked.get("storage_recovery_required")) and write_blocked and store_path.read_text(encoding="utf-8") == "not-json"

    with tempfile.TemporaryDirectory(prefix="sf-v14-light-list-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": f"List idea {i}", "description": "List endpoint should stay lightweight"} for i in range(40)])
        listing = backlog_view(repo, limit=40)
        checks["backlog_list_does_not_generate_handoff_for_every_item"] = all("handoff" not in row and "handoff_hash" not in row for row in listing.get("items", []))
        one_id = listing["items"][0]["id"]
        one_detail = backlog_detail(repo, one_id).get("item") or {}
        checks["backlog_detail_still_provides_exact_handoff"] = bool(one_detail.get("handoff")) and bool(one_detail.get("handoff_hash"))

    with tempfile.TemporaryDirectory(prefix="sf-v14-failed-progress-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Failure progress", "description": "Failed source attempts should still update the worker progress counter"}])

        async def raises(_title: str, _description: str):
            raise RuntimeError("simulated transport failure")

        failed_batch = await run_batch(repo, research_fn=raises, max_jobs=1, delay_seconds=0)
        failed_store = load_store(repo)
        checks["failed_research_attempt_updates_persisted_job_count"] = failed_batch.get("jobs_completed") == 1 and int((failed_store.get("worker") or {}).get("jobs_completed") or 0) == 1


    with tempfile.TemporaryDirectory(prefix="sf-v14-history-aggregation-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "History accuracy", "description": "Repeated retries must not inflate paid evidence"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        paid_card = {
            "source": "HN",
            "title": "Paid tool still needs manual verification",
            "excerpt": "We pay for the reviewer but still verify completion manually",
            "url": "https://example.invalid/same-paid-comment",
        }
        item["history"] = [
            {
                "job": "PAID_DISSATISFACTION",
                "coverage_complete": True,
                "counts": {"useful": 1},
                "explicit_paid_dissatisfaction": [paid_card],
                "explicit_paid_dissatisfaction_count": 1,
            },
            {
                "job": "PAID_DISSATISFACTION",
                "coverage_complete": False,
                "counts": {"useful": 99},
                "explicit_paid_dissatisfaction": [paid_card],
                "explicit_paid_dissatisfaction_count": 1,
            },
        ]
        coverage = _coverage_for_item(item)
        checks["repeated_paid_evidence_is_deduped_across_history"] = int(coverage.get("paid_dissatisfaction_direct") or 0) == 1
        checks["incomplete_retry_does_not_inflate_completed_lane_useful"] = int((coverage.get("lane_useful") or {}).get("PAID_DISSATISFACTION") or 0) == 1


    with tempfile.TemporaryDirectory(prefix="sf-v14-handoff-lane-balance-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Balanced handoff", "description": "Later paid and buyer evidence must survive a noisy baseline"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        baseline_cards = [
            {"source": "HN", "title": f"Baseline {i}", "excerpt": "baseline", "url": f"https://example.invalid/base-{i}"}
            for i in range(12)
        ]
        item["history"] = [
            {"job": "BASELINE", "coverage_complete": True, "counts": {"useful": 12}, "human_comments": baseline_cards},
            {"job": "PAID_DISSATISFACTION", "coverage_complete": True, "counts": {"useful": 1}, "human_comments": [{"source": "Reddit", "title": "Paid pain", "excerpt": "paid friction", "url": "https://example.invalid/paid-important"}]},
            {"job": "BUYER_PAYER_WTP", "coverage_complete": True, "counts": {"useful": 1}, "supporting": [{"source": "WEB", "title": "Buyer signal", "excerpt": "buyer budget", "url": "https://example.invalid/buyer-important"}]},
            {"job": "COUNTEREVIDENCE", "coverage_complete": True, "counts": {"useful": 1, "counter": 1}, "counterevidence": [{"source": "HN", "title": "Counter", "excerpt": "already good enough", "url": "https://example.invalid/counter"}]},
        ]
        item["auto_status"] = "REVIEW_READY"
        item["needs_founder"] = True
        save_store(repo, store)
        packet = backlog_detail(repo, item_id)["item"].get("handoff") or ""
        checks["handoff_keeps_paid_lane_when_baseline_has_many_cards"] = "https://example.invalid/paid-important" in packet
        checks["handoff_keeps_buyer_lane_when_baseline_has_many_cards"] = "https://example.invalid/buyer-important" in packet
        checks["handoff_keeps_counterevidence_separate"] = "https://example.invalid/counter" in packet

    api_text = (Path(__file__).parent / "api" / "routes" / "signalforge_research_backlog.py").read_text(encoding="utf-8")
    checks["api_startup_resumes_autopilot_without_dashboard"] = '@router.on_event("startup")' in api_text and "_research_backlog_startup_autopilot" in api_text and "await _ensure_worker_started" in api_text
    checks["startup_and_idle_supervisor_repair_stale_persistent_worker_before_pending_check"] = api_text.count("load_store(_REPO_ROOT, repair_worker=True)") >= 3
    client_text = (Path(__file__).parent / "dashboard" / "src" / "api" / "researchBacklog.ts").read_text(encoding="utf-8")
    page_text = (Path(__file__).parent / "dashboard" / "src" / "pages" / "ResearchBacklog.tsx").read_text(encoding="utf-8")
    checks["frontend_sends_exact_handoff_hash"] = "handoffHash: string" in client_text and "handoff_hash: handoffHash" in client_text and "selectedDetail.handoff_hash" in page_text
    checks["paused_source_limited_work_can_be_resumed"] = "waiting + activeResearch + limited > 0" in page_text
    checks["detail_requests_are_sequence_guarded"] = "detailRequestSeq" in page_text and "requestSeq === detailRequestSeq.current" in page_text
    checks["selected_item_never_reuses_previous_detail_handoff"] = "detail?.id === effectiveSelectedId" in page_text and "selectedIsHydrated" in page_text and "disabled={!selectedIsHydrated}" in page_text
    checks["partial_textarea_copy_does_not_ack_whole_handoff"] = "target.selectionStart === 0 && target.selectionEnd === handoff.length" in page_text and "if (copiedWholePacket)" in page_text
    checks["frontend_surfaces_global_source_circuit_cooldown"] = "automation.source_circuit_retry_after" in page_text and "整批已暫時降頻" in page_text


    with tempfile.TemporaryDirectory(prefix="sf-v14-research-context-closure-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "DoneProof", "description": "AI coding agents say they are done but humans still need to verify completion"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["history"] = [
            {
                "job": "BASELINE", "status": "RESEARCH_READY", "coverage_complete": True,
                "human_comments": [{"source": "HN", "title": "Human review is still essential", "excerpt": "We still manually verify agent output before accepting it", "url": "https://example.test/human"}],
                "products": [{"source": "WEB", "title": "CodeRabbit", "excerpt": "AI pull request review product", "url": "https://example.test/coderabbit"}],
                "repos": [], "supporting": [], "counterevidence": [],
                "explicit_paid_dissatisfaction": [],
                "counts": {"useful": 2, "human": 1, "products": 1, "repos": 0, "supporting": 0, "counter": 0},
            },
            {
                "job": "CURRENT_SOLUTIONS", "status": "RESEARCH_READY", "coverage_complete": True,
                "human_comments": [],
                "products": [{"source": "WEB", "title": "CodeRabbit Team", "excerpt": "Paid AI code review for teams", "url": "https://example.test/coderabbit-team"}],
                "repos": [{"source": "HN", "title": "RealDiff", "excerpt": "Runtime behavior diff for generated code", "url": "https://example.test/realdiff"}],
                "supporting": [], "counterevidence": [],
                "explicit_paid_dissatisfaction": [],
                "counts": {"useful": 2, "human": 0, "products": 1, "repos": 1, "supporting": 0, "counter": 0},
            },
            {
                "job": "PAID_DISSATISFACTION", "status": "RESEARCH_READY", "coverage_complete": True,
                "human_comments": [{"source": "REDDIT", "title": "Paying but review still takes time", "excerpt": "We pay for the reviewer but still have to manually verify the important paths", "url": "https://example.test/paid"}],
                "products": [], "repos": [], "supporting": [], "counterevidence": [],
                "explicit_paid_dissatisfaction": [{"source": "REDDIT", "title": "Paying but review still takes time", "excerpt": "We pay for the reviewer but still have to manually verify the important paths", "url": "https://example.test/paid"}],
                "counts": {"useful": 1, "human": 1, "products": 0, "repos": 0, "supporting": 0, "counter": 0},
            },
        ]
        baseline_prompt = _job_prompt(item, "BASELINE")[1]
        paid_prompt = _job_prompt(item, "PAID_DISSATISFACTION")[1]
        buyer_prompt = _job_prompt(item, "BUYER_PAYER_WTP")[1]
        counter_prompt = _job_prompt(item, "COUNTEREVIDENCE")[1]
        checks["baseline_does_not_pollute_itself_with_prior_research_anchors"] = "Previously retrieved research anchors" not in baseline_prompt
        checks["paid_lane_uses_discovered_solution_and_workflow_anchors"] = (
            "Previously retrieved research anchors" in paid_prompt
            and "CodeRabbit Team" in paid_prompt
            and "RealDiff" in paid_prompt
            and "Human review is still essential" in paid_prompt
        )
        checks["buyer_lane_uses_paid_dissatisfaction_anchor"] = (
            "Paying but review still takes time" in buyer_prompt
            and "CodeRabbit Team" in buyer_prompt
            and "UNVALIDATED" in buyer_prompt
        )
        checks["counter_lane_falsifies_against_accumulated_specific_anchors"] = (
            "CodeRabbit Team" in counter_prompt
            and "RealDiff" in counter_prompt
            and "Paying but review still takes time" in counter_prompt
        )
        checks["research_anchor_context_is_bounded"] = len(counter_prompt) < 6500

        noisy = load_store(repo)["items"][item_id]
        noisy["history"] = [{
            "job": "CURRENT_SOLUTIONS", "status": "RESEARCH_READY", "coverage_complete": True,
            "products": [
                {"source": "WEB", "title": f"Product {i}", "excerpt": "Current solution", "url": f"https://example.test/p/{i}"}
                for i in range(12)
            ],
            "repos": [],
            "human_comments": [{"source": "HN", "title": "Human wording must survive", "excerpt": "I still do the last step manually", "url": "https://example.test/human-survive"}],
            "supporting": [], "counterevidence": [], "explicit_paid_dissatisfaction": [],
            "counts": {"useful": 13, "human": 1, "products": 12, "repos": 0, "supporting": 0, "counter": 0},
        }]
        diverse_paid_prompt = _job_prompt(noisy, "PAID_DISSATISFACTION")[1]
        checks["many_products_cannot_crowd_human_wording_out_of_next_search"] = (
            "Product 0" in diverse_paid_prompt and "Human wording must survive" in diverse_paid_prompt
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-multilane-context-chain-") as tmp:
        repo = Path(tmp)
        names = ["Alpha Ops", "Beta Desk", "Gamma Flow"]
        add_ideas(repo, [{"name": name, "description": f"{name} workflow problem"} for name in names])
        calls: list[tuple[str, int, str]] = []
        call_index: dict[str, int] = {}

        def staged_result(*, human=None, products=None, supporting=None, counter=None):
            human = human or []
            products = products or []
            supporting = supporting or []
            counter = counter or []
            return {
                "status": "RESEARCH_READY",
                "research_brief": {
                    "summary": {
                        "useful_result_count": len(human) + len(products) + len(supporting) + len(counter),
                        "human_comment_count": len(human),
                        "product_or_service_count": len(products),
                        "repo_solution_count": 0,
                        "supporting_evidence_count": len(supporting),
                        "counter_evidence_count": len(counter),
                    },
                    "human_comments": human, "similar_products": products, "repo_solutions": [],
                    "supporting_evidence": supporting, "counter_evidence": counter, "gaps": [],
                    "search": {"successful_sources": ["HN", "WEB"], "failed_sources": []},
                },
                "market_truth_writes": 0,
            }

        async def chained_research(title: str, description: str):
            idx = call_index.get(title, 0)
            call_index[title] = idx + 1
            calls.append((title, idx, description))
            slug = title.split()[0]
            if idx == 0:
                return staged_result(human=[{
                    "source": "HN", "title": f"{slug} users still do this manually",
                    "excerpt": f"{slug} teams complain about manual work", "url": f"https://example.test/{slug}/human",
                }])
            if idx == 1:
                return staged_result(products=[{
                    "source": "WEB", "title": f"{slug}Suite",
                    "excerpt": f"{slug}Suite is the current product", "url": f"https://example.test/{slug}/product",
                }])
            if idx == 2:
                return staged_result(human=[{
                    "source": "REDDIT", "title": f"Paying for {slug}Suite but still manual",
                    "excerpt": f"We pay for {slug}Suite but still manually do this work", "url": f"https://example.test/{slug}/paid",
                }])
            if idx == 3:
                return staged_result(supporting=[{
                    "source": "WEB", "title": f"{slug} buyer budget owner",
                    "excerpt": f"Operations lead approves {slug}Suite spend", "url": f"https://example.test/{slug}/buyer",
                }])
            return staged_result(counter=[{
                "source": "HN", "title": f"{slug}Suite may already be good enough",
                "excerpt": "Some teams say the bundled workflow is enough", "url": f"https://example.test/{slug}/counter",
            }])

        chained = await run_continuous_session(
            repo, research_fn=chained_research, batch_size=50, session_job_cap=50, delay_seconds=0
        )
        calls_by_name = {name: [row for row in calls if row[0] == name] for name in names}
        checks["multilane_chain_reaches_review_ready_for_all_test_opportunities"] = (
            chained.get("status") == "IDLE"
            and all(len(calls_by_name[name]) == 5 for name in names)
            and all(item.get("auto_status") == "REVIEW_READY" for item in load_store(repo)["items"].values())
        )
        checks["current_solution_search_uses_baseline_human_wording"] = all(
            f"{name.split()[0]} users still do this manually" in calls_by_name[name][1][2] for name in names
        )
        checks["paid_search_uses_previous_solution_name"] = all(
            f"{name.split()[0]}Suite" in calls_by_name[name][2][2] for name in names
        )
        checks["buyer_and_counter_searches_keep_compounding_prior_specific_evidence"] = all(
            f"Paying for {name.split()[0]}Suite but still manual" in calls_by_name[name][3][2]
            and f"{name.split()[0]} buyer budget owner" in calls_by_name[name][4][2]
            for name in names
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-terminal-question-accuracy-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "No public signal", "description": "A direction with no public evidence"}])

        async def no_signal(_title: str, _description: str):
            return no_signal_complete()

        await run_batch(repo, research_fn=no_signal, max_jobs=1, delay_seconds=0)
        store = load_store(repo)
        item = store["items"][store["order"][0]]
        q = str(item.get("next_question") or "")
        checks["parked_no_signal_does_not_jump_to_buyer_wtp_question"] = (
            item.get("auto_status") == "PARKED_NO_PUBLIC_SIGNAL"
            and "公開來源沒有訊號" in q
            and "不是 buyer/WTP" in q
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-terminal-question-weak-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Weak product only", "description": "Only one product trace exists"}])

        async def weak_product(_title: str, _description: str):
            return {
                "status": "RESEARCH_READY",
                "research_brief": {
                    "summary": {
                        "useful_result_count": 1, "human_comment_count": 0,
                        "product_or_service_count": 1, "repo_solution_count": 0,
                        "supporting_evidence_count": 0, "counter_evidence_count": 0,
                    },
                    "human_comments": [],
                    "similar_products": [{"source": "WEB", "title": "Adjacent tool", "excerpt": "A single solution trace", "url": "https://example.test/adjacent"}],
                    "repo_solutions": [], "supporting_evidence": [], "counter_evidence": [], "gaps": [],
                    "search": {"successful_sources": ["HN", "WEB"], "failed_sources": []},
                },
                "market_truth_writes": 0,
            }

        await run_batch(repo, research_fn=weak_product, max_jobs=1, delay_seconds=0)
        store = load_store(repo)
        item = store["items"][store["order"][0]]
        q = str(item.get("next_question") or "")
        checks["parked_weak_baseline_asks_for_independent_signal_not_later_lane"] = (
            item.get("auto_status") == "PARKED_WEAK_SIGNAL"
            and "第二個獨立真人" in q
            and "buyer/WTP" not in q
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-terminal-question-paid-") as tmp:
        repo = Path(tmp)
        add_ideas(repo, [{"name": "Paid gap", "description": "A promising direction without direct paid dissatisfaction yet"}])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["auto_status"] = "AUTO_RESEARCH"
        item["next_job"] = "PAID_DISSATISFACTION"
        store["automation"]["initial_baseline_wave_complete"] = True
        save_store(repo, store)

        async def no_paid(_title: str, _description: str):
            return no_signal_complete()

        await run_batch(repo, research_fn=no_paid, max_jobs=1, delay_seconds=0)
        item = load_store(repo)["items"][item_id]
        q = str(item.get("next_question") or "")
        checks["parked_paid_lane_keeps_paid_gap_as_biggest_unknown"] = (
            item.get("auto_status") == "PARKED_WEAK_SIGNAL"
            and "已付費／已投入成本" in q
            and "先不浪費 buyer/WTP" in q
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-upstream-reactivation-") as tmp:
        repo = Path(tmp)
        candidate = {
            "id": 1, "canonical_key": "reactivate-1", "title": "Original direction",
            "problem_statement": "Original problem wording", "actor": "operator",
            "market_score": 1.0,
        }
        sync_backlog(repo, candidates=[candidate])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["auto_status"] = "PARKED_NO_PUBLIC_SIGNAL"
        item["next_job"] = None
        item["needs_founder"] = False
        save_store(repo, store)

        unchanged = sync_backlog(repo, candidates=[candidate])
        item = load_store(repo)["items"][item_id]
        checks["unchanged_upstream_snapshot_does_not_reopen_parked_research"] = (
            item.get("auto_status") == "PARKED_NO_PUBLIC_SIGNAL"
            and item.get("next_job") is None
            and unchanged.get("refreshed") == 0
        )

        score_only = dict(candidate)
        score_only["market_score"] = 99.0
        sync_backlog(repo, candidates=[score_only])
        item = load_store(repo)["items"][item_id]
        checks["legacy_score_change_does_not_reopen_market_research"] = (
            item.get("auto_status") == "PARKED_NO_PUBLIC_SIGNAL"
            and item.get("next_job") is None
        )

        materially_changed = dict(score_only)
        materially_changed["problem_statement"] = "New workflow detail says teams still reconcile this manually every day"
        sync_backlog(repo, candidates=[materially_changed])
        item = load_store(repo)["items"][item_id]
        checks["material_upstream_problem_change_reopens_parked_baseline"] = (
            item.get("auto_status") == "AUTO_RESEARCH"
            and item.get("next_job") == "BASELINE"
            and item.get("latest_change") == "UPSTREAM_CONTEXT_CHANGED_RESEARCH_REOPENED"
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-alias-reactivation-") as tmp:
        repo = Path(tmp)
        sync_backlog(repo, candidates=[{
            "id": 5, "canonical_key": "shared-direction", "title": "Shared direction",
            "problem_statement": "Existing wording", "actor": "team",
        }])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["auto_status"] = "REVIEW_READY"
        item["next_job"] = None
        item["needs_founder"] = True
        save_store(repo, store)
        sync_backlog(repo,
            candidates=[{
                "id": 5, "canonical_key": "shared-direction", "title": "Shared direction",
                "problem_statement": "Existing wording", "actor": "team",
            }],
            opportunities=[{
                "id": 7, "canonical_key": "shared-direction", "title": "Shared direction",
                "problem_statement": "Existing wording",
                "who_has_problem": "operations manager",
                "workarounds": ["spreadsheet and manual reconciliation"],
                "existing_solutions": ["legacy suite"],
                "buyer_signals": ["team budget owner involved"],
            }],
        )
        item = load_store(repo)["items"][item_id]
        checks["new_richer_alias_context_reopens_review_ready_research"] = (
            item.get("auto_status") == "AUTO_RESEARCH"
            and item.get("next_job") == "BASELINE"
            and item.get("needs_founder") is False
            and any(str(a.get("source_kind")) == "OPPORTUNITY" for a in (item.get("aliases") or []))
        )

    with tempfile.TemporaryDirectory(prefix="sf-v14-research-cycle-reset-") as tmp:
        repo = Path(tmp)
        original = {
            "id": 11, "canonical_key": "cycle-reset", "title": "Cycle reset",
            "problem_statement": "Original workflow context", "actor": "team",
        }
        sync_backlog(repo, candidates=[original])
        store = load_store(repo)
        item_id = store["order"][0]
        item = store["items"][item_id]
        item["history"] = [
            {"job": "BASELINE", "status": "RESEARCH_READY", "coverage_complete": True, "counts": {"useful": 2}, "human_comments": [], "products": [], "repos": [], "supporting": [], "counterevidence": [], "explicit_paid_dissatisfaction": []},
            {"job": "CURRENT_SOLUTIONS", "status": "RESEARCH_READY", "coverage_complete": True, "counts": {"useful": 1}, "human_comments": [], "products": [], "repos": [], "supporting": [], "counterevidence": [], "explicit_paid_dissatisfaction": []},
        ]
        item["auto_status"] = "REVIEW_READY"
        item["next_job"] = None
        item["needs_founder"] = True
        save_store(repo, store)
        before = _coverage_for_item(item)

        changed = dict(original)
        changed["problem_statement"] = "New workflow evidence changes how the opportunity should be searched"
        sync_backlog(repo, candidates=[changed])
        reopened_store = load_store(repo)
        reopened = reopened_store["items"][item_id]
        after = _coverage_for_item(reopened)
        checks["upstream_research_refresh_preserves_history_but_resets_current_coverage"] = (
            before.get("completed_jobs") == ["BASELINE", "CURRENT_SOLUTIONS"]
            and after.get("completed_jobs") == []
            and len(reopened.get("history") or []) == 2
            and all(bool(entry.get("coverage_superseded")) for entry in (reopened.get("history") or []))
        )
        checks["superseded_history_is_visible_as_prior_cycle_in_handoff"] = "prior-cycle" in backlog_detail(repo, item_id)["item"]["handoff"]

        async def refreshed_baseline(_title: str, _description: str):
            return {
                "status": "RESEARCH_READY",
                "research_brief": {
                    "summary": {
                        "useful_result_count": 1, "human_comment_count": 1,
                        "product_or_service_count": 0, "repo_solution_count": 0,
                        "supporting_evidence_count": 0, "counter_evidence_count": 0,
                    },
                    "human_comments": [{"source": "HN", "title": "New cycle human signal", "excerpt": "new context", "url": "https://example.test/new-cycle"}],
                    "similar_products": [], "repo_solutions": [], "supporting_evidence": [], "counter_evidence": [], "gaps": [],
                    "search": {"successful_sources": ["HN", "WEB"], "failed_sources": []},
                },
                "market_truth_writes": 0,
            }

        await run_batch(repo, research_fn=refreshed_baseline, max_jobs=1, delay_seconds=0)
        refreshed = load_store(repo)["items"][item_id]
        checks["new_cycle_counts_only_fresh_baseline_as_current_coverage"] = _coverage_for_item(refreshed).get("completed_jobs") == ["BASELINE"]

    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL"), name)
    print(f"TOTAL={len(checks)} PASS={len(checks)-len(failed)} FAIL={len(failed)}")
    if failed:
        print("FAILED", failed)
        return 2
    print("RESEARCH_BACKLOG_V1_4_RECOVERY_SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
