from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def make_result(tag: str):
    return {
        "status": "RESEARCH_READY",
        "research_brief": {
            "summary": {"useful_result_count": 2, "human_comment_count": 1, "supporting_evidence_count": 1},
            "human_comments": [{"source": "TEST", "title": tag, "excerpt": "direct user evidence", "url": f"https://example.test/{tag}"}],
            "similar_products": [], "repo_solutions": [],
            "supporting_evidence": [{"source": "TEST", "title": f"{tag}-support", "excerpt": "support", "url": f"https://example.test/{tag}/support"}],
            "counter_evidence": [], "gaps": [],
            "search": {"successful_sources": ["TEST"], "failed_sources": []},
        },
        "market_truth_writes": 0,
    }


async def asgi_request(app, method: str, path: str):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": method, "path": path, "query_string": b"", "headers": []}
    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(body or b"{}")


def main() -> int:
    from processors.signalforge_research_backlog import add_ideas, backlog_detail, backlog_view, load_store, request_stop, reset_store_for_acceptance, run_single_item

    checks = {}
    with tempfile.TemporaryDirectory(prefix="sf_single_item_") as td:
        repo = Path(td)
        reset_store_for_acceptance(repo)
        add_ideas(repo, [
            {"title": "Direction One", "description": "one", "source_kind": "USER_SUBMITTED"},
            {"title": "Direction Two", "description": "two", "source_kind": "USER_SUBMITTED"},
        ])
        item_ids = [item["id"] for item in backlog_view(repo, limit=10)["items"]]
        first_id, second_id = item_ids[0], item_ids[1]
        request_stop(repo)
        before_two = backlog_detail(repo, second_id)["item"]
        result = asyncio.run(run_single_item(repo, first_id, research_fn=lambda *_: asyncio.sleep(0, result=make_result("one"))))
        after_one = backlog_detail(repo, first_id)["item"]
        after_two = backlog_detail(repo, second_id)["item"]
        store = load_store(repo, repair_worker=False)
        checks["A_paused_global_does_not_block_single"] = result["status"] == "SINGLE_ITEM_RESEARCH_COMPLETED"
        checks["B_only_selected_item_runs"] = len(after_one.get("history") or []) == 1 and len(after_two.get("history") or []) == len(before_two.get("history") or [])
        checks["C_global_pause_unchanged"] = bool(store["automation"]["paused_by_founder"]) and result["paused_before"] and result["paused_after"]
        checks["H_material_and_history_persist"] = len(after_one.get("history") or []) == 1 and int(after_one.get("material_stats", {}).get("total") or 0) > 0
        checks["I_market_truth_untouched"] = result["market_truth_writes"] == 0 and store.get("market_truth_writes") == 0

        store_path = repo / ".radar_runtime" / "founder_opportunity_research_v1.json"
        os.environ["SIGNALFORGE_BACKLOG_STORE"] = str(store_path)
        os.environ["SIGNALFORGE_REPO_ROOT"] = str(repo)
        os.environ["SIGNALFORGE_RESEARCH_RUNS_PATH"] = str(repo / ".radar_runtime" / "single_runs.json")
        os.environ["SIGNALFORGE_RESEARCH_REPEAT_COOLDOWN_SECONDS"] = "30"
        spec = importlib.util.spec_from_file_location("sf_single_persistence_test", ROOT / "api" / "signalforge_research_persistence_v253.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class Canonical:
            def __init__(self): self.calls = []
            async def __call__(self, scope, receive, send):
                item_id = scope["path"].split("/")[-2]
                self.calls.append(item_id)
                await asyncio.sleep(0.25)
                body = json.dumps({"status": "SINGLE_ITEM_RESEARCH_COMPLETED", "materials_added": 1, "market_truth_writes": 0}).encode()
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": body})

        canonical = Canonical()
        app = module.SignalForgeResearchPersistenceMiddleware(canonical)
        path1 = f"/api/signalforge/research-backlog/{first_id}/run"
        path2 = f"/api/signalforge/research-backlog/{second_id}/run"
        s1, r1 = asyncio.run(asgi_request(app, "POST", path1))
        s2, r2 = asyncio.run(asgi_request(app, "POST", path1))
        s3, r3 = asyncio.run(asgi_request(app, "POST", path2))
        checks["D_duplicate_click_reuses_run"] = s1 == s2 == 202 and r1["run_id"] == r2["run_id"] and not r2["started"]
        checks["E_different_items_have_distinct_runs"] = s3 == 202 and r3["run_id"] != r1["run_id"]
        time.sleep(0.4)
        sg, rg = asyncio.run(asgi_request(app, "GET", f"/api/signalforge/research-backlog/runs/{first_id}"))
        checks["F_backend_status_is_reconnectable"] = sg == 200 and rg["run"]["run_id"] == r1["run_id"]
        checks["G_single_completion_is_terminal"] = rg["run"]["status"] == "SUCCEEDED" and rg["run"]["finished_at"]
        checks["single_calls_not_duplicated"] = canonical.calls.count(first_id) == 1 and canonical.calls.count(second_id) == 1

    for name, ok in checks.items():
        print(f"{name}={'PASS' if ok else 'FAIL'}")
    if all(checks.values()):
        print("SIGNALFORGE_SINGLE_ITEM_PERSISTENCE_REGRESSION_PASS")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
