from __future__ import annotations

from typing import Any

import processors.signalforge_founder_idea_loop as sf
from processors.signalforge_founder_query_contracts import source_fit_for_problem_class

CASES = [
    {
        "idea": "學生背了英文單字但作文跟翻譯還是寫不出來",
        "retrieval": "students English vocabulary writing translation cannot use words",
        "relevance": "Students memorize English vocabulary but still cannot use the words in writing or translation.",
        "profile": "EDUCATION_EXAM",
        "trace": {
            "source": "LEMMY_PUBLIC", "kind": "DISCUSSION", "content_unit": "POST",
            "title": "I know English words but cannot use them in essays",
            "excerpt": "I memorize vocabulary for exams, but when I write or translate I cannot produce the words I studied.",
            "url": "https://example.test/english-output", "author": "student",
            "metadata": {"content_unit": "POST"},
        },
    },
    {
        "idea": "餐廳老闆每天手動整理不同外送平台訂單很麻煩",
        "retrieval": "restaurant owners manual multi-platform delivery order consolidation",
        "relevance": "Restaurant owners manually consolidate orders from multiple food delivery platforms every day.",
        "profile": "SMB_SERVICE_OPERATIONS",
        "trace": {
            "source": "LEMMY_PUBLIC", "kind": "DISCUSSION", "content_unit": "POST",
            "title": "Too many delivery app orders at our restaurant",
            "excerpt": "At our restaurant we manually combine orders from multiple food delivery platforms every day and it is a mess.",
            "url": "https://example.test/restaurant-orders", "author": "restaurant-owner",
            "metadata": {"content_unit": "POST"},
        },
    },
    {
        "idea": "小型製造工廠機台停機後很難快速找出原因",
        "retrieval": "small factory machine downtime root cause troubleshooting",
        "relevance": "Small factories struggle to quickly identify the root cause after machines go down.",
        "profile": "INDUSTRIAL_OPERATIONS",
        "trace": {
            "source": "LEMMY_PUBLIC", "kind": "DISCUSSION", "content_unit": "POST",
            "title": "Machine downtime troubleshooting in a small factory",
            "excerpt": "After a machine stops in our small factory we spend hours checking logs to find the root cause.",
            "url": "https://example.test/factory-downtime", "author": "plant-engineer",
            "metadata": {"content_unit": "POST"},
        },
    },
]

errors: list[str] = []
for case in CASES:
    profile = source_fit_for_problem_class(case["relevance"])
    if profile.get("source_profile") != case["profile"]:
        errors.append(f"{case['idea']}: profile={profile.get('source_profile')}")

    captured: dict[str, Any] = {}
    orig_expansion = sf.run_source_expansion_queries
    def fake_expansion(hypothesis: str, queries: list[str], max_queries: int = 3):
        captured["hypothesis"] = hypothesis
        captured["queries"] = list(queries)
        captured["max_queries"] = max_queries
        trace = dict(case["trace"])
        return {
            "status": "PASS",
            "plan": {"source_profile": case["profile"], "selected_source_ids": ["LEMMY_PUBLIC"]},
            "sources": [{
                "source": "LEMMY_PUBLIC", "source_family": "LEMMY",
                "observation_source_families": ["DOMAIN_FORUMS", "PUBLIC_MARKET_CONVERSATIONS"],
                "status": "SUCCESS", "count": 1, "traces": [trace],
            }],
            "traces": [trace], "elapsed_ms": 1,
        }
    sf.run_source_expansion_queries = fake_expansion
    try:
        fresh = sf.run_founder_observation_probe(
            case["idea"],
            search_query_override=case["retrieval"],
            relevance_query_override=case["relevance"],
            semantic_hypothesis_override=case["relevance"],
        )
    finally:
        sf.run_source_expansion_queries = orig_expansion

    summary = sf.summarize_idea_research_probe(fresh)
    brief = sf.build_founder_research_brief(title=case["idea"], description="", fresh=fresh, fresh_summary=summary)
    comments = brief.get("human_comments") or []
    status = sf._research_status(collection_status=str(fresh.get("status") or ""), research_brief=brief)

    expected_queries = [case["idea"], case["retrieval"], case["retrieval"] + " alternative competitor tool product"]
    if captured.get("hypothesis") != case["relevance"]:
        errors.append(f"{case['idea']}: planner hypothesis drift {captured.get('hypothesis')!r}")
    if captured.get("queries") != expected_queries:
        errors.append(f"{case['idea']}: query lenses {captured.get('queries')!r}")
    if not comments:
        errors.append(f"{case['idea']}: translated relevant human trace did not reach brief")
    if status != "RESEARCH_READY":
        errors.append(f"{case['idea']}: status={status}")

    print("CASE", case["idea"])
    print("  profile=", profile.get("source_profile"))
    print("  queries=", captured.get("queries"))
    print("  counts=", brief.get("summary"))
    print("  status=", status)
    print("  first_comment=", (comments[0] if comments else {}).get("title"))

if errors:
    print("MULTIDOMAIN_E2E_FAILED", errors)
    raise SystemExit(1)
print("MULTIDOMAIN_E2E_REPLAY_OK")
