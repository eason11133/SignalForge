from __future__ import annotations

import asyncio
import sys

from init_db import init_db
from processors.signalforge_runtime import run_signalforge_manual_cycle


async def main() -> None:
    await init_db()
    result = await run_signalforge_manual_cycle(force_refresh=False)
    if result.get("skipped"):
        reason = result.get("skip_reason")
        if reason == "BUSY_CROSS_PROCESS":
            owner = result.get("owner") or {}
            print(
                "SignalForge cycle not started: another process owns the runtime lease "
                f"(pid={owner.get('pid')} reason={owner.get('reason')})."
            )
            raise SystemExit(20)
        if reason not in {None, "FRESH"}:
            print(f"SignalForge cycle not started: {reason}")
            raise SystemExit(21)


if __name__ == "__main__":
    asyncio.run(main())
