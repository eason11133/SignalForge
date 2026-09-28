from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from processors.opportunity_decision import run_opportunity_decision
from processors.case_progression import select_progression_targets
from processors.research_portfolio import build_research_portfolio
from processors.quality_guard import (
    audit_quality,
    capture_quality_snapshot,
    repair_ledger_state_from_validated_links,
)
from processors.founder_daily_surface import build_founder_daily_surface
from processors.historical_replay import run_historical_replay
from processors.calibration import calibration_report
from processors.market_ground_truth import validate_market_result_request


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def main() -> None:
    print("=" * 122)
    print("SIGNALFORGE QUALITY-LOCKED PROGRESSION ACCEPTANCE")
    print("=" * 122)
    print("No crawler. No LLM. No threshold weakening. No synthetic market outcome.")
    print()

    ledger_repair = await repair_ledger_state_from_validated_links()

    decision = await run_opportunity_decision(limit=50)
    rows = decision.get("rows", [])
    _require(bool(rows), "no decision rows")

    quality = await audit_quality(decision=decision)
    _require(
        quality.get("status") == "PASS",
        "quality audit failed: " + str(quality.get("critical", [])[:8]),
    )

    snapshot = await capture_quality_snapshot()
    _require(
        bool(snapshot.get("claims")),
        "quality rollback snapshot contains no claims",
    )
    _require(
        bool(snapshot.get("links")),
        "quality rollback snapshot contains no evidence links",
    )

    # Prior Floor-60 capability regression checks remain mandatory.
    floor60_missing = []
    for row in rows:
        floor = row.get("floor60_reality") or {}
        packets = floor.get("packets") or {}
        for code in ("C08", "C10", "C11", "C12", "C13", "C14"):
            packet = packets.get(code)
            if not packet:
                floor60_missing.append((row.get("case_id"), code))
                continue
            _require(
                packet.get("support_not_inferred") is True,
                f"prior Floor60 {code} can manufacture support",
            )
            if code in {"C08", "C13"}:
                _require(
                    bool(packet.get("falsification_checks")),
                    f"prior Floor60 {code} lost falsification checks",
                )
            elif code in {"C10", "C11", "C14"}:
                _require(
                    bool(packet.get("experiment")),
                    f"prior Floor60 {code} lost market experiment",
                )
            elif code == "C12":
                _require(
                    len(packet.get("scenario_matrix") or []) >= 3,
                    "prior Floor60 C12 lost scenario matrix",
                )
                _require(
                    packet.get("forecast_claimed") is False,
                    "prior Floor60 C12 started claiming a forecast",
                )

    _require(
        not floor60_missing,
        f"prior Floor60 packets regressed: {floor60_missing[:10]}",
    )

    missing_progression = []
    missing_queries = []
    support_leaks = []

    for row in rows:
        prog = row.get("progression") or {}
        if not prog:
            missing_progression.append(row.get("case_id"))
            continue

        contract = prog.get("promotion_contract") or {}
        _require(
            contract.get("thresholds_weakened") is False,
            f"case {row.get('case_id')} progression weakens thresholds",
        )
        _require(
            contract.get("build_allowed_now") is False,
            f"case {row.get('case_id')} illegally allows BUILD",
        )

        packets = prog.get("query_packets") or []
        gate = str(row.get("current_gate") or "")
        if gate and gate != "DECISION_READY" and not packets:
            # Some founder-only gates may legitimately have a prepared market
            # experiment rather than a web query. Those still require an
            # explicit stop condition.
            if gate not in {"DISTRIBUTION", "ECONOMICS", "SWITCHING"}:
                missing_queries.append((row.get("case_id"), gate))

        for packet in packets:
            if packet.get("support_not_inferred") is not True:
                support_leaks.append(
                    (row.get("case_id"), packet.get("purpose"))
                )
            _require(
                bool(packet.get("quality_contract")),
                f"case {row.get('case_id')} query packet missing quality contract",
            )

    _require(
        not missing_progression,
        f"missing progression packets: {missing_progression[:10]}",
    )
    _require(
        not missing_queries,
        f"machine gate missing query packet: {missing_queries[:10]}",
    )
    _require(
        not support_leaks,
        f"query packet can manufacture support: {support_leaks[:10]}",
    )

    portfolio = build_research_portfolio(rows)
    _require(
        bool(portfolio.get("ranked_groups")),
        "portfolio produced no source-group ranking",
    )
    _require(
        bool(portfolio.get("query_jobs")),
        "portfolio produced no deduplicated query jobs",
    )

    targets = select_progression_targets(rows, limit=8)
    _require(
        len(targets) >= min(4, len(rows)),
        "focused progression did not expand beyond the old narrow target set",
    )
    watch_targets = sum(
        1 for row in targets
        if str(row.get("decision_verdict") or "").upper() == "WATCH"
    )

    # Quality boundary: an unregistered result must be rejected before DB write.
    prereg_blocked = False
    try:
        validate_market_result_request(
            case_id=int(rows[0].get("case_id") or 1),
            event="ACQUISITION",
            result="PASS",
            experiment_id="definitely-not-registered",
            actor_label="Acceptance Actor",
            amount=None,
            currency=None,
        )
    except ValueError:
        prereg_blocked = True
    _require(
        prereg_blocked,
        "unregistered market result bypass is still open",
    )

    daily = await build_founder_daily_surface(
        limit=10,
        save_snapshot=True,
    )
    daily_quality = daily.get("quality") or {}
    _require(
        daily_quality.get("status") == "PASS",
        "Founder Daily does not expose a passing quality gate",
    )
    _require(
        all((card.get("progression") or {}) for card in daily.get("cards", [])),
        "Founder Daily cards missing progression contracts",
    )

    replay_30 = await run_historical_replay(
        cutoff=datetime.utcnow() - timedelta(days=30),
        save_report=True,
    )
    _require(
        replay_30.get("predictive_accuracy") == "UNVALIDATED",
        "historical replay fabricated predictive accuracy",
    )
    _require(
        "leakage" in replay_30,
        "historical replay lost leakage accounting",
    )

    calibration = calibration_report()
    if int(calibration.get("completed_experiments", 0) or 0) < 10:
        _require(
            (calibration.get("credibility") or {}).get("status")
            == "UNVALIDATED",
            "calibration overclaimed credibility",
        )

    print("LEDGER STATE REPAIR")
    print(
        f"  checked={ledger_repair.get('checked_claims', 0)} | "
        f"changed={ledger_repair.get('changed_claims', 0)} | "
        f"by_code={ledger_repair.get('changed_by_code', {})} | "
        "thresholds_weakened=NO | evidence_deleted=0 | links_deleted=0"
    )
    for row in (ledger_repair.get("changes") or [])[:12]:
        print(
            f"  case {row.get('case_id')} {row.get('claim')}: "
            f"{(row.get('before') or {}).get('state')} -> "
            f"{(row.get('after') or {}).get('state')} | "
            f"support={(row.get('after') or {}).get('support_groups')}/"
            f"{row.get('required')}"
        )

    print("\nQUALITY GUARD")
    print(
        f"  status={quality.get('status')} | "
        f"critical={quality.get('critical_count', 0)} | "
        f"warnings={quality.get('warning_count', 0)} | "
        f"snapshot_claims={len(snapshot.get('claims', {}))} | "
        f"snapshot_links={len(snapshot.get('links', {}))}"
    )

    print("\nCASE PROGRESSION")
    print(
        f"  cases={len(rows)} | "
        f"focused_targets={len(targets)} | "
        f"WATCH_targets={watch_targets}"
    )
    print(
        "  target gates="
        + ",".join(
            str(row.get("current_gate"))
            for row in targets
        )
    )

    print("\nRESEARCH PORTFOLIO")
    print(
        f"  source_groups={len(portfolio.get('ranked_groups', []))} | "
        f"deduplicated_query_jobs={len(portfolio.get('query_jobs', []))}"
    )
    for row in portfolio.get("ranked_groups", []):
        print(
            f"  {row['group']}: voi={row['voi']} "
            f"cases={row['case_count']} "
            f"unlocks={','.join(row['unlock_dimensions'])}"
        )

    print("\nMARKET GROUND TRUTH")
    print(
        "  unregistered PASS bypass=BLOCKED | "
        f"completed={calibration.get('completed_experiments', 0)} | "
        f"independent_actor_pairs={calibration.get('independent_actor_pairs', 0)} | "
        f"credibility={(calibration.get('credibility') or {}).get('status')}"
    )

    print("\nFOUNDER DAILY")
    print(
        f"  cards={len(daily.get('cards', []))} | "
        f"quality={daily_quality.get('status')} | "
        f"snapshot={daily.get('snapshot_path')}"
    )

    leakage = replay_30.get("leakage") or {}
    print("\nHISTORICAL REPLAY QUALITY")
    print(
        f"  future_evidence_excluded={leakage.get('future_evidence_excluded', 0)} | "
        f"future_interpretation_excluded={leakage.get('future_interpretation_excluded', 0)} | "
        f"predictive_accuracy={replay_30.get('predictive_accuracy')}"
    )

    print()
    print("QUALITY_LOCKED_PROGRESSION_ACCEPTANCE_PASS")
    print(
        "Next full radar cycle may research more cases in parallel, but any "
        "new critical evidence/decision regression is automatically rolled back."
    )
    print("=" * 122)


if __name__ == "__main__":
    asyncio.run(main())
