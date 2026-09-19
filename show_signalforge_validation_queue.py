from __future__ import annotations

import argparse
import asyncio

from processors.opportunity_decision import run_opportunity_decision
from processors.validation_registry import validation_registry_report


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show SignalForge machine-research / market-validation boundary."
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    result = await run_opportunity_decision(
        limit=max(5, min(args.limit, 50))
    )

    rows = result.get("rows", [])
    validate = [
        row for row in rows
        if row.get("decision_verdict") == "VALIDATE"
    ]
    prebuilt = [
        row for row in rows
        if row.get("market_validation_boundary")
        == "PREBUILT_WAITING_FOR_VALIDATE"
    ]
    blocked = [
        row for row in rows
        if row.get("market_validation_boundary")
        == "MACHINE_RESEARCH_FIRST"
    ]
    registry = validation_registry_report()

    print("=" * 116)
    print("SIGNALFORGE VALIDATION QUEUE V2")
    print("=" * 116)
    print(
        f"VALIDATE now={len(validate)} | "
        f"prebuilt waiting={len(prebuilt)} | "
        f"machine first={len(blocked)} | "
        f"experiments pending={registry['pending']} completed={registry['completed']}"
    )

    if validate:
        print("\nREADY FOR REAL MARKET ACTION")
        for row in validate[:10]:
            print(
                f"  case {row['case_id']} | {row['title']} | "
                f"action={row.get('founder_action')}"
            )
            plans = row.get("prepared_validation_plans", {}) or {}
            for code, plan in plans.items():
                print(
                    f"    {code} {plan.get('experiment')} | "
                    f"PASS={plan.get('pass_signal')}"
                )
                if code in {"C10", "C11", "C14"}:
                    print(
                        "      PRE-REGISTER: "
                        "python create_signalforge_validation_experiment.py "
                        f"--case {row['case_id']} --claim {code}"
                    )
    else:
        print("\nREADY FOR REAL MARKET ACTION: none")

    if prebuilt:
        print("\nPREBUILT BUT NOT YET AUTHORIZED")
        for row in prebuilt[:10]:
            print(
                f"  case {row['case_id']} | {row['title']} | "
                f"gate={row.get('current_gate')} | "
                f"prepared={','.join(row.get('prepared_validation_claims', []) or [])}"
            )

    print("\nMACHINE MUST CONTINUE FIRST")
    for row in blocked[:12]:
        floor = row.get("floor60_reality") or {}
        needs = ",".join(floor.get("source_needs", []) or []) or "none"
        print(
            f"  case {row['case_id']} | {row['title']} | "
            f"gate={row.get('current_gate')} | sources={needs} | "
            f"machine={row.get('machine_action')}"
        )

    print("\nMarket-result rule:")
    print(
        "  Pre-register before a real test. Record the result with the same "
        "--experiment-id so calibration has a clean pre-test snapshot."
    )
    print("=" * 116)


if __name__ == "__main__":
    asyncio.run(main())
