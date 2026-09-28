from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Mapping

from processors import signalforge_founder_idea_loop as sf

checks: list[tuple[str, bool, str]] = []


def ck(name: str, ok: bool, detail: object = "") -> None:
    checks.append((name, bool(ok), str(detail)))
    print(("GREEN" if ok else "RED  "), name, detail)


TITLE = "AI coding agents finish work but founders cannot efficiently verify whether the work is actually correct and complete"
DESC = "Founders using coding agents need to verify requirements, tests and actual completion without manually reviewing everything."


def signals(*, pain=(), workaround=(), paid=(), dissatisfaction=()):
    return {
        "pain": list(pain),
        "workaround": list(workaround),
        "paid": list(paid),
        "dissatisfaction": list(dissatisfaction),
    }


FRESH: dict[str, Any] = {
    "status": "PASS",
    "founder_query": f"{TITLE} {DESC}",
    "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
    "elapsed_ms": 42,
    "queries": [TITLE],
    "source_profile_queries_used": [TITLE, f"{TITLE} alternative competitor tool product"],
    "sources": [
        {"source": "REDDIT_PUBLIC", "status": "SUCCESS", "count": 2},
        {"source": "BRAVE_WEB", "status": "SUCCESS", "count": 4},
    ],
    "traces": [
        {
            "source": "REDDIT_PUBLIC", "kind": "DISCUSSION",
            "title": "AI coding agent completion verification is unreliable",
            "excerpt": "I use AI coding agents for software changes but I still have to manually verify whether the implementation is actually correct and complete.",
            "url": "https://example.test/comment-1", "author": "founder1",
            "signals": signals(pain=("unreliable",), workaround=("manually",), dissatisfaction=("still have to",)), "metadata": {},
        },
        {
            "source": "REDDIT_PUBLIC", "kind": "DISCUSSION",
            "title": "Built-in checks are already good enough for our coding agents",
            "excerpt": "For our AI coding agent workflow the built-in verification is already good enough, so we would not pay for another completion checker.",
            "url": "https://example.test/comment-2", "author": "founder2",
            "signals": signals(), "metadata": {},
        },
        {
            "source": "BRAVE_WEB", "kind": "SOLUTION",
            "title": "AgentVerify",
            "excerpt": "Verification for AI coding agent software changes, tests and completion.",
            "url": "https://agentverify.example", "author": "vendor",
            "signals": signals(), "metadata": {},
        },
        {
            "source": "BRAVE_WEB", "kind": "ARTICLE",
            "title": "Engineering teams still verify AI coding-agent output",
            "excerpt": "Teams using AI coding agents still review software implementation and tests to confirm the work is correct and complete.",
            "url": "https://example.test/article", "author": "writer",
            "signals": signals(pain=("manual",)), "metadata": {},
        },
        {
            "source": "BRAVE_WEB", "kind": "ARTICLE",
            "title": "Pasta recipes for weeknights",
            "excerpt": "A cooking article about tomato sauce.",
            "url": "https://example.test/pasta", "author": "cook",
            "signals": signals(), "metadata": {},
        },
    ],
}


# Product-shape/static checks.
probe_src = inspect.getsource(sf.probe_founder_idea)
sync_src = inspect.getsource(sf.probe_founder_observation_only)
retrieval_src = inspect.getsource(sf.run_founder_observation_probe)
module_src = inspect.getsource(sf)

ck("canonical product mode is Idea Research", '"mode": "IDEA_RESEARCH"' in probe_src)
ck("canonical path uses lightweight research summary", "summarize_idea_research_probe" in probe_src)
ck("canonical path does not execute legacy heavy summary", "summarize_fresh_probe(" not in probe_src)
ck("canonical path does not calculate source-absence adequacy", "_attach_fresh_source_fit(" not in probe_src)
ck("sync path also uses lightweight research summary", "summarize_idea_research_probe" in sync_src and "summarize_fresh_probe(" not in sync_src)
ck("normal scan has no Money Trail dependency", "signalforge_money_trail" not in module_src)
ck("normal scan has no Decision Frontier builder", "def build_decision_frontier" not in module_src)
ck("normal scan has no PRODUCT_ACCEPTED output", "product_accepted" not in probe_src.lower())
ck("semantic relevance LLM stays opt-in", 'SIGNALFORGE_RELEVANCE_LLM_ENABLED", "false"' in module_src)
ck("research retrieval has bounded competitor lens", "alternative competitor tool product" in retrieval_src and "max_queries=3" in retrieval_src)
ck("Chinese counter cues are supported", all(x in module_src for x in ("已經解決", "夠用了", "不會付費", "沒預算")))
root = Path(__file__).resolve().parent
ck("direct idea runner is installed", (root / "run_signalforge_idea_research.py").exists())
ck("research benchmark runner is installed", (root / "run_signalforge_idea_research_benchmark.py").exists())

# Lightweight summarizer behavior.
summary = sf.summarize_idea_research_probe(FRESH)
brief = sf.build_founder_research_brief(title=TITLE, description=DESC, fresh=FRESH, fresh_summary=summary)
ck("lightweight diagnostic mode", summary.get("diagnostic_mode") == "LIGHTWEIGHT_IDEA_RESEARCH", summary.get("diagnostic_mode"))
ck("relevant human comments returned", len(brief.get("human_comments") or []) >= 1, len(brief.get("human_comments") or []))
ck("similar product returned", any(x.get("title") == "AgentVerify" for x in (brief.get("similar_products") or [])))
ck("supporting material returned", len(brief.get("supporting_evidence") or []) >= 1, len(brief.get("supporting_evidence") or []))
ck("counter evidence returned", any("good enough" in str(x.get("title") or "").lower() for x in (brief.get("counter_evidence") or [])))
ck("obvious unrelated trace excluded from useful sections", not any("Pasta" in str(x.get("title") or "") for lane in ("human_comments", "similar_products", "supporting_evidence") for x in (brief.get(lane) or [])))
ck("market truth remains read-only", int(summary.get("market_truth_writes") or 0) == 0)

