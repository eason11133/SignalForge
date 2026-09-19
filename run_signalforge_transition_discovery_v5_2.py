"""One real V5.2 change-first discovery pass using existing SignalForge sources.

No crawler is invoked here. Up to two mini-model calls are used to connect
cross-source change evidence with lagging concrete workflows. Existing Radar
ledger/decision/Founder surface are then rebuilt from persisted truth.
"""
from __future__ import annotations

import asyncio

from processors.transition_gap_discovery import run_transition_gap_discovery
from processors.radar_ledger import run_radar_ledger
from processors.opportunity_decision import run_opportunity_decision
from processors.founder_daily_surface import build_founder_daily_surface, print_founder_daily_surface


async def main() -> None:
    print("=" * 112)
    print("SIGNALFORGE V5.2 — CHANGE-FIRST TRANSITION-GAP DISCOVERY")
    print("=" * 112)
    print("Crawler calls: 0 | max LLM calls: 2 | product ideation: DISABLED")
    result = await run_transition_gap_discovery(ai_call_allowance=2, max_persist=12)
    print(
        f"sources={result.get('source_counts')} | docs={result.get('documents_seen')} | "
        f"change_docs={result.get('change_docs')} | lag_docs={result.get('lag_docs')} | "
        f"pair_pool={result.get('pair_pool')}"
    )
    print(
        f"accepted={result.get('accepted')} | inserted={result.get('inserted')} | "
        f"updated={result.get('updated')} | evidence_rows={result.get('evidence_rows')} | "
        f"llm_calls={result.get('llm_calls')}"
    )
    for i, row in enumerate(result.get("accepted_summaries") or [], 1):
        print("-" * 112)
        print(f"#{i} {row.get('problem')}")
        print(f"Actor: {row.get('actor')}")
        print(f"Workflow: {row.get('workflow')}")
        print(f"Change: {row.get('change')}")
        print(f"Legacy: {row.get('legacy_workflow')}")
        print(f"Economic signal: {row.get('economic_signal')}")
        print(f"Confidence: {row.get('confidence')}")

    await run_radar_ledger()
    decision = await run_opportunity_decision(limit=80, reality_mode="persisted")
    snapshot = await build_founder_daily_surface(limit=10, save_snapshot=True, decision=decision)
    print_founder_daily_surface(snapshot)
    gate = snapshot.get("solo_founder_gate") or {}
    print("\nSOLO FOUNDER GATE")
    print(
        f"ready={gate.get('ready', 0)} | watch={gate.get('watch', 0)} | "
        f"research_themes_parked={gate.get('research_themes_parked', 0)}"
    )
    print("\nNOTE: accepted transition candidates are discovery hypotheses backed by source pairs; market outcome remains UNVALIDATED.")


if __name__ == "__main__":
    asyncio.run(main())
