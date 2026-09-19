from __future__ import annotations

import argparse
import asyncio

from processors.validation_registry import create_validation_experiment


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-register a real SignalForge market validation experiment."
    )
    parser.add_argument("--case", type=int, required=True)
    parser.add_argument(
        "--claim",
        required=True,
        choices=["C10", "C11", "C14", "c10", "c11", "c14"],
    )
    parser.add_argument("--note", default=None)
    args = parser.parse_args()

    row = await create_validation_experiment(
        case_id=args.case,
        claim_code=args.claim.upper(),
        note=args.note,
    )

    print("=" * 108)
    print("SIGNALFORGE VALIDATION EXPERIMENT PRE-REGISTERED")
    print("=" * 108)
    print("Experiment:", row["experiment_id"])
    print("Case:      ", row["case_id"], "—", row["title"])
    print("Claim:     ", row["claim_code"])
    print("Event:     ", row["event"])
    print("Pre-test verdict:", row["pretest_snapshot"]["decision_verdict"])
    print("Pre-test gate:   ", row["pretest_snapshot"]["current_gate"])
    print("Plan:")
    plan = row.get("plan") or {}
    if isinstance(plan, dict):
        for key, value in plan.items():
            print(f"  {key}: {value}")
    else:
        print(" ", plan)
    print()
    print("Use this SAME experiment id when recording the result.")
    print("=" * 108)


if __name__ == "__main__":
    asyncio.run(main())
