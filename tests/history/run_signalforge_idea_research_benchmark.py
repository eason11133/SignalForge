from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
BENCHMARK_PATH = HERE / "benchmarks" / "signalforge_benchmark_batch_01.json"
VALID_SETS = {"GOLDEN", "TOURNAMENT_MAIN", "HOLDOUT"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _load_benchmark() -> dict[str, Any]:
    data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    if int((data.get("execution_policy") or {}).get("market_truth_writes") or 0) != 0:
        raise SystemExit("benchmark manifest violates research-only boundary")
    return data


def _case_summary(record: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else {}
    summary = brief.get("summary") if isinstance(brief.get("summary"), Mapping) else {}
    return {
        "record_id": record.get("id"),
        "benchmark_set": record.get("set"),
        "title": record.get("title"),
        "description": record.get("description"),
        "runtime_status": result.get("status"),
        "market_truth_writes": int(result.get("market_truth_writes") or 0),
        "useful_result_count": int(summary.get("useful_result_count") or 0),
        "human_comment_count": int(summary.get("human_comment_count") or 0),
        "similar_product_count": int(summary.get("similar_product_count") or 0),
        "supporting_evidence_count": int(summary.get("supporting_evidence_count") or 0),
        "counter_evidence_count": int(summary.get("counter_evidence_count") or 0),
        "human_comments": list(brief.get("human_comments") or []),
        "similar_products": list(brief.get("similar_products") or []),
        "supporting_evidence": list(brief.get("supporting_evidence") or []),
        "counter_evidence": list(brief.get("counter_evidence") or []),
        "gaps": list(brief.get("gaps") or []),
        "search": dict(brief.get("search") or {}),
    }


def _write_md(path: Path, payload: Mapping[str, Any]) -> None:
    lines = [
        "# SignalForge Idea Research live check",
        "",
        f"- set: `{payload.get('benchmark_set')}`",
        f"- started: {payload.get('started_at')}",
        f"- finished: {payload.get('finished_at')}",
        "",
        "> This check asks whether SignalForge brings back useful research material. It does not score or accept/reject the idea.",
        "",
    ]
    for run in payload.get("runs") or []:
        lines.append(f"## {run.get('record_id')} — {run.get('title')}")
        lines.append("")
        if run.get("error"):
            lines.append(f"**ERROR:** `{run.get('error')}`")
            lines.append("")
            continue
        lines.append(
            f"- status: `{run.get('runtime_status')}` | comments={run.get('human_comment_count')} | "
            f"products={run.get('similar_product_count')} | supporting={run.get('supporting_evidence_count')} | "
            f"counter={run.get('counter_evidence_count')}"
        )
        lines.append("")
        lines.append("### 真人留言")
        lines.append("")
        if not run.get("human_comments"):
            lines.append("_目前沒有夠相關的真人留言。_")
        for item in run.get("human_comments") or []:
            lines.append(f"- **{_clean(item.get('title')) or '(untitled)'}** — `{item.get('source')}`")
            if item.get("url"):
                lines.append(f"  - {item.get('url')}")
            if item.get("excerpt"):
                lines.append(f"  - {_clean(item.get('excerpt'))[:700]}")
        lines.append("")
        lines.append("### 類似產品")
        lines.append("")
        if not run.get("similar_products"):
            lines.append("_目前沒有夠相近的產品。_")
        for item in run.get("similar_products") or []:
            lines.append(f"- **{_clean(item.get('title')) or '(untitled)'}** — `{item.get('source')}` — {item.get('url') or ''}")
        lines.append("")
        lines.append("### 其他有用資料")
        lines.append("")
        if not run.get("supporting_evidence"):
            lines.append("_目前沒有額外旁證。_")
        for item in run.get("supporting_evidence") or []:
            lines.append(f"- **{_clean(item.get('title')) or '(untitled)'}** — `{item.get('source')}` — {item.get('url') or ''}")
        lines.append("")
        lines.append("### 反面／不支持資料")
        lines.append("")
        if not run.get("counter_evidence"):
            lines.append("_目前沒有明確反面資料。_")
        for item in run.get("counter_evidence") or []:
            lines.append(f"- **{_clean(item.get('title')) or '(untitled)'}** — `{item.get('source')}` — {item.get('url') or ''}")
        if run.get("gaps"):
            lines.append("")
            lines.append("### 目前缺口")
            lines.append("")
            for gap in run.get("gaps") or []:
                lines.append(f"- {gap}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run SignalForge Idea Research on a benchmark set.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--set", dest="benchmark_set", required=True, choices=sorted(VALID_SETS))
    ap.add_argument("--ids", default="")
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--unlock-holdout", action="store_true")
    args = ap.parse_args()

    if args.benchmark_set == "HOLDOUT" and not args.unlock_holdout:
        print("REFUSED: HOLDOUT remains sealed until tuning is frozen.")
        return 3

    repo = Path(args.repo).resolve()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from processors.signalforge_founder_idea_loop import probe_founder_idea

    bench = _load_benchmark()
    records = [r for r in (bench.get("records") or []) if isinstance(r, Mapping) and str(r.get("set")) == args.benchmark_set]
    requested = {x.strip().upper() for x in args.ids.split(",") if x.strip()}
    if requested:
        records = [r for r in records if str(r.get("id") or "").upper() in requested]
    if not records:
        print("No records selected.")
        return 4

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"signalforge_idea_research_{args.benchmark_set.lower()}_{stamp}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"

    payload: dict[str, Any] = {
        "benchmark_set": args.benchmark_set,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "market_truth_writes": 0,
        "runs": [],
    }

    failures = 0
    for pos, record in enumerate(records, 1):
        print(f"[{pos}/{len(records)}] {record.get('id')} — {record.get('title')}")
        started = time.perf_counter()
        try:
            result = await probe_founder_idea(title=str(record.get("title") or ""), description=str(record.get("description") or ""))
            run = _case_summary(record, result)
            run["full_result"] = result
            print(
                f"  {run.get('runtime_status')} comments={run.get('human_comment_count')} "
                f"products={run.get('similar_product_count')} supporting={run.get('supporting_evidence_count')}"
            )
        except Exception as exc:
            failures += 1
            run = {
                "record_id": record.get("id"),
                "title": record.get("title"),
                "error": f"{type(exc).__name__}: {exc}",
            }
            print("  ERROR:", run["error"])
        run["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        payload["runs"].append(run)
        payload["finished_at"] = datetime.now().isoformat(timespec="seconds")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_md(md_path, payload)
        if pos < len(records) and args.delay > 0:
            await asyncio.sleep(args.delay)

    print("JSON:", json_path)
    print("MD:  ", md_path)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