# Product-page heuristic: catch real product pages without making editorial pages products.
product_page = {
    "kind": "WEB_PAGE", "title": "VerifyFlow — AI agent verification platform",
    "excerpt": "Features, integrations and pricing plans. Get started with a free trial.",
    "signals": signals(),
}
editorial_page = {
    "kind": "WEB_PAGE", "title": "Best tools for AI agent verification",
    "excerpt": "A guide comparing software products and platforms.",
    "signals": signals(),
}
ck("product page can be recognized without visible buyer-spend evidence", sf._looks_like_existing_solution(product_page))
ck("editorial tool roundup is not promoted to product", not sf._looks_like_existing_solution(editorial_page))
unrelated_counter = {
    "kind": "ARTICLE", "title": "Pasta recipe is good enough", "excerpt": "No need for extra sauce.",
    "thesis_relevance": {"grade": "R3", "countable": False},
}
ck("unrelated R3 cue cannot become counter evidence", not sf._looks_like_counter_evidence(unrelated_counter))
partial_status = sf._research_status(
    collection_status="PARTIAL",
    research_brief={
        "summary": {"useful_result_count": 0},
        "search": {"successful_sources": ["A"], "failed_sources": [{"source": "B"}]},
    },
)
ck("partial source coverage is not reported as clean no-results", partial_status == "RESEARCH_PARTIAL", partial_status)

# Canonical runtime must not fall back into legacy summary/source-fit machinery.
original_run = sf.run_founder_observation_probe
original_adj = sf.adjudicate_fresh_relevance
original_legacy_summary = sf.summarize_fresh_probe
original_attach = sf._attach_fresh_source_fit
original_record = sf.record_founder_hypothesis_probe

async def fake_adj(fresh: Mapping[str, Any]):
    return dict(fresh), {"enabled": False, "api_calls": 0, "status": "DISABLED"}

def poison(*args, **kwargs):
    raise AssertionError("legacy heavy product-judgment path was executed")

try:
    sf.run_founder_observation_probe = lambda *args, **kwargs: dict(FRESH)
    sf.adjudicate_fresh_relevance = fake_adj
    sf.summarize_fresh_probe = poison
    sf._attach_fresh_source_fit = poison
    sf.record_founder_hypothesis_probe = lambda **kwargs: {"status": "RECORDED_FOR_TEST", "market_truth_writes": 0}

    result = asyncio.run(sf.probe_founder_idea(title=TITLE, description=DESC))
    ck("canonical async probe completes with legacy path poisoned", result.get("status") in {"RESEARCH_READY", "RESEARCH_PARTIAL"}, result.get("status"))
    ck("canonical async probe returns research_brief", isinstance(result.get("research_brief"), Mapping))
    ck("canonical async probe makes no relevance LLM call by default fixture", int(result.get("ai_api_calls") or 0) == 0)
    ck("canonical async probe writes no market truth", int(result.get("market_truth_writes") or 0) == 0)

    sync_result = sf.probe_founder_observation_only(title=TITLE, description=DESC)
    ck("sync probe completes with legacy path poisoned", sync_result.get("status") in {"RESEARCH_READY", "RESEARCH_PARTIAL"}, sync_result.get("status"))
finally:
    sf.run_founder_observation_probe = original_run
    sf.adjudicate_fresh_relevance = original_adj
    sf.summarize_fresh_probe = original_legacy_summary
    sf._attach_fresh_source_fit = original_attach
    sf.record_founder_hypothesis_probe = original_record

# Retrieval fan-out contract without hitting the network.
original_fast = sf.run_fresh_fast_probe
original_profile_queries = sf.source_profile_queries
original_expansion_queries = sf.run_source_expansion_queries
original_merge = sf.merge_expansion_into_fresh
captured: dict[str, Any] = {}
try:
    sf.run_fresh_fast_probe = lambda *args, **kwargs: {
        "status": "PASS", "founder_query": TITLE, "search_query_used": "ai coding agent verification",
        "sources": [], "traces": [], "queries": [TITLE],
    }
    sf.source_profile_queries = lambda *args, **kwargs: ["ai coding agent completion verification"]
    def fake_expansion(hypothesis_text, queries, **kwargs):
        captured["queries"] = list(queries)
        captured["max_queries"] = kwargs.get("max_queries")
        return {"status": "PASS", "sources": [], "traces": [], "elapsed_ms": 0}
    sf.run_source_expansion_queries = fake_expansion
    sf.merge_expansion_into_fresh = lambda base, expansion: dict(base)
    sf.run_founder_observation_probe(TITLE, DESC)
    ck("retrieval stays bounded to three query lenses", captured.get("max_queries") == 3 and len(captured.get("queries") or []) <= 3, captured)
    ck("one retrieval lens explicitly searches alternatives/products", any("alternative competitor tool product" in q for q in (captured.get("queries") or [])), captured.get("queries"))
finally:
    sf.run_fresh_fast_probe = original_fast
    sf.source_profile_queries = original_profile_queries
    sf.run_source_expansion_queries = original_expansion_queries
    sf.merge_expansion_into_fresh = original_merge

print("-" * 96)
passed = sum(1 for _, ok, _ in checks if ok)
print(f"IDEA_RESEARCH_FINAL_ACCEPTANCE: {passed}/{len(checks)} GREEN")
if passed != len(checks):
    raise SystemExit(1)
