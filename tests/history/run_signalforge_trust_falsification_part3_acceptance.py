from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def check(name: str, condition: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, bool(condition), detail)


def make_run(theme: str, query: str, *, status: str = "PASS", source_statuses: list[tuple[str, str]] | None = None, traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    statuses = source_statuses or [("HACKER_NEWS_ALGOLIA", "SUCCESS"), ("STACK_OVERFLOW_API", "SUCCESS")]
    return {
        "status": status,
        "falsification_theme": theme,
        "falsification_query": query,
        "sources": [
            {"source": source, "status": st, "count": 1 if st == "SUCCESS" else 0, "traces": [], "transport": {}, **({"error": "fixture failure"} if st != "SUCCESS" else {})}
            for source, st in statuses
        ],
        "traces": traces or [],
    }


def main() -> int:
    from processors import signalforge_trust_falsification as trust

    results: list[tuple[str, bool, str]] = []

    queries = trust.build_falsification_queries("AI agent forgets rules", "persistent instruction reliability")
    results.append(check("Try-to-Kill has bounded query set", len(queries) == 3, str(len(queries))))
    joined = " ".join(x["query"] for x in queries).lower()
    results.append(check("falsification searches current-solution-good-enough", "good enough" in joined and "native" in joined))
    results.append(check("falsification searches no-budget/low-value", "not worth paying" in joined and "no budget" in joined))
    results.append(check("falsification searches switching/trust/failure", "switching cost" in joined and "trust" in joined and "no traction" in joined))

    counter_trace = {
        "source": "HACKER_NEWS_ALGOLIA",
        "kind": "DISCUSSION",
        "title": "Built-in memory is good enough for our team",
        "excerpt": "We would not pay for another tool; native support already handles it.",
        "url": "https://example.test/counter-1",
        "truth_status": "UNVALIDATED_SEARCH_TRACE",
    }
    duplicate_trace = dict(counter_trace)
    runs = [
        make_run("CURRENT_SOLUTION_GOOD_ENOUGH", "q1", traces=[counter_trace]),
        make_run("NO_BUDGET_OR_LOW_VALUE", "q2", traces=[duplicate_trace]),
        make_run("SWITCHING_TRUST_OR_MARKET_FAILURE", "q3", source_statuses=[("GITHUB_ISSUES", "SUCCESS"), ("STACK_OVERFLOW_API", "FAILED")]),
    ]
    summary = trust.summarize_falsification_runs(runs)
    results.append(check("counterevidence traces deduplicate across kill themes", summary["candidate_count"] == 1, str(summary["candidate_count"])))
    candidate = summary["candidates"][0]
    results.append(check("fresh kill hit is explicitly unvalidated", candidate["truth_status"] == "UNVALIDATED_COUNTEREVIDENCE_CANDIDATE"))
    results.append(check("one hit can expose multiple counter categories", "CURRENT_SOLUTION_GOOD_ENOUGH" in candidate["counterevidence_categories"] and "NO_BUDGET_OR_LOW_VALUE" in candidate["counterevidence_categories"]))
    results.append(check("partial source failure remains visible", summary["coverage"] == "PARTIAL" and summary["failed_source_runs"] == 1))
    results.append(check("partial coverage does not hide successful searches", summary["successful_source_runs"] == 5, str(summary["successful_source_runs"])))
    results.append(check("fresh counterevidence never claims Published contradiction", summary["interpretation"] == "COUNTEREVIDENCE_CANDIDATES_FOUND_REQUIRES_VALIDATION"))

    no_hit = trust.summarize_falsification_runs([
        make_run("CURRENT_SOLUTION_GOOD_ENOUGH", "q", traces=[]),
    ])
    results.append(check("no hit is scoped to successful configured searches", no_hit["interpretation"] == "NO_COUNTEREVIDENCE_FOUND_IN_SUCCESSFUL_CONFIGURED_SEARCHES"))
    results.append(check("no hit message refuses universal absence claim", "不等於" in no_hit["message"] and "不存在" in no_hit["message"]))

    failed = trust.summarize_falsification_runs([
        make_run("NO_BUDGET_OR_LOW_VALUE", "q", source_statuses=[("HN", "FAILED"), ("GITHUB", "RATE_LIMITED")]),
    ])
    results.append(check("failed falsification coverage is fail-visible", failed["coverage"] == "FAILED"))
    results.append(check("failed search produces no market conclusion", failed["interpretation"] == "SEARCH_FAILED_NO_MARKET_CONCLUSION"))

    evidence_rows = [
        {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "Agency is the buyer", "stance": "SUPPORT", "validated": True, "source_type": "REDDIT", "source_title": "Agency owner thread", "source_url": "https://a", "source_family_key": "org:a", "excerpt": "We pay senior reviewers.", "directness": "FIRST_PERSON", "authority_class": "FIRSTHAND", "rationale": "buyer direct"},
        {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "Agency is the buyer", "stance": "SUPPORT", "validated": True, "source_type": "HN", "source_title": "Founder comment", "source_url": "https://b", "source_family_key": "org:b", "excerpt": "Our agency budget covers QA.", "directness": "FIRST_PERSON", "authority_class": "FIRSTHAND", "rationale": "independent"},
        {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "Agency is the buyer", "stance": "CONTRADICT", "validated": True, "source_type": "INTERVIEW", "source_title": "Agency C", "source_url": "https://c", "source_family_key": "org:c", "excerpt": "We would not buy a separate QA tool.", "directness": "FIRST_PERSON", "authority_class": "FIRSTHAND", "rationale": "counter"},
        {"claim_code": "C07", "claim_state": "UNKNOWN", "claim_statement": "Gap remains", "stance": "INSUFFICIENT", "validated": True, "source_type": "WEB", "source_title": "Product doc", "source_url": "https://d", "source_family_key": "vendor:d", "excerpt": "Feature exists.", "directness": "INDIRECT", "authority_class": "VENDOR", "rationale": "does not prove gap"},
        {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "Should be ignored", "stance": "SUPPORT", "validated": False, "source_type": "SHADOW", "source_title": "Unvalidated", "source_url": "https://shadow", "source_family_key": "shadow", "excerpt": "shadow only"},
    ]
    thesis = {"thesis_id": "thesis:agency-qa", "representative_title": "Agency QA", "claim_states": {"C05": "SUPPORTED", "C07": "UNKNOWN", "C11": "UNKNOWN"}}
    replay = trust.build_evidence_replay_from_rows(thesis=thesis, evidence_rows=evidence_rows)
    results.append(check("Evidence Replay only consumes validated links", replay["summary"]["validated_evidence_links"] == 4, str(replay["summary"])))
    results.append(check("Evidence Replay exposes support and contradiction separately", replay["summary"]["supporting"] == 2 and replay["summary"]["contradicting"] == 1))
    c05 = next(x for x in replay["claims"] if x["claim_code"] == "C05")
    results.append(check("Evidence Replay exposes source independence", c05["independent_source_families"] == 3, str(c05["independent_source_families"])))
    results.append(check("Evidence Replay preserves Unknown claims", any(x["claim_code"] == "C11" and x["state"] == "UNKNOWN" for x in replay["claims"])))
    results.append(check("Evidence Replay does not invent full search coverage", replay["search_coverage"]["status"] == "LEDGER_REPLAY_ONLY"))
    results.append(check("Evidence Replay creates zero Market Truth writes", replay["market_truth_writes"] == 0))

    kill_trail = {"claim_states": {"C03": "SUPPORTED", "C05": "REFUTED", "C07": "UNKNOWN", "C09": "SUPPORTED"}, "revenue_wedge": {"decision": "INVESTIGATE", "existing_spend": "PARTIAL"}, "paid_dissatisfaction": {"count": 1}, "published_evidence_count": 8}
    advance_trail = {"claim_states": {"C03": "SUPPORTED", "C05": "SUPPORTED", "C07": "PARTIAL", "C09": "SUPPORTED"}, "revenue_wedge": {"decision": "TRY_NOW", "existing_spend": "STRONG"}, "paid_dissatisfaction": {"count": 2}, "published_evidence_count": 12}
    park_trail = {"claim_states": {"C03": "SUPPORTED", "C05": "UNKNOWN", "C07": "INSUFFICIENT", "C09": "SUPPORTED"}, "revenue_wedge": {"decision": "NOT_NOW", "existing_spend": "UNKNOWN"}, "paid_dissatisfaction": {"count": 0}, "published_evidence_count": 7}
    continue_trail = {"claim_states": {"C03": "SUPPORTED", "C05": "PARTIAL", "C07": "UNKNOWN", "C09": "SUPPORTED"}, "revenue_wedge": {"decision": "INVESTIGATE", "existing_spend": "PARTIAL"}, "paid_dissatisfaction": {"count": 1}, "published_evidence_count": 5}
    results.append(check("Published hard refutation triggers KILL", trust.evaluate_kill_advance_park(kill_trail)["current_disposition"] == "KILL"))
    results.append(check("Published strong wedge triggers ADVANCE", trust.evaluate_kill_advance_park(advance_trail)["current_disposition"] == "ADVANCE"))
    results.append(check("researched but moneyless direction can PARK", trust.evaluate_kill_advance_park(park_trail)["current_disposition"] == "PARK"))
    results.append(check("otherwise Part 3 leaves direction CONTINUE", trust.evaluate_kill_advance_park(continue_trail)["current_disposition"] == "CONTINUE"))
    results.append(check("fresh search cannot trigger disposition", trust.evaluate_kill_advance_park(continue_trail)["fresh_search_can_trigger_disposition"] is False))

    original_probe = trust.run_fresh_fast_probe
    original_published = trust._published_trail
    async def fake_published(*, thesis_id: str | None, title: str, description: str) -> dict[str, Any]:
        return continue_trail
    def fake_probe(query: str, description: str = "") -> dict[str, Any]:
        return {"status": "PASS", "sources": [{"source": "FIXTURE", "status": "SUCCESS", "count": 1, "transport": {}}], "traces": [counter_trace]}
    try:
        trust.run_fresh_fast_probe = fake_probe
        trust._published_trail = fake_published
        end_to_end = asyncio.run(trust.falsify_direction(title="AI agent forgets rules", description="persistent rules"))
    finally:
        trust.run_fresh_fast_probe = original_probe
        trust._published_trail = original_published
    results.append(check("Try-to-Kill end-to-end performs zero AI calls", end_to_end["ai_api_calls"] == 0))
    results.append(check("Try-to-Kill end-to-end performs zero Market Truth writes", end_to_end["market_truth_writes"] == 0))
    results.append(check("Try-to-Kill end-to-end returns counter search + disposition", end_to_end["fresh_counterevidence_search"]["candidate_count"] >= 1 and end_to_end["published_disposition"]["current_disposition"] == "CONTINUE"))

    route = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
    source = (ROOT / "processors/signalforge_trust_falsification.py").read_text(encoding="utf-8")
    ui = (ROOT / "dashboard/src/pages/MoneyTrail.tsx").read_text(encoding="utf-8")
    client = (ROOT / "dashboard/src/api/client.ts").read_text(encoding="utf-8")
    hooks = (ROOT / "dashboard/src/api/hooks.ts").read_text(encoding="utf-8")

    results.append(check("Part 3 API exposes falsify and evidence replay", "/trust/falsify" in route and "/trust/evidence-replay/{thesis_id}" in route))
    results.append(check("Part 3 processor has no LLM dependency", "openai" not in source.lower() and "anthropic" not in source.lower()))
    results.append(check("Part 3 processor has no market-truth write call", "session.add" not in source and ".commit(" not in source and "publish" not in source.lower().replace("published", "")))
    results.append(check("UI makes Try-to-Kill first-class", "Try to Kill It" in ui and "先找它為什麼不值得做" in ui))
    results.append(check("UI labels fresh counterevidence UNVALIDATED", "UNVALIDATED counterevidence candidate" in ui and "Fresh traces 不能觸發 KILL / ADVANCE / PARK" in ui))
    results.append(check("UI exposes search coverage failure visibility", "Search coverage / failure visibility" in ui and "No counterevidence found in successful searches ≠ no counterevidence exists." in ui))
    results.append(check("UI exposes Evidence Replay", "Evidence Replay · Why do you believe this?" in ui and "Validated links" in ui and "independent" in ui))
    results.append(check("UI exposes explicit ADVANCE/KILL/PARK conditions", '(["ADVANCE", "KILL", "PARK"] as const)' in ui and "IF" in ui))
    results.append(check("client/hooks expose Trust workflow", "falsifySignalForge" in client and "signalforgeEvidenceReplay" in client and "useFalsifySignalForge" in hooks and "useSignalForgeEvidenceReplay" in hooks))

    failed_rows = [x for x in results if not x[1]]
    print("=" * 104)
    print("SIGNALFORGE PART 3 — TRUST / FALSIFICATION — REAL FOUNDER TASK ACCEPTANCE")
    print("=" * 104)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}" + (f" — {detail}" if detail else ""))
    print("-" * 104)
    print(f"RESULT: {len(results)-len(failed_rows)}/{len(results)} PASS")
    if failed_rows:
        print("FINAL_STATUS: SIGNALFORGE_TRUST_FALSIFICATION_PART3_ACCEPTANCE_FAIL")
        return 1
    print("FINAL_STATUS: SIGNALFORGE_TRUST_FALSIFICATION_PART3_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
