from __future__ import annotations

import asyncio
import json

from processors.signalforge_brain_v2_benchmark import benchmark_dataset_contract, synthetic_time_slice_acceptance


async def main() -> int:
    checks = await synthetic_time_slice_acceptance()
    print("=" * 120)
    print("SignalForge Brain v2 — Time-Sliced Benchmark Readiness")
    print("=" * 120)
    print("BENCHMARK_CONTRACT:", json.dumps(benchmark_dataset_contract(), ensure_ascii=False))
    print("SYNTHETIC_TIME_SLICE:", json.dumps(checks, ensure_ascii=False))
    ok = all(checks.values())
    print("Market Calibration changed: NO")
    print("FINAL_STATUS:", "SIGNALFORGE_BRAIN_V2_BENCHMARK_READINESS_PASS" if ok else "SIGNALFORGE_BRAIN_V2_BENCHMARK_READINESS_FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
