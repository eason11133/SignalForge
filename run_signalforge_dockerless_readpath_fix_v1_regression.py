from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from processors import signalforge_research_backlog as rb  # noqa: E402


def fail(message: str) -> None:
    print("FAIL:", message)
    raise SystemExit(1)


store_path = ROOT / ".radar_runtime" / "founder_opportunity_research_v1.json"
if not store_path.exists():
    fail(f"missing canonical store: {store_path}")

before_stat = store_path.stat()
before_mtime = before_stat.st_mtime_ns
before_size = before_stat.st_size

with store_path.open("r", encoding="utf-8") as fh:
    raw = json.load(fh)

items = raw.get("items") if isinstance(raw, dict) else None
order = raw.get("order") if isinstance(raw, dict) else None
if not isinstance(items, dict):
    fail("canonical items is not a dict")
if not isinstance(order, list):
    fail("canonical order is not a list")

expected = len(items)
print(f"canonical_items={expected}")
print(f"canonical_order={len(order)}")

t0 = time.perf_counter()
view = rb.backlog_view(ROOT, limit=1000)
cold = time.perf_counter() - t0

t1 = time.perf_counter()
view2 = rb.backlog_view(ROOT, limit=5)
warm = time.perf_counter() - t1

actual = len(view.get("items") or [])
total = int(view.get("total") or 0)
limited = len(view2.get("items") or [])

print(f"backlog_total={total}")
print(f"backlog_items={actual}")
print(f"limited_items={limited}")
print(f"cold_seconds={cold:.3f}")
print(f"warm_seconds={warm:.3f}")

if total != expected:
    fail(f"API-view total mismatch: expected {expected}, got {total}")
if actual != min(expected, 1000):
    fail(f"full list mismatch: expected {min(expected, 1000)}, got {actual}")
if expected and limited != min(expected, 5):
    fail(f"limit not applied correctly: got {limited}")

after_stat = store_path.stat()
if after_stat.st_mtime_ns != before_mtime:
    fail("read-only backlog_view changed canonical store mtime")
if after_stat.st_size != before_size:
    fail("read-only backlog_view changed canonical store size")

# Warm-cache request should be comfortably below the old timeout path.
if warm > 2.0:
    fail(f"warm cached list is unexpectedly slow: {warm:.3f}s")

first_id = None
for row in view.get("items") or []:
    if isinstance(row, dict) and row.get("id"):
        first_id = str(row["id"])
        break

if first_id:
    td0 = time.perf_counter()
    detail = rb.backlog_detail(ROOT, first_id)
    detail_cold = time.perf_counter() - td0

    td1 = time.perf_counter()
    detail2 = rb.backlog_detail(ROOT, first_id)
    detail_warm = time.perf_counter() - td1

    print(f"detail_id={first_id}")
    print(f"detail_cold_seconds={detail_cold:.3f}")
    print(f"detail_warm_seconds={detail_warm:.3f}")

    if detail.get("status") != "OK" or (detail.get("item") or {}).get("id") != first_id:
        fail("detail read path failed")
    if detail2.get("status") != "OK":
        fail("detail warm-cache read failed")
    if detail_warm > 1.0:
        fail(f"warm cached detail is unexpectedly slow: {detail_warm:.3f}s")

final_stat = store_path.stat()
if final_stat.st_mtime_ns != before_mtime or final_stat.st_size != before_size:
    fail("read-only detail changed canonical store")

print("market_truth_writes=" + str(view.get("market_truth_writes")))
if int(view.get("market_truth_writes") or 0) != 0:
    fail("market_truth_writes is not zero")

print("SIGNALFORGE_DOCKERLESS_READPATH_FIX_V1_REGRESSION_PASS")
