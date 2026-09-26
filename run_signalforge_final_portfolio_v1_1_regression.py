from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from processors import signalforge_research_backlog as rb  # noqa: E402


def fail(msg: str) -> None:
    print("FAIL:", msg)
    raise SystemExit(1)


store_path = ROOT / ".radar_runtime" / "founder_opportunity_research_v1.json"
if not store_path.exists():
    fail(f"canonical store missing: {store_path}")

with store_path.open("r", encoding="utf-8") as fh:
    raw = json.load(fh)

items = raw.get("items") if isinstance(raw, dict) else None
order = raw.get("order") if isinstance(raw, dict) else None
if not isinstance(items, dict):
    fail("canonical items is not a dict")
if not isinstance(order, list):
    fail("canonical order is not a list")

print(f"canonical_items={len(items)}")
print(f"canonical_order={len(order)}")
print(f"market_truth_writes={raw.get('market_truth_writes')}")

if len(items) != len(order):
    fail("items/order count mismatch")
if int(raw.get("market_truth_writes") or 0) != 0:
    fail("market_truth_writes is not zero")

# Prove read endpoints do NOT touch the migration/write path.
original_load_store = rb.load_store
original_save_store = rb.save_store

def forbidden(*args, **kwargs):
    raise AssertionError("read endpoint touched migration/write path")

rb.load_store = forbidden
rb.save_store = forbidden

try:
    t0 = time.perf_counter()
    view = rb.backlog_view(ROOT, limit=5)
    list_elapsed = time.perf_counter() - t0

    print("list_read_path=READ_ONLY")
    print(f"list_limit5_seconds={list_elapsed:.3f}")
    print(f"list_total={view.get('total')}")
    print(f"list_items={len(view.get('items') or [])}")

    if int(view.get("total") or 0) != len(items):
        fail("list total does not match canonical store")
    if len(view.get("items") or []) != min(5, len(items)):
        fail("list limit=5 is not respected")
    if list_elapsed > 10.0:
        fail(f"read-only list path is too slow: {list_elapsed:.3f}s")

    first = (view.get("items") or [None])[0]
    if first and first.get("id"):
        t1 = time.perf_counter()
        detail = rb.backlog_detail(ROOT, str(first["id"]))
        detail_elapsed = time.perf_counter() - t1

        print("detail_read_path=READ_ONLY")
        print(f"detail_seconds={detail_elapsed:.3f}")
        print(f"detail_status={detail.get('status')}")

        if detail.get("status") != "OK":
            fail("detail read failed")
        if detail_elapsed > 10.0:
            fail(f"detail read path is too slow: {detail_elapsed:.3f}s")
finally:
    rb.load_store = original_load_store
    rb.save_store = original_save_store

page = (ROOT / "dashboard/src/pages/ResearchBacklog.tsx").read_text(encoding="utf-8")

ui_checks = {
    "final_title": "持續市場研究" in page,
    "evidence_first_copy": "不自動下市場結論" in page,
    "behavior_section": "行為與趨勢變化" in page,
    "pattern_section": "重複行為模式" in page,
    "handoff_section": "研究資料交接" in page,
    "stale_interrupt_hidden": "Previous API process stopped|in-flight searches were requeued" in page,
}

for name, ok in ui_checks.items():
    print(f"{name}={'PASS' if ok else 'FAIL'}")
    if not ok:
        fail(name)

print("SIGNALFORGE_FINAL_PORTFOLIO_V1_1_REGRESSION_PASS")
