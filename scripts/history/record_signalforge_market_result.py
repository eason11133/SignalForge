from __future__ import annotations

import argparse
import asyncio

from processors.market_ground_truth import record_market_result
from processors.opportunity_decision import run_opportunity_decision
from processors.validation_registry import complete_validation_experiment


def _row_for(result: dict, case_id: int) -> dict:
    return next(
        (
            row for row in result.get("rows", [])
            if int(row.get("case_id") or 0) == int(case_id)
        ),
        {},
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Record a pre-registered real SignalForge market validation "
            "outcome and immediately recompute the decision."
        )
    )
    parser.add_argument("--case", type=int, required=True)
    parser.add_argument(
        "--event",
        required=True,
        choices=["acquisition", "price", "switch", "paid-pilot"],
    )
    parser.add_argument(
        "--result",
        required=True,
        choices=["pass", "fail"],
    )
    parser.add_argument("--note", required=True)
    parser.add_argument("--actor", required=False, default=None)
    parser.add_argument("--amount", type=float, default=None)
    parser.add_argument("--currency", default=None)
    parser.add_argument(
        "--experiment-id",
        required=True,
        help=(
            "Required pre-registration id created by "
            "create_signalforge_validation_experiment.py."
        ),
    )
    args = parser.parse_args()

    before_all = await run_opportunity_decision(limit=50)
    before = _row_for(before_all, args.case)

    result = await record_market_result(
        case_id=args.case,
        event=args.event,
        result=args.result,
        note=args.note,
        experiment_id=args.experiment_id,
        actor_label=args.actor,
        amount=args.amount,
        currency=args.currency,
    )

    registered = complete_validation_experiment(
        experiment_id=args.experiment_id,
        result=args.result,
        note=args.note,
        amount=args.amount,
        currency=args.currency,
        actor_label=args.actor,
    )
    if registered is None:
        raise RuntimeError(
            "Market evidence was recorded but registry completion failed."
        )

    after_all = await run_opportunity_decision(limit=50)
    after = _row_for(after_all, args.case)

    print("=" * 108)
    print("SIGNALFORGE PRE-REGISTERED MARKET RESULT → DECISION CLOSURE")
    print("=" * 108)
    print(f"Case:       {result['case_id']} — {result['title']}")
    print(f"Experiment: {result['experiment_id']}")
    print("Registered: YES")
    print(f"Event:      {result['event']}")
    print(f"Result:     {result['result']}")
    print(f"Stance:     {result['stance']}")
    for row in result["updated_claims"]:
        print(
            f"  {row['claim_code']}: state={row['state']} "
            f"support_groups={row['support_groups']} "
            f"refute_groups={row['refute_groups']}"
        )

    print("-" * 108)
    print(
        "Decision before: "
        f"{before.get('decision_verdict', 'UNKNOWN')} | "
        f"gate={before.get('current_gate', 'UNKNOWN')}"
    )
    print(
        "Decision after:  "
        f"{after.get('decision_verdict', 'UNKNOWN')} | "
        f"gate={after.get('current_gate', 'UNKNOWN')}"
    )
    print(
        "Boundary after:  "
        f"{after.get('market_validation_boundary', 'UNKNOWN')}"
    )
    print(result["warning"])
    print("=" * 108)


if __name__ == "__main__":
    asyncio.run(main())
