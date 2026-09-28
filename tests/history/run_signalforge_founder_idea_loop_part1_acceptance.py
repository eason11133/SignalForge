#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent


def _stub_database() -> None:
    if "database.connection" in sys.modules:
        return
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")

    class Dummy:
        id = candidate_id = claim_id = evidence_id = case_id = None

    async def _session():  # pragma: no cover - pure Part 1 acceptance never opens DB
        raise RuntimeError("DB stub should not be used in Part 1 pure acceptance")

    for name in ("ProblemCandidate", "RadarCase", "RadarClaim", "RadarClaimEvidence", "RadarEvidence"):
        setattr(conn, name, Dummy)
    conn.async_session = _session
    sys.modules["database.connection"] = conn
    setattr(db_pkg, "connection", conn)


def check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, bool(ok), detail


def _fixture_request(url: str, **_: object):
    host = urlparse(url).netloc
    if "hn.algolia.com" in host:
        return {
            "hits": [
                {
                    "title": "AI assistants keep forgetting project rules",
                    "comment_text": "We pay $20/month for the assistant but still have to manually paste our instructions every session.",
                    "objectID": "101", "story_id": "101", "author": "founder", "created_at": "2026-09-01T00:00:00Z",
                },
                {
                    "title": "Persistent memory workaround for coding agents",
                    "comment_text": "Our workaround is a checklist plus a rules file because the agent forgets context.",
                    "objectID": "102", "story_id": "102", "author": "builder", "created_at": "2026-09-02T00:00:00Z",
                },
            ]
        }, {"status_code": 200, "elapsed_ms": 5}
    if "api.stackexchange.com" in host:
        return {
            "items": [
                {
                    "title": "How to stop an AI coding assistant forgetting custom instructions?",
                    "tags": ["ai", "instructions", "memory"], "link": "https://stackoverflow.com/q/1",
                    "owner": {"display_name": "dev"}, "creation_date": 1788307200, "score": 7, "answer_count": 3, "is_answered": True,
                }
            ], "quota_remaining": 299,
        }, {"status_code": 200, "elapsed_ms": 6}
    if "api.github.com" in host and "/search/issues" in url:
        return {
            "items": [
                {
                    "title": "Agent forgets repository instructions after context compaction",
                    "body": "We still manually re-check rules after every compaction. This is unreliable for delivery.",
                    "html_url": "https://github.com/example/agent/issues/9", "user": {"login": "teamlead"},
                    "created_at": "2026-08-31T00:00:00Z", "comments": 18, "state": "open", "repository_url": "https://api.github.com/repos/example/agent",
                }
            ]
        }, {"status_code": 200, "elapsed_ms": 7, "rate_remaining": "8"}
    if "api.github.com" in host and "/search/repositories" in url:
        return {
            "items": [
                {
                    "full_name": "example/persistent-agent-rules", "name": "persistent-agent-rules",
                    "description": "Persist project rules and memory for AI coding agents",
                    "html_url": "https://github.com/example/persistent-agent-rules", "owner": {"login": "example"},
                    "created_at": "2026-01-01T00:00:00Z", "stargazers_count": 420, "forks_count": 22, "language": "Python", "license": {"spdx_id": "MIT"},
                }
            ]
        }, {"status_code": 200, "elapsed_ms": 8, "rate_remaining": "7"}
    raise AssertionError(f"unexpected fixture URL: {url}")


