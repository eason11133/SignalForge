#!/usr/bin/env python3
"""Detached SignalForge runtime worker.

The FastAPI process may dispatch this worker, but all real SignalForge cycle
execution and cross-process mutation authority remain inside the canonical
runtime lease. This script never changes truth rules; it only isolates workload
from the web event loop. R7 also treats child dispatch receipts as best-effort
observability so a Windows file-sharing race cannot kill production work.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import traceback

from processors.signalforge_runtime import (
    record_worker_dispatch_state,
    run_signalforge_if_stale,
    run_signalforge_manual_cycle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reason", default="manual_api")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dispatch-id", default=None)
    args = parser.parse_args()

    # Dispatch receipts are observability only. A receipt write failure must not
    # block the canonical runtime lease from executing the production cycle.
    record_worker_dispatch_state(status="WORKER_STARTED", dispatch_id=args.dispatch_id)
    try:
        if args.reason == "manual_cli":
            result = asyncio.run(
                run_signalforge_manual_cycle(force_refresh=bool(args.force_refresh))
            )
        else:
            result = asyncio.run(
                run_signalforge_if_stale(
                    force=bool(args.force),
                    reason=str(args.reason),
                )
            )
        record_worker_dispatch_state(status="WORKER_FINISHED", dispatch_id=args.dispatch_id)
        print(json.dumps({
            "status": "PASS",
            "runtime_status": result.get("status"),
            "skipped": bool(result.get("skipped", False)),
            "skip_reason": result.get("skip_reason"),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        record_worker_dispatch_state(status="WORKER_FAIL", error=error, dispatch_id=args.dispatch_id)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
