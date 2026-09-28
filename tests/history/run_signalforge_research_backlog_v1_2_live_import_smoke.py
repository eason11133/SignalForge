from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path


async def main() -> int:
    # Read the user's real database through the installed route adapters, but never mutate the
    # persistent production backlog during an installer hard gate. Import/dedupe/handoff are
    # exercised in a temporary backlog; the real API startup performs the live sync only after
    # the release has fully installed.
    from api.routes.signalforge_research_backlog import _load_opportunities, _load_problem_candidates
    from processors.signalforge_research_backlog import auto_run_allowed, backlog_detail, backlog_view, sync_backlog

    candidates, candidate_warning = await _load_problem_candidates()
    opportunities, opportunity_warning = await _load_opportunities()
    source_counts = {"problem_candidates": len(candidates), "opportunities": len(opportunities)}
    source_total = len(candidates) + len(opportunities)
    warnings = [x for x in (candidate_warning, opportunity_warning) if x]

    with tempfile.TemporaryDirectory(prefix="signalforge-live-import-smoke-") as tmp:
        scratch = Path(tmp)
        sync_result = sync_backlog(scratch, candidates=candidates, opportunities=opportunities)
        view = backlog_view(scratch, limit=5)
        backlog_total = int(view.get("total") or 0)
        first = (view.get("items") or [None])[0]
        first_id = str(first.get("id") or "") if isinstance(first, dict) else ""
        detail = backlog_detail(scratch, first_id) if first_id else {}
        detail_item = detail.get("item") if isinstance(detail, dict) else None
        handoff_ok = isinstance(detail_item, dict) and "SIGNALFORGE HANDOFF" in str(detail_item.get("handoff") or "")
        list_is_lightweight = isinstance(first, dict) and "handoff" not in first and "history" not in first
        truth_ok = int(view.get("market_truth_writes") or 0) == 0
        automation = view.get("automation") or {}

        checks = {
            "existing_signalforge_rows_found": source_total > 0,
            "scratch_backlog_populated": backlog_total > 0,
            "lightweight_list_contract": bool(list_is_lightweight),
            "pasteable_detail_handoff_generated": bool(handoff_ok),
            "market_truth_writes_zero": truth_ok,
            "automation_state_present": "paused_by_founder" in automation and "auto_run_enabled" in automation,
            "auto_run_policy_is_readable": isinstance(auto_run_allowed(scratch), bool),
            "smoke_uses_temporary_backlog_not_production_history": str(scratch) != str(Path.cwd()),
        }
        print("RESEARCH_BACKLOG_V1_4_LIVE_IMPORT_SMOKE", json.dumps({
            "checks": checks,
            "source_counts": source_counts,
            "scratch_backlog_total_after_dedupe": backlog_total,
            "sync_result": {
                "added": sync_result.get("added", 0),
                "refreshed": sync_result.get("refreshed", 0),
                "merged_duplicates": sync_result.get("merged_duplicates", 0),
            },
            "automation": automation,
            "import_warnings": warnings,
            "persistent_production_backlog_touched": False,
        }, ensure_ascii=False))
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            print("RESEARCH_BACKLOG_V1_4_LIVE_IMPORT_SMOKE_FAIL", failed)
            return 2
        print("RESEARCH_BACKLOG_V1_4_LIVE_IMPORT_SMOKE_PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
