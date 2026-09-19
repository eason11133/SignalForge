from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _print_cards(title: str, rows: list[Mapping[str, Any]]) -> None:
    print(f"\n## {title}")
    if not rows:
        print("(這次沒有找到)")
        return
    for idx, item in enumerate(rows, 1):
        name = _clean(item.get("title")) or "(untitled)"
        source = _clean(item.get("source")) or "UNKNOWN"
        match = _clean(item.get("match_level")).upper()
        match_label = " [相關]" if match == "RELATED" else ""
        print(f"\n{idx}. {name}  [{source}]{match_label}")
        if item.get("url"):
            print(f"   {item.get('url')}")
        excerpt = _clean(item.get("excerpt"))
        if excerpt:
            print(f"   {excerpt[:900]}")
        if item.get("author"):
            print(f"   author: {item.get('author')}")


async def main() -> int:
    ap = argparse.ArgumentParser(description="SignalForge: give it an idea, get back research material.")
    ap.add_argument("--repo", default=".", help="SignalForge repository path")
    ap.add_argument("--idea", required=True, help="Product/business idea or problem to research")
    ap.add_argument("--description", default="", help="Optional extra context")
    ap.add_argument("--json-out", default="", help="Optional path to save the full JSON result")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from processors.signalforge_founder_idea_loop import probe_founder_idea

    result = await probe_founder_idea(title=args.idea, description=args.description)
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else {}
    summary = brief.get("summary") if isinstance(brief.get("summary"), Mapping) else {}

    print("SignalForge Idea Research")
    print("=" * 72)
    print("Idea:", args.idea)
    print("Status:", result.get("status"))
    print(
        "Results:",
        f"comments={int(summary.get('human_comment_count') or 0)}",
        f"products={int(summary.get('product_or_service_count') or 0)}",
        f"repos={int(summary.get('repo_solution_count') or 0)}",
        f"supporting={int(summary.get('supporting_evidence_count') or 0)}",
        f"counter={int(summary.get('counter_evidence_count') or 0)}",
    )

    _print_cards("真人留言", list(brief.get("human_comments") or []))
    _print_cards("產品 / 服務 / 作者提出的方案", list(brief.get("similar_products") or []))
    _print_cards("Repo / 開源方案", list(brief.get("repo_solutions") or []))
    _print_cards("其他有用資料", list(brief.get("supporting_evidence") or []))
    _print_cards("反面 / 不支持資料", list(brief.get("counter_evidence") or []))

    print("\n## 目前缺口")
    gaps = list(brief.get("gaps") or [])
    if not gaps:
        print("(沒有額外缺口提示)")
    else:
        for gap in gaps:
            print("-", gap)

    # When a scan is empty or partial, show just enough retrieval diagnostics to
    # distinguish a real no-result search from query/source failure.
    useful = int(summary.get("useful_result_count") or 0)
    if useful == 0 or str(result.get("status") or "") in {"RESEARCH_PARTIAL", "SEARCH_FAILED"}:
        search = brief.get("search") if isinstance(brief.get("search"), Mapping) else {}
        print("\n## 搜尋診斷")
        queries = list((search or {}).get("source_profile_queries") or (search or {}).get("queries") or [])
        if queries:
            print("queries:", " | ".join(_clean(x) for x in queries if _clean(x)))
        failed = list((search or {}).get("failed_sources") or [])
        if failed:
            for row in failed[:8]:
                if isinstance(row, Mapping):
                    print("failed:", _clean(row.get("source")), _clean(row.get("status")), _clean(row.get("error")))

    if args.json_out:
        out = Path(args.json_out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nJSON:", out)

    status = str(result.get("status") or "")
    if status == "INVALID_QUERY":
        return 2
    if status == "SEARCH_FAILED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
