from __future__ import annotations
import asyncio
from processors.system_wide_audit import run_system_wide_audit


async def main():
    result = await run_system_wide_audit()
    print("=" * 132)
    print("SIGNALFORGE FULL-SYSTEM FINE-GRAINED AUDIT — M18 OPERATIONAL CUTOVER")
    print("=" * 132)
    if result.get("deferred_while_cycle_running"):
        runtime = result.get("runtime") or {}
        published = result.get("published_founder") or {}
        print("AUDIT_DEFERRED_WHILE_CYCLE_RUNNING")
        print(f"owner={((runtime.get('lease') or {}).get('reason'))} pid={((runtime.get('lease') or {}).get('pid'))}")
        print(f"last_success_at={runtime.get('last_success_at')}")
        print(f"published_verdicts={published.get('verdict_counts') or {}}")
        print("Unpublished DB truth was not inspected.")
        print("=" * 132)
        raise SystemExit(22)
    q = result.get("quality") or {}
    print(f"Quality={q.get('status')} critical={q.get('critical_count',0)} warnings={q.get('warning_count',0)}")
    print("Percentages are accepted baselines only; M18 does not auto-inflate completion.")
    for name, row in result["areas"].items():
        pct = row.get("baseline_percent")
        pct_text = "UNVALIDATED" if pct is None else f"{pct}%"
        target = row.get("go_live_target")
        target_text = "n/a" if target is None else f"{target}%"
        print("-" * 132)
        print(f"{name}: baseline={pct_text} | go-live target={target_text}")
        if row.get("observed"):
            print("  observed:", row["observed"])
        for item in row.get("problems", []):
            print("  PROBLEM:", item)
        for item in row.get("m13_progress", []):
            print("  M13:", item)
        for item in row.get("m14_progress", []):
            print("  M14:", item)
        for item in row.get("m15_progress", []):
            print("  M15:", item)
        for item in row.get("m16_progress", []):
            print("  M16:", item)
        for item in row.get("m17_progress", []):
            print("  M17:", item)
        for item in row.get("m18_progress", []):
            print("  M18:", item)
    print("=" * 132)


if __name__ == "__main__":
    asyncio.run(main())
