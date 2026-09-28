from __future__ import annotations

import inspect
from typing import Any, Mapping

from processors import signalforge_founder_idea_loop as sf
from processors.signalforge_founder_query_contracts import compile_source_query

checks: list[tuple[str, bool, str]] = []

def ck(name: str, ok: bool, detail: object = "") -> None:
    checks.append((name, bool(ok), str(detail)))
    print(("GREEN" if ok else "RED  "), name, detail)

IDEA = "AI coding agents 完成工作後，使用者很難快速確認它到底有沒有真的做對、做完"
EXPECTED = "AI coding agents completion verification"

expanded = sf.expand_founder_query(IDEA)
bridged = sf._bridged_founder_query(IDEA)
ck("mixed Chinese idea gets a specific English bridge", bridged == EXPECTED, bridged)
ck("generic developer workflow cannot be the first English bridge", len(expanded) >= 2 and expanded[1] == EXPECTED, expanded)
ck("HN transport query keeps the actual job", compile_source_query(bridged, "HACKER_NEWS_ALGOLIA").get("final_query") == "ai coding agents completion verification", compile_source_query(bridged, "HACKER_NEWS_ALGOLIA").get("final_query"))

# Base developer sources must receive the specific bridged query, never the old generic profile query.
original_searchers = sf._SEARCHERS
seen: list[str] = []
def fake_searcher(query: str) -> dict[str, Any]:
    seen.append(query)
    return {"source": "FAKE", "status": "SUCCESS", "count": 0, "traces": []}
fake_searcher.__name__ = "_search_fake"
try:
    sf._SEARCHERS = (fake_searcher,)
    base = sf.run_fresh_fast_probe(IDEA)
finally:
    sf._SEARCHERS = original_searchers
ck("base search uses specific bridged query", base.get("search_query_used") == EXPECTED and seen == [EXPECTED], {"used": base.get("search_query_used"), "seen": seen})
ck("relevance query is preserved separately from retrieval wording", base.get("founder_query") == IDEA and base.get("search_query_used") == EXPECTED and "review" in str(base.get("relevance_query") or "").lower() and "requirements" in str(base.get("relevance_query") or "").lower(), {"raw": base.get("founder_query"), "search": base.get("search_query_used"), "relevance": base.get("relevance_query")})
ck("mixed query no longer reports English bridge as limited", base.get("language_coverage") == "SUPPORTED_BY_CURRENT_QUERY_BRIDGE", base.get("language_coverage"))

# Expansion gets raw + bridged + competitor lenses. No generic profile query in the bounded three.
original_fast = sf.run_fresh_fast_probe
original_expansion = sf.run_source_expansion_queries
original_merge = sf.merge_expansion_into_fresh
captured: dict[str, Any] = {}
try:
    sf.run_fresh_fast_probe = lambda *a, **k: dict(base)
    def fake_exp(hypothesis: str, queries: list[str], **kwargs: Any) -> dict[str, Any]:
        captured["hypothesis"] = hypothesis
        captured["queries"] = list(queries)
        captured["max_queries"] = kwargs.get("max_queries")
        return {"status": "PASS", "sources": [], "traces": [], "elapsed_ms": 0}
    sf.run_source_expansion_queries = fake_exp
    sf.merge_expansion_into_fresh = lambda b, e: dict(b)
    sf.run_founder_observation_probe(IDEA)
finally:
    sf.run_fresh_fast_probe = original_fast
    sf.run_source_expansion_queries = original_expansion
    sf.merge_expansion_into_fresh = original_merge
queries = captured.get("queries") or []
ck("expansion keeps raw and bridged lenses", queries[:2] == [IDEA, EXPECTED], queries)
ck("competitor lens is idea-specific", len(queries) == 3 and queries[2] == EXPECTED + " alternative competitor tool product", queries)
ck("generic developer workflow is absent from executed expansion lenses", all(q != "developer workflow" for q in queries), queries)

# Relevance must use the bridged semantic job, otherwise retrieval can succeed and then be thrown away.
trace = {
    "source": "HACKER_NEWS_ALGOLIA",
    "kind": "DISCUSSION",
    "title": "Show HN: AgentTeams – Traceable AI coding workflows",
    "excerpt": "AI coding agents ship code quickly. Completion reports include a verification summary so teams can check whether implementation work is actually complete.",
    "url": "https://news.ycombinator.com/item?id=1",
    "author": "founder",
    "signals": {"pain": ["manual"], "workaround": [], "paid": [], "dissatisfaction": []},
    "metadata": {},
}
fresh = {
    "status": "PASS",
    "founder_query": IDEA,
    "relevance_query": EXPECTED,
    "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
    "sources": [{"source": "HACKER_NEWS_ALGOLIA", "status": "SUCCESS", "count": 1}],
    "traces": [trace],
}
summary = sf.summarize_idea_research_probe(fresh)
ck("bridged semantic job survives relevance filtering", int(summary.get("relevant_trace_count") or 0) == 1, summary.get("trace_relevance"))

runner_src = inspect.getsource(__import__("run_signalforge_idea_research"))
ck("empty/partial runner exposes retrieval diagnostics", "## 搜尋診斷" in runner_src and "failed:" in runner_src, "diagnostic output present")

print("-" * 96)
passed = sum(1 for _, ok, _ in checks if ok)
print(f"IDEA_RESEARCH_FIX2_ACCEPTANCE: {passed}/{len(checks)} GREEN")
if passed != len(checks):
    raise SystemExit(1)
