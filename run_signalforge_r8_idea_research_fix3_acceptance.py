from __future__ import annotations

import inspect
from typing import Any, Mapping

from processors import signalforge_founder_idea_loop as sf

checks: list[tuple[str, bool, str]] = []

def ck(name: str, ok: bool, detail: object = "") -> None:
    checks.append((name, bool(ok), str(detail)))
    print(("GREEN" if ok else "RED  "), name, detail)

IDEA = "AI coding agents completion verification"

def relevant_fresh(traces: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "founder_query": IDEA,
        "relevance_query": IDEA,
        "language_coverage": "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
        "sources": [{"source": "FIXTURE", "status": "SUCCESS", "count": len(traces)}],
        "traces": traces,
    }

show_hn = {
    "source": "HACKER_NEWS_ALGOLIA",
    "kind": "DISCUSSION",
    "content_unit": "POST",
    "title": "Show HN: AgentTeams – Traceable AI coding workflows",
    "excerpt": "AI coding agents ship code quickly. We built AgentTeams with completion reports and verification summaries so teams can verify implementation work.",
    "url": "https://news.ycombinator.com/item?id=47217890",
    "author": "maker",
    "signals": {"pain": [], "workaround": [], "paid": [], "dissatisfaction": []},
    "metadata": {"story_id": "47217890", "content_unit": "POST"},
}
show_hn_comment = {
    "source": "HACKER_NEWS_ALGOLIA",
    "kind": "DISCUSSION",
    "content_unit": "COMMENT",
    "title": "Show HN: AgentTeams – Traceable AI coding workflows",
    "excerpt": "We use coding agents every day and I still have to manually verify whether they actually completed the requested implementation.",
    "url": "https://news.ycombinator.com/item?id=47218000",
    "author": "buyer",
    "signals": {"pain": ["manually"], "workaround": ["manually"], "paid": [], "dissatisfaction": ["still"]},
    "metadata": {"story_id": "47217890", "comment_id": "47218000", "content_unit": "COMMENT"},
}
repo = {
    "source": "GITHUB_SEARCH",
    "kind": "SOLUTION",
    "title": "groundtruth",
    "excerpt": "A verification layer for AI coding agents that fact-checks claimed completion against test runs and diff analysis.",
    "url": "https://github.com/acme/groundtruth",
    "author": "acme",
    "signals": {"pain": [], "workaround": [], "paid": [], "dissatisfaction": []},
    "metadata": {"stars": 12},
}
product = {
    "source": "BRAVE_WEB",
    "kind": "WEB_PAGE",
    "title": "VerifyAgent",
    "excerpt": "VerifyAgent is a platform for AI coding agent completion verification. Features, integrations, pricing plans and book a demo.",
    "url": "https://verifyagent.example.com",
    "author": None,
    "signals": {"pain": [], "workaround": [], "paid": [], "dissatisfaction": []},
    "metadata": {},
}

summary = sf.summarize_idea_research_probe(relevant_fresh([show_hn, show_hn_comment, repo, product]))
ck("Show HN root pitch is not a human comment", all(x.get("url") != show_hn["url"] for x in summary.get("founder_primary_conversations") or []), summary.get("trace_relevance"))
ck("Show HN root pitch is retained as a solution", any(x.get("url") == show_hn["url"] for x in summary.get("founder_solution_traces") or []), summary.get("founder_solution_traces"))
ck("HN child comment can still be human conversation", any(x.get("url") == show_hn_comment["url"] for x in summary.get("founder_primary_conversations") or []), summary.get("founder_primary_conversations"))
ck("GitHub repo is separated from product/service lane", any(x.get("url") == repo["url"] for x in summary.get("founder_repo_solution_traces") or []) and all(x.get("url") != repo["url"] for x in summary.get("founder_solution_traces") or []), {"products": summary.get("founder_solution_traces"), "repos": summary.get("founder_repo_solution_traces")})
ck("real product page remains product/service", any(x.get("url") == product["url"] for x in summary.get("founder_solution_traces") or []), summary.get("founder_solution_traces"))

brief = sf.build_founder_research_brief(title=IDEA, description="", fresh=relevant_fresh([show_hn, show_hn_comment, repo, product]), fresh_summary=summary)
counts = brief.get("summary") if isinstance(brief.get("summary"), Mapping) else {}
ck("brief reports human/product/repo counts separately", int(counts.get("human_comment_count") or 0) == 1 and int(counts.get("product_or_service_count") or 0) == 2 and int(counts.get("repo_solution_count") or 0) == 1, counts)
ck("compatibility similar_product_count remains total solutions", int(counts.get("similar_product_count") or 0) == 3, counts)
ck("brief exposes repo_solutions separately", len(brief.get("repo_solutions") or []) == 1 and len(brief.get("similar_products") or []) == 2, {"products": brief.get("similar_products"), "repos": brief.get("repo_solutions")})


# HN child extraction must retain root topic context so short replies survive relevance.
walked: list[dict[str, Any]] = []
sf._walk_hn_children(
    {"title": "Show HN: AgentTeams – Traceable AI coding workflows", "children": [
        {"id": 9, "text": "Same here, we still verify manually.", "author": "buyer", "children": []}
    ]},
    story_id="7", out=walked, remaining=[5], story_title="Show HN: AgentTeams – Traceable AI coding workflows"
)
ck("HN child comments retain parent topic context", len(walked) == 1 and str(walked[0].get("title") or "").startswith("Comment on Show HN:") and (walked[0].get("metadata") or {}).get("parent_story_title"), walked)

runner_src = inspect.getsource(__import__("run_signalforge_idea_research"))
ck("CLI prints product and repo sections separately", "產品 / 服務 / 作者提出的方案" in runner_src and "Repo / 開源方案" in runner_src, "runner split present")
ck("CLI count line exposes products and repos separately", "product_or_service_count" in runner_src and "repo_solution_count" in runner_src, "count split present")

print("-" * 96)
passed = sum(1 for _, ok, _ in checks if ok)
print(f"IDEA_RESEARCH_FIX3_ACCEPTANCE: {passed}/{len(checks)} GREEN")
if passed != len(checks):
    raise SystemExit(1)
