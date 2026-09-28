from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import processors.signalforge_founder_idea_loop as sf

CASES = {
    "學生背了英文單字但作文跟翻譯還是寫不出來": {
        "retrieval_query": "students English vocabulary writing translation cannot use words",
        "relevance_query": "Students memorize English vocabulary but still cannot use the words in writing or translation.",
        "must": ("vocabulary", "writing", "translation"),
    },
    "餐廳老闆每天手動整理不同外送平台訂單很麻煩": {
        "retrieval_query": "restaurant owners manual multi-platform delivery order consolidation",
        "relevance_query": "Restaurant owners manually consolidate orders from multiple food delivery platforms every day.",
        "must": ("restaurant", "delivery", "orders"),
    },
    "小型製造工廠機台停機後很難快速找出原因": {
        "retrieval_query": "small factory machine downtime root cause troubleshooting",
        "relevance_query": "Small factories struggle to quickly identify the root cause after machines go down.",
        "must": ("factory", "machine", "downtime"),
    },
}

checks: list[tuple[bool, str, Any]] = []
def ck(ok: bool, name: str, detail: Any = "") -> None:
    checks.append((bool(ok), name, detail))
    print(("GREEN" if ok else "FAIL"), name, detail)

# Existing mixed-language idea should remain zero-cost deterministic.
mixed = "AI coding agents 完成工作後，使用者很難快速確認它到底有沒有真的做對、做完"
orig = sf._bridged_founder_query(mixed)
ck(sf._bridge_is_searchable(orig), "existing mixed Chinese/English bridge remains locally searchable", orig)

# Inject the real llm_client contract shape without requiring a live API in package acceptance.
fake_module = types.ModuleType("processors.llm_client")
async def fake_call_llm(prompt: str, **kwargs):
    idea = prompt.split("Founder idea:\n", 1)[1].split("\n\n", 1)[0].strip()
    if idea not in CASES:
        raise AssertionError(f"unexpected idea: {idea}")
    row = CASES[idea]
    return {"retrieval_query": row["retrieval_query"], "relevance_query": row["relevance_query"]}
fake_module.call_llm = fake_call_llm
old_module = sys.modules.get("processors.llm_client")
sys.modules["processors.llm_client"] = fake_module
try:
    for idea, expected in CASES.items():
        deterministic = sf._bridged_founder_query(idea)
        ck(not sf._bridge_is_searchable(deterministic), f"pure Chinese case does not pretend weak local bridge is enough: {idea}", deterministic)
        bridge = asyncio.run(sf._prepare_query_bridge(idea))
        ck(bridge.get("status") == "LLM_FALLBACK", f"pure Chinese case uses bounded mini bridge: {idea}", bridge)
        ck(int(bridge.get("api_calls") or 0) == 1, f"pure Chinese case spends at most one bridge call: {idea}", bridge.get("api_calls"))
        retrieval = str(bridge.get("retrieval_query") or "").lower()
        relevance = str(bridge.get("relevance_query") or "").lower()
        ck(sf._bridge_is_searchable(retrieval), f"pure Chinese case produces searchable English query: {idea}", retrieval)
        ck(all(term in (retrieval + " " + relevance) for term in expected["must"]), f"pure Chinese case preserves core job: {idea}", {"retrieval": retrieval, "relevance": relevance})
finally:
    if old_module is None:
        sys.modules.pop("processors.llm_client", None)
    else:
        sys.modules["processors.llm_client"] = old_module

# Canonical async path must actually pass translated search + relevance semantics into retrieval.
idea = "餐廳老闆每天手動整理不同外送平台訂單很麻煩"
bridge_row = CASES[idea]
captured: dict[str, Any] = {}
orig_prepare = sf._prepare_query_bridge
orig_probe = sf.run_founder_observation_probe
orig_record = sf.record_founder_hypothesis_probe

async def fake_prepare(raw: str):
    return {
        "status": "LLM_FALLBACK",
        "retrieval_query": bridge_row["retrieval_query"],
        "relevance_query": bridge_row["relevance_query"],
        "api_calls": 1,
        "error": None,
    }

def fake_probe(title: str, description: str = "", **kwargs):
    captured.update(kwargs)
    return {
        "status": "PASS",
        "founder_query": title,
        "relevance_query": kwargs.get("relevance_query_override"),
        "search_query_used": kwargs.get("search_query_override"),
        "queries": [title, kwargs.get("search_query_override")],
        "source_profile_queries_used": [title, kwargs.get("search_query_override")],
        "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
        "sources": [{"source": "BRAVE_WEB", "status": "SUCCESS", "count": 1, "traces": []}],
        "traces": [{
            "source": "BRAVE_WEB", "kind": "WEB_PAGE", "title": "Restaurant order management platform",
            "excerpt": "Software that consolidates food delivery orders from multiple platforms into one workflow.",
            "url": "https://example.com/order-platform",
        }],
        "elapsed_ms": 2,
    }

def fake_record(**kwargs):
    return {"status": "RECORDED", "market_truth_writes": 0}

sf._prepare_query_bridge = fake_prepare
sf.run_founder_observation_probe = fake_probe
sf.record_founder_hypothesis_probe = fake_record
try:
    result = asyncio.run(sf.probe_founder_idea(title=idea))
finally:
    sf._prepare_query_bridge = orig_prepare
    sf.run_founder_observation_probe = orig_probe
    sf.record_founder_hypothesis_probe = orig_record

ck(captured.get("search_query_override") == bridge_row["retrieval_query"], "canonical path sends LLM retrieval query into real retrieval", captured)
ck(captured.get("relevance_query_override") == bridge_row["relevance_query"], "canonical path keeps richer relevance semantics separate", captured)
ck(captured.get("semantic_hypothesis_override") == bridge_row["relevance_query"], "source routing receives translated semantic hypothesis", captured)
ck((result.get("query_bridge") or {}).get("status") == "LLM_FALLBACK", "canonical output exposes query bridge provenance", result.get("query_bridge"))
ck(int(result.get("ai_api_calls") or 0) == 1, "canonical API count includes query bridge call", result.get("ai_api_calls"))
ck((result.get("research_brief") or {}).get("search", {}).get("query_bridge", {}).get("status") == "LLM_FALLBACK", "Founder brief search diagnostics expose query bridge", (result.get("research_brief") or {}).get("search"))

# If the model/key is unavailable, do not pretend a one-word Chinese bridge is adequate.
failing_module = types.ModuleType("processors.llm_client")
async def failing_call_llm(*args, **kwargs):
    raise RuntimeError("no key")
failing_module.call_llm = failing_call_llm
old_module = sys.modules.get("processors.llm_client")
sys.modules["processors.llm_client"] = failing_module
try:
    limited = asyncio.run(sf._prepare_query_bridge("餐廳老闆每天手動整理不同外送平台訂單很麻煩"))
finally:
    if old_module is None:
        sys.modules.pop("processors.llm_client", None)
    else:
        sys.modules["processors.llm_client"] = old_module
ck(limited.get("status") == "LIMITED_FALLBACK", "missing LLM bridge fails visibly instead of pretending translation succeeded", limited)
ck(not sf._bridge_is_searchable(str(limited.get("retrieval_query") or "")), "limited fallback remains marked unsearchable", limited.get("retrieval_query"))

print("-" * 100)
passed = sum(1 for ok, _, _ in checks if ok)
print(f"IDEA_RESEARCH_CHINESE_BRIDGE_FIX5_ACCEPTANCE: {passed}/{len(checks)} GREEN")
raise SystemExit(0 if passed == len(checks) else 1)
