from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta

from processors.opportunity_decision import run_opportunity_decision
from processors.research_portfolio import build_research_portfolio
from processors.founder_daily_surface import (
    build_founder_daily_surface,
)
from processors.historical_replay import (
    run_historical_replay,
)
from processors.calibration import calibration_report

TARGET_CODES = ("C08", "C10", "C11", "C12", "C13", "C14")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def main() -> None:
    print("=" * 120)
    print("SIGNALFORGE FLOOR-60 INTEGRATED ACCEPTANCE")
    print("=" * 120)
    print("No crawler. No LLM. No threshold weakening.")
    print()

    decision = await run_opportunity_decision(limit=50)
    rows = decision.get("rows", [])
    _require(bool(rows), "no decision rows")

    floor = decision.get("floor60") or {}
    _require(
        int(floor.get("cases", 0) or 0) == len(rows),
        "Floor60 engine did not cover every decision case",
    )

    packet_cases = 0
    packet_count = 0
    missing_packets = []
    for row in rows:
        packets = (
            (row.get("floor60_reality") or {}).get("packets") or {}
        )
        if packets:
            packet_cases += 1
        for code in TARGET_CODES:
            packet = packets.get(code)
            if not packet:
                missing_packets.append(
                    (row.get("case_id"), code)
                )
                continue
            packet_count += 1
            _require(
                packet.get("support_not_inferred") is True,
                f"{code} packet can manufacture support",
            )

            if code in {"C08", "C13"}:
                _require(
                    bool(packet.get("falsification_checks")),
                    f"{code} missing falsification checks",
                )
            elif code in {"C10", "C11", "C14"}:
                _require(
                    bool(packet.get("experiment")),
                    f"{code} missing market validation experiment",
                )
            elif code == "C12":
                _require(
                    len(packet.get("scenario_matrix") or []) >= 3,
                    "C12 missing technology/window scenario matrix",
                )
                _require(
                    packet.get("forecast_claimed") is False,
                    "C12 is pretending scenario context is a forecast",
                )

    _require(
        not missing_packets,
        f"missing Floor60 packets: {missing_packets[:10]}",
    )

    portfolio = build_research_portfolio(rows)
    _require(
        bool(portfolio.get("ranked_groups")),
        "research portfolio produced no ranked source groups",
    )

    daily = await build_founder_daily_surface(
        limit=10,
        save_snapshot=True,
    )
    _require(
        len(daily.get("cards") or []) >= min(3, len(rows)),
        "Founder daily surface produced too few cards",
    )
    _require(
        bool(daily.get("snapshot_path")),
        "Founder daily surface did not persist JSON snapshot",
    )

    replay_now = await run_historical_replay(
        cutoff=datetime.utcnow(),
        save_report=True,
    )
    replay_30 = await run_historical_replay(
        cutoff=datetime.utcnow() - timedelta(days=30),
        save_report=True,
    )
    _require(
        replay_now.get("cases") == len(rows),
        "historical replay current cutoff case coverage mismatch",
    )
    _require(
        "leakage" in replay_30,
        "historical replay missing leakage accounting",
    )
    _require(
        replay_30.get("predictive_accuracy") == "UNVALIDATED",
        "historical replay fabricated predictive accuracy",
    )

    registry_module = importlib.import_module(
        "processors.validation_registry"
    )
    market_module = importlib.import_module(
        "processors.market_ground_truth"
    )
    _require(
        hasattr(registry_module, "create_validation_experiment"),
        "validation pre-registration missing",
    )
    _require(
        hasattr(market_module, "record_market_result"),
        "market-result recorder missing",
    )

    calibration = calibration_report()
    cred = calibration.get("credibility") or {}
    if int(calibration.get("completed_experiments", 0) or 0) < 10:
        _require(
            cred.get("status") == "UNVALIDATED",
            "calibration claimed credibility without enough outcomes",
        )

    boundary_counts = {}
    for row in rows:
        key = str(
            row.get("market_validation_boundary")
            or "UNKNOWN"
        )
        boundary_counts[key] = boundary_counts.get(key, 0) + 1

    print("REALITY ENGINE")
    print(
        f"  cases={floor.get('cases')} | "
        f"packets={packet_count} | "
        f"packet_cases={packet_cases}"
    )
    print(
        "  boundaries: "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(
                (floor.get("boundary_counts") or {}).items()
            )
        )
    )
    print()

    print("PORTFOLIO SCHEDULER")
    for item in (portfolio.get("ranked_groups") or [])[:4]:
        print(
            f"  {item['group']}: voi={item['voi']} "
            f"cases={item['case_count']} "
            f"unlocks={','.join(item['unlock_dimensions'])}"
        )
    print()

    print("FOUNDER DAILY SURFACE")
    print(
        f"  cards={len(daily.get('cards') or [])} | "
        f"snapshot={daily.get('snapshot_path')}"
    )
    print(
        "  validation boundary: "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(boundary_counts.items())
        )
    )
    print()

    print("HISTORICAL REPLAY")
    print(
        f"  now: cases={replay_now.get('cases')} "
        f"stages={replay_now.get('stage_counts')} "
        f"report={replay_now.get('report_path')}"
    )
    print(
        f"  30d: cases={replay_30.get('cases')} "
        f"stages={replay_30.get('stage_counts')} "
        f"future_excluded="
        f"{(replay_30.get('leakage') or {}).get('excluded_future_evidence', 0)} "
        f"report={replay_30.get('report_path')}"
    )
    print()

    print("MARKET CLOSURE + CALIBRATION")
    print(
        f"  registered={calibration.get('registered_experiments')} | "
        f"completed={calibration.get('completed_experiments')} | "
        f"credibility={cred.get('status')}"
    )
    print()

    print("FLOOR60_ENGINEERING_ACCEPTANCE_PASS")
    print(
        "Engineering capability floor is installed across C08/C10/C11/C12/"
        "C13/C14, scheduler, Founder surface, market closure, and replay."
    )
    print(
        "True live-market predictive accuracy remains UNVALIDATED until real "
        "pre-registered outcomes exist."
    )
    print("=" * 120)


if __name__ == "__main__":
    asyncio.run(main())
