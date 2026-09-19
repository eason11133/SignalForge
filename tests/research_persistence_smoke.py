from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("sf_v253_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


async def request(app, method: str, path: str, payload=None):
    body = json.dumps(payload or {}).encode()
    sent = False
    messages = []
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type":"http.request","body":body,"more_body":False}
        return {"type":"http.disconnect"}
    async def send(msg):
        messages.append(msg)
    scope = {
        "type":"http", "asgi":{"version":"3.0"}, "http_version":"1.1",
        "method":method, "scheme":"http", "path":path, "raw_path":path.encode(),
        "query_string":b"", "headers":[(b"content-type",b"application/json")],
        "client":("127.0.0.1",12345), "server":("test",80), "root_path":"",
    }
    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    data = b"".join(m.get("body",b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(data.decode()) if data else None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "src" / "api" / "signalforge_research_persistence.py"
    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td)
        os.environ["SIGNALFORGE_RUNTIME_DIR"] = str(runtime)
        os.environ["SIGNALFORGE_RESEARCH_RUNS_PATH"] = str(runtime / "runs.json")
        os.environ["SIGNALFORGE_RESEARCH_REPEAT_COOLDOWN_SECONDS"] = "30"
        os.environ["SIGNALFORGE_RESEARCH_POST_RETURN_SETTLE_SECONDS"] = "1"
        mod = load_module(module_path)

        class CanonicalStart:
            def __init__(self):
                self.calls = 0
            async def __call__(self, scope, receive, send):
                self.calls += 1
                body = b""
                while True:
                    msg = await receive()
                    if msg.get("type") == "http.request":
                        body += msg.get("body", b"")
                        if not msg.get("more_body"):
                            break
                await asyncio.sleep(0.35)
                out = json.dumps({"status":"COMPLETE","canonical_calls":self.calls}).encode()
                await send({"type":"http.response.start","status":200,"headers":[(b"content-type",b"application/json")]})
                await send({"type":"http.response.body","body":out,"more_body":False})

        canonical = CanonicalStart()
        middleware = mod.SignalForgeResearchPersistenceMiddleware(canonical)
        payload = {"item_id":"direction-42"}
        t0 = time.time()
        s1, r1 = asyncio.run(request(middleware, "POST", "/api/signalforge/research-backlog/start", payload))
        elapsed = time.time() - t0
        assert s1 == 202 and r1["started"] is True and elapsed < 0.25, (s1, r1, elapsed)
        run_id = r1["run_id"]
        s2, r2 = asyncio.run(request(middleware, "POST", "/api/signalforge/research-backlog/start", payload))
        assert s2 == 202 and r2["run_id"] == run_id and r2["started"] is False, (s2, r2)
        assert canonical.calls <= 1, canonical.calls
        time.sleep(0.55)
        s3, r3 = asyncio.run(request(middleware, "GET", "/api/signalforge/research-backlog/runs/direction-42"))
        assert s3 == 200 and r3["run"]["run_id"] == run_id, (s3, r3)
        assert Path(os.environ["SIGNALFORGE_RESEARCH_RUNS_PATH"]).exists()
        persisted = json.loads(Path(os.environ["SIGNALFORGE_RESEARCH_RUNS_PATH"]).read_text())
        assert run_id in persisted["runs"]
        assert persisted["runs"][run_id]["market_truth_writes"] == 0

        checks = {
            "browser_request_returns_before_canonical_work_finishes": elapsed < 0.25,
            "same_direction_active_run_is_idempotent": r2["run_id"] == run_id and r2["started"] is False,
            "canonical_start_not_duplicated": canonical.calls == 1,
            "run_id_persists_across_view_requests": r3["run"]["run_id"] == run_id,
            "durable_run_registry_written": Path(os.environ["SIGNALFORGE_RESEARCH_RUNS_PATH"]).exists(),
            "market_truth_writes_0": persisted["runs"][run_id]["market_truth_writes"] == 0,
        }
        for k, v in checks.items():
            print(f"{k}={'PASS' if v else 'FAIL'}")
        if all(checks.values()):
            print("SIGNALFORGE_TRACKING_RESEARCH_PERSISTENCE_V2_5_3_SMOKE_PASS")
            return 0
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
