from __future__ import annotations

import asyncio
import json
import py_compile
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def make_result(*, useful=2, human=1, products=0, repos=0, supporting=1, counter=0, success_sources=None, failed=None, status="RESEARCH_READY", tag="base", paid_dissatisfaction=False):
    success_sources = success_sources if success_sources is not None else ["HACKER_NEWS_ALGOLIA", "GITHUB_SEARCH"]
    failed = failed or []
    def cards(prefix, count):
        label = f"{tag}-{prefix}"
        return [
            {
                "source": "TEST",
                "title": f"{label} {i+1}",
                "excerpt": f"evidence for {label} {i+1}",
                "url": f"https://example.test/{label.lower().replace(' ', '-')}/{i+1}",
                "author": f"u{i+1}",
            }
            for i in range(count)
        ]
    human_cards = cards("Human", human)
    if paid_dissatisfaction and human_cards:
        human_cards[0]["excerpt"] = "We pay for the Pro subscription but still verify the work manually and are considering switching."
    return {
        "status": status,
        "research_brief": {
            "summary": {
                "useful_result_count": useful,
                "human_comment_count": human,
                "product_or_service_count": products,
                "repo_solution_count": repos,
                "supporting_evidence_count": supporting,
                "counter_evidence_count": counter,
            },
            "human_comments": human_cards,
            "similar_products": cards("Product", products),
            "repo_solutions": cards("Repo", repos),
            "supporting_evidence": cards("Support", supporting),
            "counter_evidence": cards("Counter", counter),
            "gaps": [] if useful else ["目前沒有找到夠相關的真人留言。"],
            "search": {
                "successful_sources": success_sources,
                "failed_sources": failed,
            },
        },
        "market_truth_writes": 0,
    }


