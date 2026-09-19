from __future__ import annotations

import argparse
import asyncio

from processors.signalforge_brain_v2_engine import refresh_signalforge_brain_v2
from processors.signalforge_brain_v2_runtime import mark_brain_v2_run_finished, mark_brain_v2_run_started


async def main(reason: str) -> int:
    mark_brain_v2_run_started(reason=reason)
    try:
        result = await refresh_signalforge_brain_v2()
        mark_brain_v2_run_finished(result=result)
        print("=" * 112)
        print("SIGNALFORGE BRAIN V2 DERIVED REFRESH")
        print("=" * 112)
        print("status:", result.get("status"))
        print("refresh_skipped:", result.get("refresh_skipped", False))
        print("elapsed_ms:", result.get("elapsed_ms"))
        print("counts:", result.get("counts") or {})
        print("classification_counts:", result.get("classification_counts") or {})
        print("zip2_counts:", result.get("zip2_counts") or {})
        print("Production truth mutated: NO")
        print("FINAL_STATUS: SIGNALFORGE_BRAIN_V2_DERIVED_REFRESH_PASS")
        return 0
    except Exception as exc:
        mark_brain_v2_run_finished(error=exc)
        print(f"FINAL_STATUS: SIGNALFORGE_BRAIN_V2_DERIVED_REFRESH_FAIL {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reason", default="manual_brain_refresh")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.reason)))