def main() -> int:
    _stub_database()
    loop = importlib.import_module("processors.signalforge_founder_idea_loop")
    results: list[tuple[str, bool, str]] = []

    queries = loop.expand_founder_query("AI 常忘記規則")
    joined = " ".join(queries).lower()
    results.append(check("real founder task expands deterministically", len(queries) >= 2 and "forget" in joined and "rules" in joined, repr(queries)))
    results.append(check("query fanout is bounded", len(queries) <= 3, repr(queries)))

    old_request = loop._request_json
    loop._request_json = _fixture_request
    try:
        fresh = loop.run_fresh_fast_probe("AI 常忘記規則")
    finally:
        loop._request_json = old_request
    summary = loop.summarize_fresh_probe(fresh)
    results.append(check("configured fast sources all executed", len(fresh.get("sources") or []) == 4))
    results.append(check("fast probe needs zero AI API", "openai" not in (ROOT / "processors/signalforge_founder_idea_loop.py").read_text(encoding="utf-8").lower()))
    results.append(check("fast probe returns real-style discussions", summary["problem_discussions"] >= 3, str(summary)))
    results.append(check("fast probe surfaces existing solution", summary["existing_solutions"] >= 1, str(summary)))
    results.append(check("paid signal surfaced", summary["paid_signals"] >= 1, str(summary)))
    results.append(check("paid dissatisfaction surfaced", summary["post_purchase_complaints"] >= 1, str(summary)))
    results.append(check("spend trace remains unvalidated", bool(summary["spend_observations"]) and all(x.get("truth_status") == "UNVALIDATED_SEARCH_TRACE" and x.get("evidence_grade") == "UNVALIDATED_TRACE" for x in summary["spend_observations"])))
    results.append(check("fresh trace coverage visible", summary["coverage"] == "COMPLETE_FOR_CONFIGURED_FAST_SOURCES", summary["coverage"]))
    results.append(check("all fast traces explicitly unvalidated", all(x.get("truth_status") == "UNVALIDATED_SEARCH_TRACE" for x in fresh.get("traces") or [])))

    frontier = loop.build_decision_frontier(published_money_trail={"revenue_wedge": {}, "paid_dissatisfaction": {"count": 0}}, fresh_summary=summary)
    results.append(check("exactly one decision-changing question", isinstance(frontier.get("question"), str) and len(frontier["question"]) > 8))
    results.append(check("decision frontier has advance and kill", bool(frontier.get("advance_if")) and bool(frontier.get("kill_if"))))
    results.append(check("decision frontier stops useless research", len(frontier.get("do_not_research") or []) >= 1))

    def always_fail(url: str, **_: object):
        raise loop.FetchError("network unavailable")

    loop._request_json = always_fail
    try:
        failed_fresh = loop.run_fresh_fast_probe("AI 常忘記規則")
    finally:
        loop._request_json = old_request
    failed_summary = loop.summarize_fresh_probe(failed_fresh)
    failed_frontier = loop.build_decision_frontier(published_money_trail={"revenue_wedge": {}}, fresh_summary=failed_summary)
    results.append(check("source failures are fail-visible", failed_summary["coverage"] == "FAILED" and all(x["status"] == "FAILED" for x in failed_summary["source_health"])))
    results.append(check("failed search never means no market", "搜尋失敗" in failed_frontier["kill_if"] and "沒有競品" in " ".join(failed_frontier["do_not_research"])))

    async def fake_published(*, title: str, description: str = ""):
        return {
            "status": "NO_RELATED_PUBLISHED_EVIDENCE", "title": title, "problem": description,
            "revenue_wedge": {"existing_spend": "UNKNOWN", "buyer_reality": "UNKNOWN", "unresolved_gap": "UNKNOWN", "buyer_reachability": "UNKNOWN"},
            "paid_dissatisfaction": {"count": 0}, "truth_boundary": "PUBLISHED_ONLY_FIXTURE",
        }

    async def run_whole() -> dict:
        old_pub = loop.probe_money_trail_direction
        old_fast = loop.run_fresh_fast_probe
        loop.probe_money_trail_direction = fake_published
        loop.run_fresh_fast_probe = lambda title, description="": fresh
        try:
            return await loop.probe_founder_idea(title="AI 常忘記規則")
        finally:
            loop.probe_money_trail_direction = old_pub
            loop.run_fresh_fast_probe = old_fast

    whole = asyncio.run(run_whole())
    results.append(check("published money trail stays separate", whole.get("published_money_trail", {}).get("truth_boundary") == "PUBLISHED_ONLY_FIXTURE"))
    results.append(check("part1 creates zero market truth writes", whole.get("market_truth_writes") == 0))
    results.append(check("part1 reports zero AI API calls", whole.get("ai_api_calls") == 0))
    results.append(check("Today exposes same single frontier question", whole.get("today", {}).get("one_question") == whole.get("decision_frontier", {}).get("question")))

    route = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
    source = (ROOT / "processors/signalforge_founder_idea_loop.py").read_text(encoding="utf-8")
    ui = (ROOT / "dashboard/src/pages/MoneyTrail.tsx").read_text(encoding="utf-8")
    client = (ROOT / "dashboard/src/api/client.ts").read_text(encoding="utf-8")
    hooks = (ROOT / "dashboard/src/api/hooks.ts").read_text(encoding="utf-8")
    results.append(check("Founder Idea API endpoint exists", "@router.post('/founder-idea/probe')" in route and "probe_founder_idea" in route))
    results.append(check("new engine has no direct Radar mutation authority", "update(RadarClaim" not in source and "delete(RadarClaim" not in source and "add(RadarClaim" not in source and "async_session" not in source))
    results.append(check("client and hook expose Founder Idea probe", "probeSignalForgeFounderIdea" in client and "useProbeSignalForgeFounderIdea" in hooks))
    results.append(check("Founder task begins at one idea input", "Probe 這個 idea" in ui and "Fast Reality Check" in ui))
    results.append(check("Founder sees source failure visibility", "Search coverage / failure visibility" in ui and "搜尋失敗 ≠ 市場不存在" in ui))
    results.append(check("Founder sees one Decision Frontier", "The One Question That Matters Next" in ui))
    results.append(check("Founder sees Today advance kill", "Today / 下一步" in ui and "Advance if" in ui and "Kill if" in ui))
    results.append(check("fresh traces visibly separated from Published Money Trail", "未驗證 trace" in ui and "Published Money Trail" in ui and "Fresh trace 不會偷偷混進這裡" in ui))

    failed = [x for x in results if not x[1]]
    print("=" * 96)
    print("SIGNALFORGE PART 1 — FOUNDER IDEA LOOP — REAL FOUNDER TASK ACCEPTANCE")
    print("=" * 96)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}" + (f" — {detail}" if detail else ""))
    print("-" * 96)
    print(f"RESULT: {len(results)-len(failed)}/{len(results)} PASS")
    if failed:
        print("FINAL_STATUS: SIGNALFORGE_FOUNDER_IDEA_LOOP_PART1_ACCEPTANCE_FAIL")
        return 1
    print("FINAL_STATUS: SIGNALFORGE_FOUNDER_IDEA_LOOP_PART1_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
