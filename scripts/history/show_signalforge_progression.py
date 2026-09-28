from __future__ import annotations

import argparse
import asyncio

from processors.opportunity_decision import run_opportunity_decision
from processors.research_portfolio import build_research_portfolio
from processors.quality_guard import audit_quality


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show quality-locked SignalForge case progression."
    )
    parser.add_argument("--limit", type=int, default=15)
    args = parser.parse_args()

    result = await run_opportunity_decision(limit=50)
    rows = result.get("rows", [])
    portfolio = build_research_portfolio(rows)
    quality = await audit_quality(decision=result)

    print("=" * 118)
    print("SIGNALFORGE QUALITY-LOCKED CASE PROGRESSION")
    print("=" * 118)
    print(
        f"Quality={quality.get('status')} "
        f"critical={quality.get('critical_count', 0)} "
        f"warnings={quality.get('warning_count', 0)}"
    )
    print(
        "Research groups: "
        + " | ".join(
            f"{row['group']} voi={row['voi']} cases={row['case_count']}"
            for row in portfolio.get("ranked_groups", [])
        )
    )
    print(
        f"Deduplicated query jobs={len(portfolio.get('query_jobs', []))}"
    )

    for row in rows[: max(1, args.limit)]:
        prog = row.get("progression") or {}
        contract = prog.get("promotion_contract") or {}
        packets = prog.get("query_packets") or []

        print("-" * 118)
        print(
            f"case {row.get('case_id')} [{row.get('decision_verdict')}] "
            f"gate={row.get('current_gate')} | "
            f"boundary={prog.get('boundary')}"
        )
        print(row.get("title") or "")
        print(
            "Missing VALIDATE prerequisites:",
            ",".join(
                contract.get("missing_validate_prerequisites") or []
            ) or "none",
        )
        print("Stop condition:", prog.get("stop_condition"))
        for packet in packets[:3]:
            print(
                f"  [{packet.get('source_group')}] "
                f"{packet.get('purpose')}: {packet.get('query')}"
            )

    print("=" * 118)


if __name__ == "__main__":
    asyncio.run(main())
