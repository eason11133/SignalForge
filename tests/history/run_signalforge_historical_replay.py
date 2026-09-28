from __future__ import annotations

import argparse
import asyncio

from processors.historical_replay import run_replay_series


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SignalForge evidence-time historical replay."
    )
    parser.add_argument(
        "--days",
        default="90,60,30,0",
        help="Comma-separated days-back cutoffs.",
    )
    args = parser.parse_args()

    days = []
    for part in str(args.days).split(","):
        part = part.strip()
        if part:
            days.append(max(0, int(part)))

    result = await run_replay_series(days_back=days)

    print("=" * 112)
    print("SIGNALFORGE HISTORICAL REPLAY — EVIDENCE/TIME FREEZE")
    print("=" * 112)
    for row in result["series"]:
        leakage = row.get("leakage") or {}
        print(
            f"{row['days_back']:>3}d back | cases={row['cases']} | "
            f"stages={row['stage_counts']} | "
            f"future_evidence_excluded={leakage.get('excluded_future_evidence', 0)} | "
            f"future_interpretations_excluded={leakage.get('future_interpretation_excluded', 0)} | "
            f"unknown_interpretation_time={leakage.get('interpretation_time_unknown', 0)}"
        )
        print("            report:", row.get("report_path"))

    print()
    print("Predictive accuracy:", result["predictive_accuracy"])
    print(
        "Replay infrastructure is active; accuracy stays UNVALIDATED until "
        "historical outcomes / live ground truth are available."
    )
    print("=" * 112)


if __name__ == "__main__":
    asyncio.run(main())