async def main() -> int:
    import processors.signalforge_research_backlog as backlog_engine
    from processors.signalforge_research_backlog import (
        add_ideas,
        backlog_detail,
        backlog_view,
        JOB_QUESTIONS,
        acknowledge_handoff,
        auto_run_allowed,
        load_store,
        reset_store_for_acceptance,
        resume_auto_run,
        run_batch,
        save_store,
        sync_backlog,
        request_stop,
    )

    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="sf_backlog_accept_") as td:
        repo = Path(td)
        reset_store_for_acceptance(repo)
        candidates = [
            {"id": 1, "canonical_key": "agent verification", "title": "Agent Verification", "problem_statement": "Need to verify AI agent work", "actor": "software team", "buyer_context": "engineering manager owns review cost", "workaround": "manual acceptance checklist", "market_score": 80},
            {"id": 2, "canonical_key": "rfq compare", "title": "RFQ Compare", "problem_statement": "Teams compare supplier quotes manually", "market_score": 70},
            {"id": 3, "canonical_key": "weak no signal", "title": "Weak No Signal", "problem_statement": "Very specific problem nobody discusses", "market_score": 10},
        ]
        first = sync_backlog(repo, candidates=candidates)
        second = sync_backlog(repo, candidates=candidates)
        checks["sync_imports_existing_backlog"] = first["total"] == 3 and first["added"] == 3
        checks["sync_idempotent"] = second["total"] == 3 and second["added"] == 0

        # A live worker marker must not be "repaired" by sync itself; the API layer defers sync while its task is live.
        live_store = load_store(repo)
        live_store["worker"]["status"] = "RUNNING"
        save_store(repo, live_store)
        sync_backlog(repo, candidates=candidates)
        checks["sync_does_not_clobber_live_worker_state"] = load_store(repo)["worker"]["status"] == "RUNNING"
        live_store = load_store(repo)
        live_store["worker"]["status"] = "IDLE"
        save_store(repo, live_store)

        opportunity_merge = sync_backlog(repo, opportunities=[{
            "id": 91,
            "canonical_key": "agent verification",
            "title": "Agent Verification Opportunity",
            "problem_statement": "Need to verify AI agent work",
            "who_has_problem": "software teams using coding agents",
            "why_now": "agent output volume increased",
            "buyer_signals": ["engineering manager"],
            "opportunity_score": 99,
        }])
        merged_detail = backlog_detail(repo, "candidate-1")["item"]
        checks["opportunity_table_merges_into_same_research_thread"] = opportunity_merge["total"] == 3 and opportunity_merge["merged_duplicates"] == 1
        checks["structured_legacy_context_is_preserved"] = (
            merged_detail.get("source_context", {}).get("buyer_context") == "engineering manager owns review cost"
            and merged_detail.get("source_context", {}).get("who_has_problem") == "software teams using coding agents"
        )

        # The actual Founder use case is hundreds of pre-existing directions, not three hand-entered ideas.
        # Verify bulk sync remains one idempotent operation and does not require N manual probes.
        bulk_candidates = [
            {
                "id": 1000 + i,
                "canonical_key": f"bulk-candidate-{i}",
                "title": f"Bulk Candidate {i}",
                "problem_statement": f"Synthetic backlog candidate {i} for scale acceptance",
                "market_score": float(300 - i),
            }
            for i in range(300)
        ]
        bulk_first = sync_backlog(repo, candidates=bulk_candidates)
        bulk_second = sync_backlog(repo, candidates=bulk_candidates)
        checks["bulk_sync_300_without_manual_repaste"] = bulk_first["total"] == 303 and bulk_first["added"] == 300
        checks["bulk_sync_300_idempotent"] = bulk_second["total"] == 303 and bulk_second["added"] == 0

        # V1.2 triage: 60 single weak non-human traces should cost exactly 60 baseline jobs, not 300 deep jobs.
        weak_repo = repo / "weak-scale"
        reset_store_for_acceptance(weak_repo)
        sync_backlog(weak_repo, candidates=[
            {"id": 5000+i, "canonical_key": f"weak-{i}", "title": f"Weak Product {i}", "problem_statement": "single product trace only"}
            for i in range(60)
        ])
        weak_calls = []
        async def weak_research(title: str, description: str):
            weak_calls.append((title, description))
            return make_result(useful=1, human=0, products=1, repos=0, supporting=0, counter=0, tag="weak-product")
        await run_batch(weak_repo, research_fn=weak_research, max_jobs=300, delay_seconds=0)
        weak_view = backlog_view(weak_repo, limit=100)
        checks["weak_single_trace_stops_after_baseline"] = len(weak_calls) == 60 and all(x["auto_status"] == "PARKED_WEAK_SIGNAL" for x in weak_view["items"])
        checks["weak_triage_avoids_5x_search_explosion"] = len(weak_calls) < 60 * len(("BASELINE","CURRENT_SOLUTIONS","PAID_DISSATISFACTION","BUYER_PAYER_WTP","COUNTEREVIDENCE"))

        dup = add_ideas(repo, [{"title": "Agent Verification", "description": "Need to verify AI agent work", "canonical_key": "agent verification"}])
        checks["canonical_duplicate_merged"] = dup["total"] == 303 and dup["merged_duplicates"] == 1

        # Reset the acceptance store so the queue-order assertions below stay small and deterministic.
        reset_store_for_acceptance(repo)
        sync_backlog(repo, candidates=candidates, opportunities=[{
            "id": 91, "canonical_key": "agent verification", "title": "Agent Verification Opportunity",
            "problem_statement": "Need to verify AI agent work", "who_has_problem": "software teams using coding agents",
            "buyer_signals": ["engineering manager"],
        }])

        # Rank 0 must stay rank 0; Python falsy semantics must not push it behind rank 1+.
        rank_view = backlog_view(repo)
        rank_new = [x for x in rank_view["items"] if x["auto_status"] == "NEW"]
        checks["import_rank_zero_is_not_treated_as_missing"] = bool(rank_new) and rank_new[0].get("import_rank") == 0

        calls: list[tuple[str, str]] = []
        baseline_seen: set[str] = set()

        async def research(title: str, description: str):
            calls.append((title, description))
            is_deep = "Research focus:" in description
            if not is_deep:
                baseline_seen.add(title)
                if title == "Weak No Signal":
                    return make_result(useful=0, human=0, supporting=0, success_sources=["HN", "GITHUB"], failed=[] ,status="NO_RELEVANT_RESULTS", tag="baseline-weak")
                if title == "RFQ Compare":
                    return make_result(useful=3, human=2, products=1, supporting=0, counter=0, tag="baseline-rfq")
                return make_result(useful=3, human=2, products=0, supporting=1, counter=0, tag="baseline-agent")
            if "paid dissatisfaction" in description.lower():
                return make_result(useful=4, human=3, products=1, supporting=0, counter=1, tag="paid", paid_dissatisfaction=True)
            if "buyer and payer reality" in description.lower():
                return make_result(useful=3, human=1, products=1, supporting=1, counter=0, tag="buyer")
            if "try to falsify" in description.lower():
                return make_result(useful=3, human=1, products=0, supporting=1, counter=2, tag="counter")
            return make_result(useful=3, human=1, products=1, supporting=1, counter=0, tag="solutions")

        # Exactly three jobs proves wave-1 behavior: all NEW items get baseline before deepening any one item.
        r1 = await run_batch(repo, research_fn=research, max_jobs=3, delay_seconds=0)
        checks["wave1_scans_every_new_item_first"] = len(calls) == 3 and baseline_seen == {"Agent Verification", "RFQ Compare", "Weak No Signal"}
        view = backlog_view(repo)
        by_title = {x["title"]: x for x in view["items"]}
        checks["no_signal_parks_without_market_kill"] = by_title["Weak No Signal"]["auto_status"] == "PARKED_NO_PUBLIC_SIGNAL" and "不等於市場不存在" in by_title["Weak No Signal"]["why"]
        checks["promising_items_auto_continue"] = by_title["Agent Verification"]["auto_status"] == "AUTO_RESEARCH" and by_title["RFQ Compare"]["auto_status"] == "AUTO_RESEARCH"
        checks["next_question_is_explicit_not_prompt_tail"] = (
            by_title["Agent Verification"]["next_question"] == JOB_QUESTIONS["CURRENT_SOLUTIONS"]
            and "Research focus:" not in by_title["Agent Verification"]["next_question"]
        )
        checks["structured_context_reaches_research_query"] = any(
            title == "Agent Verification" and "Imported backlog context (UNVALIDATED" in description and "Buyer context: engineering manager owns review cost" in description
            for title, description in calls
        )

        # Paid-dissatisfaction gate: useful generic material without explicit pay + unresolved friction stops before buyer/WTP.
        paid_repo = repo / "paid-gate"
        reset_store_for_acceptance(paid_repo)
        sync_backlog(paid_repo, candidates=[{"id": 1, "canonical_key": "paid-gate", "title": "Paid Gate", "problem_statement": "test"}])
        paid_calls = []
        async def no_paid_research(title: str, description: str):
            paid_calls.append(description)
            if "Research focus:" not in description:
                return make_result(useful=2, human=1, products=1, supporting=0, tag="pg-base")
            if "paid dissatisfaction" in description.lower():
                return make_result(useful=3, human=2, products=1, supporting=0, tag="pg-paid", paid_dissatisfaction=False)
            return make_result(useful=2, human=1, products=1, supporting=0, tag="pg-other")
        await run_batch(paid_repo, research_fn=no_paid_research, max_jobs=10, delay_seconds=0)
        paid_item = backlog_view(paid_repo)["items"][0]
        checks["no_explicit_paid_signal_stops_before_buyer_wtp"] = paid_item["auto_status"] == "PARKED_WEAK_SIGNAL" and not any("buyer and payer reality" in x.lower() for x in paid_calls)

        # Bounded source retry: one transient exception is retried once and can recover without becoming SOURCE_LIMITED.
        retry_repo = repo / "retry"
        reset_store_for_acceptance(retry_repo)
        sync_backlog(retry_repo, candidates=[{"id": 1, "canonical_key": "retry", "title": "Retry Test", "problem_statement": "test"}])
        retry_calls = 0
        async def retry_research(title: str, description: str):
            nonlocal retry_calls
            retry_calls += 1
            if retry_calls == 1:
                raise RuntimeError("temporary transport failure")
            return make_result(useful=1, human=1, products=0, supporting=0, tag="retry")
        await run_batch(retry_repo, research_fn=retry_research, max_jobs=1, delay_seconds=0)
        retry_view = backlog_view(retry_repo)
        checks["source_failure_gets_one_bounded_retry"] = retry_calls == 2 and int(retry_view["worker"].get("retry_attempts") or 0) == 1
        checks["successful_retry_does_not_become_source_limited"] = retry_view["items"][0]["auto_status"] == "AUTO_RESEARCH"

        # Founder pause survives refresh/sync semantics until an explicit resume.
        request_stop(retry_repo)
        checks["founder_pause_persists"] = auto_run_allowed(retry_repo) is False
        resume_auto_run(retry_repo)
        checks["founder_resume_reenables_autopilot"] = auto_run_allowed(retry_repo) is True

        # Continue enough jobs to take at least one item through all lanes into REVIEW_READY.
        await run_batch(repo, research_fn=research, max_jobs=10, delay_seconds=0)
        view2 = backlog_view(repo)
        ready = [x for x in view2["items"] if x["auto_status"] == "REVIEW_READY"]
        checks["auto_lanes_converge_to_review_ready"] = bool(ready)
        checks["founder_inbox_bounded_to_three"] = len(view2["founder_inbox"]) <= 3 and all(x["needs_founder"] for x in view2["founder_inbox"])

        if ready:
            d = backlog_detail(repo, ready[0]["id"])
            item = d["item"]
            handoff = item["handoff"]
            checks["history_persists_per_opportunity"] = item["research_count"] >= 4 and len(item.get("history") or []) == item["research_count"]
            checks["handoff_is_directly_pasteable"] = all(marker in handoff for marker in (
                "SIGNALFORGE HANDOFF", "CURRENT STATE", "WHAT WE KNOW FROM RETRIEVED MATERIAL",
                "WHAT IS STILL UNKNOWN / GAPS", "ACCUMULATED IMPORTANT EVIDENCE", "ACCUMULATED COUNTEREVIDENCE",
                "RESEARCH HISTORY", "LATEST DELTA", "CURRENT BIGGEST QUESTION", "INSTRUCTIONS FOR CHATGPT",
            ))
            checks["handoff_has_source_links"] = "https://example.test/" in handoff
            checks["handoff_keeps_earlier_round_evidence_after_counter_round"] = (
                "https://example.test/baseline-" in handoff and "https://example.test/paid-" in handoff and "https://example.test/counter-" in handoff
            )
            checks["handoff_labels_imported_context_unvalidated"] = "IMPORTED BACKLOG CONTEXT — UNVALIDATED" in handoff
            checks["coverage_is_not_market_score"] = ("不是 market score" in handoff.lower() or "not market score" in handoff.lower()) and item.get("review_priority", 0) > 0
            before_inbox_ids = [x["id"] for x in backlog_view(repo)["founder_inbox"]]
            current_handoff_hash = backlog_detail(repo, ready[0]["id"])["item"]["handoff_hash"]
            ack = acknowledge_handoff(repo, ready[0]["id"], expected_hash=current_handoff_hash)
            after_inbox_ids = [x["id"] for x in backlog_view(repo)["founder_inbox"]]
            checks["handoff_copy_acknowledgement_removes_item_from_inbox"] = ack.get("status") == "ACKNOWLEDGED" and ready[0]["id"] not in after_inbox_ids
            checks["founder_inbox_rotates_after_copy"] = (len(before_inbox_ids) <= 1) or (after_inbox_ids and after_inbox_ids[0] != before_inbox_ids[0])

            # Simulate an existing HOTFIX3 store that has history but no V1.1 derived coverage fields.
            migration_store = load_store(repo)
            migration_item = migration_store["items"][ready[0]["id"]]
            original_history_count = len(migration_item.get("history") or [])
            migration_item.pop("research_coverage", None)
            migration_item.pop("review_priority", None)
            save_store(repo, migration_store)
            sync_backlog(repo, candidates=candidates)
            migrated = backlog_detail(repo, ready[0]["id"])["item"]
            checks["hotfix3_history_migrates_without_loss"] = (
                migrated["research_count"] == original_history_count
                and len(migrated.get("research_coverage", {}).get("completed_jobs") or []) >= 4
                and migrated.get("review_priority", 0) > 0
            )
        else:
            checks["history_persists_per_opportunity"] = False
            checks["handoff_is_directly_pasteable"] = False
            checks["handoff_has_source_links"] = False
            checks["handoff_keeps_earlier_round_evidence_after_counter_round"] = False
            checks["handoff_labels_imported_context_unvalidated"] = False
            checks["coverage_is_not_market_score"] = False
            checks["hotfix3_history_migrates_without_loss"] = False
            checks["handoff_copy_acknowledgement_removes_item_from_inbox"] = False
            checks["founder_inbox_rotates_after_copy"] = False

        # Founder inbox ordering is research-review readiness, not the old market_score.
        store = load_store(repo)
        ready_ids = [x["id"] for x in backlog_view(repo)["items"] if x["auto_status"] == "REVIEW_READY"]
        if len(ready_ids) >= 2:
            a = store["items"][ready_ids[0]]
            b = store["items"][ready_ids[1]]
            a["needs_founder"] = b["needs_founder"] = True
            a["review_priority"] = 1
            b["review_priority"] = 999
            a.setdefault("legacy", {})["market_score"] = 999
            b.setdefault("legacy", {})["market_score"] = 1
            save_store(repo, store)
            inbox_ranked = backlog_view(repo)["founder_inbox"]
            checks["founder_inbox_uses_review_readiness_not_legacy_market_score"] = bool(inbox_ranked) and inbox_ranked[0]["id"] == ready_ids[1]
        else:
            checks["founder_inbox_uses_review_readiness_not_legacy_market_score"] = False

        store = load_store(repo)
        checks["workflow_state_never_claims_market_truth"] = store.get("market_truth_writes") == 0 and all((x.get("market_truth_writes") or 0) == 0 for x in (store.get("items") or {}).values())
        checks["batch_finished_not_fake_running"] = str(store.get("worker", {}).get("status")) in {"IDLE", "BATCH_LIMIT_REACHED"}


        # V1.3 continuous-autopilot / coverage-integrity checks.
        defaults = backlog_engine._default_store()
        checks["v14_engine_version_retains_v13_contract"] = backlog_engine.ENGINE_VERSION.startswith("signalforge-research-backlog-v1.4")
        checks["continuous_defaults_batch_500"] = defaults["automation"].get("continuous_batch_size") == 500
        checks["continuous_defaults_cap_5000"] = defaults["automation"].get("session_job_cap") == 5000
        checks["idle_poll_default_60_seconds"] = defaults["automation"].get("idle_poll_seconds") == 60
        checks["worker_tracks_continuous_session"] = all(k in defaults["worker"] for k in ("session_jobs_completed", "batches_completed", "batch_size", "session_job_cap", "safety_cap_reached", "pending_after_session"))

        limited = {
            "status": "SEARCH_FAILED",
            "research_brief": {
                "summary": {"useful_result_count": 0, "human_comment_count": 0, "product_or_service_count": 0, "repo_solution_count": 0, "supporting_evidence_count": 0, "counter_evidence_count": 0},
                "search": {"successful_sources": [], "failed_sources": [{"source": "HN", "error": "timeout"}]},
                "human_comments": [], "similar_products": [], "repo_solutions": [], "supporting_evidence": [], "counter_evidence": [], "gaps": ["source failed"],
            },
        }
        snap = backlog_engine._history_snapshot("BASELINE", limited, "2026-09-10T00:00:00+00:00", "2026-09-10T00:00:01+00:00")
        checks["source_failure_snapshot_not_complete"] = snap.get("coverage_complete") is False
        fake_item = {"history": [snap], "next_job": None, "auto_status": "SOURCE_LIMITED"}
        cov = backlog_engine._coverage_for_item(fake_item)
        checks["source_failure_not_counted_as_baseline_complete"] = "BASELINE" not in (cov.get("completed_jobs") or [])
        checks["source_failure_reason_is_explicit"] = snap.get("coverage_reason") == "SOURCE_TRANSPORT_LIMITED_NOT_COMPLETE"
        checks["continuous_session_function_present"] = hasattr(backlog_engine, "run_continuous_session")
        checks["continuous_session_market_truth_zero"] = defaults.get("market_truth_writes") == 0 and backlog_engine.TRUTH_BOUNDARY.startswith("RESEARCH_BACKLOG")
        checks["source_limited_remains_non_founder_terminal"] = "SOURCE_LIMITED" in backlog_engine.TERMINAL_AUTO_STATES

    static = {
        "api/routes/signalforge_research_backlog.py": [
            "/research-backlog/sync", "/research-backlog/start", "/research-backlog/stop", "/handoff-copied", "_sync_live_backlog", "_research_deterministic_batch", "DETERMINISTIC_BATCH", "SYNC_DEFERRED_WHILE_RESEARCH_RUNNING", "Opportunity", "_autopilot_supervisor", "_IDLE_POLL_SECONDS", "_SESSION_JOB_CAP",
        ],
        "dashboard/src/pages/ResearchBacklog.tsx": [
            "不用再一個一個貼", "ProblemCandidate 與 Opportunity backlog", "恢復自動研究", "暫停自動研究", "給 ChatGPT", "複製這段", "onCopy",
        ],
        "dashboard/src/api/researchBacklog.ts": [
            "ResearchBacklogResponse", "getResearchBacklog", "startResearchBacklog", "syncResearchBacklog", "acknowledgeResearchBacklogHandoff",
        ],
        "run_signalforge_research_backlog_v1_2_live_import_smoke.py": [
            "_load_problem_candidates", "_load_opportunities", "TemporaryDirectory",
            "existing_signalforge_rows_found", "pasteable_detail_handoff_generated",
            "smoke_uses_temporary_backlog_not_production_history", "persistent_production_backlog_touched",
            "market_truth_writes_zero", "automation_state_present",
        ],
        "run_signalforge_research_backlog_v1_4_startup_smoke.py": [
            "_research_backlog_startup_autopilot", "Startup recovery", "startup_created_worker_without_dashboard",
            "interrupted_lane_was_researched", "market_truth_writes_zero",
        ],
        "dashboard/src/App.tsx": ["ResearchBacklog", 'path="research-one"'],
        "dashboard/src/components/Sidebar.tsx": ["研究工作台", "臨時查一個 idea"],
    }
    for rel, markers in static.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        checks[f"static:{rel}"] = all(marker in text for marker in markers)

    integration = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
    checks["runtime_router_include_is_installed"] = (
        "R8_RESEARCH_BACKLOG_V1_HOTFIX3_ROUTER_INCLUDE" in integration
        and "signalforge_research_backlog" in integration
        and "include_router" in integration
    )

    sidebar = (ROOT / "dashboard/src/components/Sidebar.tsx").read_text(encoding="utf-8")
    checks["no_chatgpt_discussion_button_in_sidebar"] = "跟 ChatGPT 討論" not in sidebar
    page = (ROOT / "dashboard/src/pages/ResearchBacklog.tsx").read_text(encoding="utf-8")
    checks["handoff_is_plain_selectable_text_not_chatgpt_action"] = (
        "<textarea" in page and "Ctrl+C" in page and "跟 GPT 討論" not in page
    )
    processor_text = (ROOT / "processors/signalforge_research_backlog.py").read_text(encoding="utf-8")
    route_text = (ROOT / "api/routes/signalforge_research_backlog.py").read_text(encoding="utf-8")
    checks["batch_path_avoids_per_item_llm_bridge"] = ("probe_founder_idea(" not in route_text and "DETERMINISTIC_BATCH" in route_text and '"ai_api_calls": 0' in route_text)
    checks["handoff_includes_evidence_excerpts_and_counterevidence"] = (
        "ACCUMULATED IMPORTANT EVIDENCE" in processor_text
        and "ACCUMULATED COUNTEREVIDENCE" in processor_text
        and "RESEARCH HISTORY" in processor_text
        and 'row.get("excerpt")' in processor_text
    )

    for rel in (
        "processors/signalforge_research_backlog.py",
        "api/routes/signalforge_research_backlog.py",
        "api/routes/signalforge.py",
        "run_signalforge_research_backlog_v1_2_live_import_smoke.py",
        "run_signalforge_research_backlog_v1_4_startup_smoke.py",
    ):
        py_compile.compile(str(ROOT / rel), doraise=True)
    checks["python_compile"] = True

    failed = [name for name, ok in checks.items() if not ok]
    print("SIGNALFORGE_RESEARCH_BACKLOG_V1_ACCEPTANCE")
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"TOTAL={len(checks)} PASS={len(checks)-len(failed)} FAIL={len(failed)}")
    if failed:
        print("FAILED:", json.dumps(failed, ensure_ascii=False))
        return 2
    print("RESEARCH_BACKLOG_V1_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
