"""Quick persisted-reality rebuild after Solo Transition V5 install.

No crawler and no LLM are intentionally invoked by this script. It re-evaluates
Company Truth, the persisted evidence ledger, Decision, and Founder Daily snapshot.
"""
from __future__ import annotations

import asyncio

from processors.opportunity_decision import run_opportunity_decision
from processors.founder_daily_surface import build_founder_daily_surface, print_founder_daily_surface


async def main() -> None:
    print("SignalForge Solo Transition quick rebuild")
    print("Crawler calls: 0 | LLM calls: 0 | full Radar cycle: 0")
    decision = await run_opportunity_decision(limit=50, reality_mode="persisted")
    snapshot = await build_founder_daily_surface(limit=10, save_snapshot=True, decision=decision)
    print_founder_daily_surface(snapshot)
    gate = snapshot.get("solo_founder_gate") or {}
    print("\nSOLO FOUNDER GATE")
    print(
        f"ready={gate.get('ready', 0)} | watch={gate.get('watch', 0)} | "
        f"research_themes_parked={gate.get('research_themes_parked', 0)}"
    )
    if not snapshot.get("cards"):
        print("No Founder-ready opportunity is currently supported. This is a valid result; no filler cards were created.")


if __name__ == "__main__":
    asyncio.run(main())
