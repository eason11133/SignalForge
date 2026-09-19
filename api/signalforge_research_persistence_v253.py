from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import unquote

_VERSION = "2.5.3"
_PROCESS_ID = uuid.uuid4().hex
_ACTIVE = {"QUEUED", "RUNNING", "RESUMING", "STOPPING"}
_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}
_ID_KEYS = ("item_id", "direction_id", "opportunity_id", "idea_id", "candidate_id", "id")
_STATUS_WORDS_ACTIVE = ("RUNNING", "RESEARCHING", "TRACKING", "SCANNING", "WORKING", "STARTED", "QUEUED")
_STATUS_WORDS_DONE = ("COMPLETE", "COMPLETED", "SUCCESS", "SUCCEEDED", "IDLE", "DONE", "STOPPED")
_EVIDENCE_KEYS = {
    "materials", "material", "evidence", "human_comments", "human_comment", "comments",
    "related_products", "products", "product_or_service", "sources", "source_links",
    "research_results", "results", "items", "documents", "findings",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _jsonable(value.dict())
        except Exception:
            pass
    return str(value)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key in _ID_KEYS:
            got = value.get(key)
            if got not in (None, "") and isinstance(got, (str, int)):
                return str(got)
        for child in value.values():
            got = _find_id(child)
            if got:
                return got
    elif isinstance(value, list):
        for child in value:
            got = _find_id(child)
            if got:
                return got
    return None


def _find_item(value: Any, item_key: str) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        for key in _ID_KEYS:
            if str(value.get(key, "")) == item_key:
                return value
        for child in value.values():
            got = _find_item(child, item_key)
            if got is not None:
                return got
    elif isinstance(value, list):
        for child in value:
            got = _find_item(child, item_key)
            if got is not None:
                return got
    return None


def _count_materials(value: Any, *, depth: int = 0) -> int:
    if depth > 7:
        return 0
    total = 0
    if isinstance(value, dict):
        for key, child in value.items():
            lk = str(key).lower()
            if lk in _EVIDENCE_KEYS or any(tok in lk for tok in ("evidence", "material", "human_comment", "related_product")):
                if isinstance(child, list):
                    total += len(child)
                    continue
            total += _count_materials(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value[:5000]:
            total += _count_materials(child, depth=depth + 1)
    return total


def _extract_progress(value: Any) -> Tuple[Optional[int], Optional[int]]:
    completed = None
    total = None
    if isinstance(value, dict):
        pairs = [
            ("completed_searches", "total_searches"),
            ("completed_queries", "total_queries"),
            ("query_runs_completed", "query_runs_total"),
            ("completed_units", "total_units"),
            ("done", "total"),
        ]
        for a, b in pairs:
            if isinstance(value.get(a), int) and isinstance(value.get(b), int):
                return int(value[a]), int(value[b])
        for child in value.values():
            completed, total = _extract_progress(child)
            if completed is not None or total is not None:
                return completed, total
    elif isinstance(value, list):
        for child in value[:200]:
            completed, total = _extract_progress(child)
            if completed is not None or total is not None:
                return completed, total
    return None, None


def _detect_active(value: Any, *, depth: int = 0) -> Optional[bool]:
    if depth > 8:
        return None
    if isinstance(value, dict):
        for key, child in value.items():
            lk = str(key).lower()
            if lk in {"worker_running", "is_running", "running", "researching", "tracking", "autopilot_running"}:
                if isinstance(child, bool):
                    return child
            if lk in {"status", "research_status", "tracking_status", "worker_status", "state"} and isinstance(child, str):
                upper = child.upper()
                if any(w in upper for w in _STATUS_WORDS_ACTIVE):
                    return True
                if any(w in upper for w in _STATUS_WORDS_DONE):
                    return False
        for child in value.values():
            got = _detect_active(child, depth=depth + 1)
            if got is not None:
                return got
    elif isinstance(value, list):
        states = []
        for child in value[:1000]:
            got = _detect_active(child, depth=depth + 1)
            if got is not None:
                states.append(got)
        if any(states):
            return True
        if states:
            return False
    return None


def _response_says_async_started(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lk = str(key).lower()
            if lk in {"worker_running", "running", "started", "queued"} and child is True:
                return True
            if lk in {"status", "state"} and isinstance(child, str):
                upper = child.upper()
                if any(w in upper for w in _STATUS_WORDS_ACTIVE):
                    return True
        return any(_response_says_async_started(v) for v in value.values())
    if isinstance(value, list):
        return any(_response_says_async_started(v) for v in value[:100])
    return False


class ResearchRunRegistry:
    def __init__(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        runtime = Path(os.environ.get("SIGNALFORGE_RUNTIME_DIR", str(repo / ".radar_runtime")))
        self.path = Path(os.environ.get(
            "SIGNALFORGE_RESEARCH_RUNS_PATH",
            str(runtime / "signalforge_research_runs_v2_5_3.json"),
        ))
        self.store_candidates = [
            runtime / "idea_research_backlog_v1.json",
            runtime / "signalforge_tracking.json",
            runtime / "tracking_store.json",
        ]
        self.lock = threading.RLock()
        self._monitor_started = False

    def _empty(self) -> Dict[str, Any]:
        return {"schema_version": 1, "engine": "research-persistence-v2.5.3", "runs": {}}

    def _load(self) -> Dict[str, Any]:
        try:
            if not self.path.exists():
                return self._empty()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("runs"), dict):
                return self._empty()
            return data
        except Exception:
            # Registry is workflow observability only. A broken registry must not corrupt research data.
            return self._empty()

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def _serialize(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return deepcopy(run)

    def begin(self, item_key: str, request_payload: Any, request_meta: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, str]:
        now = time.time()
        now_iso = _utcnow()
        fp = _stable_hash({"payload": request_payload, "path": request_meta.get("path"), "query": request_meta.get("query")})
        cooldown = max(0, int(os.environ.get("SIGNALFORGE_RESEARCH_REPEAT_COOLDOWN_SECONDS", "180")))
        with self.lock:
            data = self._load()
            runs = data["runs"]
            same = [r for r in runs.values() if r.get("item_key") == item_key and r.get("request_fingerprint") == fp]
            same.sort(key=lambda r: _parse_ts(r.get("updated_at")), reverse=True)
            if same:
                latest = same[0]
                if latest.get("status") in _ACTIVE and latest.get("process_id") == _PROCESS_ID:
                    latest["duplicate_start_suppressed"] = int(latest.get("duplicate_start_suppressed", 0)) + 1
                    latest["updated_at"] = now_iso
                    self._write(data)
                    return self._serialize(latest), False, "ACTIVE_RUN_REUSED"
                if latest.get("status") in _ACTIVE and latest.get("process_id") != _PROCESS_ID:
                    latest["status"] = "RESUMING"
                    latest["process_id"] = _PROCESS_ID
                    latest["attempt"] = int(latest.get("attempt", 1)) + 1
                    latest["updated_at"] = now_iso
                    latest["resume_reason"] = "PROCESS_RESTART_OR_ORPHAN_RECOVERY"
                    self._write(data)
                    return self._serialize(latest), True, "INTERRUPTED_RUN_RESUMED"
                if latest.get("status") in _TERMINAL and cooldown > 0:
                    age = now - _parse_ts(latest.get("finished_at") or latest.get("updated_at"))
                    if 0 <= age < cooldown:
                        latest["duplicate_start_suppressed"] = int(latest.get("duplicate_start_suppressed", 0)) + 1
                        latest["last_duplicate_at"] = now_iso
                        self._write(data)
                        return self._serialize(latest), False, "RECENT_IDENTICAL_RUN_REUSED"

            run_id = uuid.uuid4().hex
            run = {
                "run_id": run_id,
                "item_key": item_key,
                "status": "RUNNING",
                "process_id": _PROCESS_ID,
                "request_fingerprint": fp,
                "request": _jsonable(request_meta),
                "payload": _jsonable(request_payload),
                "attempt": 1,
                "created_at": now_iso,
                "started_at": now_iso,
                "updated_at": now_iso,
                "finished_at": None,
                "original_http_status": None,
                "original_response": None,
                "original_done": False,
                "original_async_started": False,
                "duplicate_start_suppressed": 0,
                "material_count": None,
                "completed_units": None,
                "total_units": None,
                "store_mtime_ns": None,
                "store_active": None,
                "last_store_change_at": None,
                "error": None,
                "market_truth_writes": 0,
            }
            runs[run_id] = run
            self._write(data)
            return self._serialize(run), True, "NEW_RUN_STARTED"

    def update(self, run_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
        with self.lock:
            data = self._load()
            run = data["runs"].get(run_id)
            if not run:
                return None
            run.update(_jsonable(changes))
            run["updated_at"] = _utcnow()
            self._write(data)
            return self._serialize(run)

    def finish(self, run_id: str, status: str = "SUCCEEDED", **changes: Any) -> Optional[Dict[str, Any]]:
        changes = dict(changes)
        changes["status"] = status
        changes["finished_at"] = _utcnow()
        return self.update(run_id, **changes)

    def get_by_item(self, item_key: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            data = self._load()
            rows = [r for r in data["runs"].values() if r.get("item_key") == item_key]
            if not rows:
                return None
            rows.sort(key=lambda r: _parse_ts(r.get("updated_at")), reverse=True)
            return self._serialize(rows[0])

    def list_runs(self, active_only: bool = False, limit: int = 50) -> list[Dict[str, Any]]:
        with self.lock:
            data = self._load()
            rows = list(data["runs"].values())
            if active_only:
                rows = [r for r in rows if r.get("status") in _ACTIVE]
            rows.sort(key=lambda r: _parse_ts(r.get("updated_at")), reverse=True)
            return [self._serialize(r) for r in rows[: max(1, min(limit, 200))]]

    def _choose_store(self) -> Optional[Path]:
        env = os.environ.get("SIGNALFORGE_BACKLOG_STORE")
        if env:
            p = Path(env)
            if p.exists():
                return p
        existing = [p for p in self.store_candidates if p.exists()]
        if not existing:
            return None
        return max(existing, key=lambda p: p.stat().st_mtime_ns)

    def item_exists(self, item_key: str) -> bool:
        path = self._choose_store()
        if path is None:
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return _find_item(data, item_key) is not None

    def _sample_store(self, run: Dict[str, Any]) -> Dict[str, Any]:
        path = self._choose_store()
        if path is None:
            return {"store_path": None, "store_active": None}
        try:
            stat = path.stat()
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"store_path": str(path), "store_active": None, "store_sample_error": f"{type(exc).__name__}: {exc}"}
        item = _find_item(data, str(run.get("item_key", "")))
        if item is not None:
            subject = item
            completed, total = _extract_progress(subject)
            active = _detect_active(subject)
            material_count = _count_materials(subject)
        else:
            # A global start must not recursively count the whole multi-thousand-row store every poll.
            # Inspect only workflow/worker metadata when the direction id is unavailable.
            meta = {}
            if isinstance(data, dict):
                for key, value in data.items():
                    lk = str(key).lower()
                    if any(tok in lk for tok in ("worker", "session", "status", "running", "tracking", "autopilot")):
                        meta[key] = value
            completed, total = _extract_progress(meta)
            active = _detect_active(meta)
            material_count = None
        return {
            "store_path": str(path),
            "store_mtime_ns": stat.st_mtime_ns,
            "store_active": active,
            "material_count": material_count,
            "completed_units": completed,
            "total_units": total,
        }

    def monitor_once(self) -> None:
        max_seconds = max(300, int(os.environ.get("SIGNALFORGE_RESEARCH_RUN_MAX_SECONDS", "14400")))
        settle_seconds = max(3, int(os.environ.get("SIGNALFORGE_RESEARCH_POST_RETURN_SETTLE_SECONDS", "12")))
        now = time.time()
        with self.lock:
            data = self._load()
            changed = False
            for run in data["runs"].values():
                if run.get("status") not in _ACTIVE:
                    continue
                if run.get("process_id") != _PROCESS_ID:
                    # Preserve orphan state for begin() to resume on the next explicit call.
                    continue
                sample = self._sample_store(run)
                previous_mtime = run.get("store_mtime_ns")
                new_mtime = sample.get("store_mtime_ns")
                if new_mtime is not None and new_mtime != previous_mtime:
                    run["last_store_change_at"] = _utcnow()
                for key, value in sample.items():
                    if value is not None or key in {"store_active", "store_path"}:
                        run[key] = value
                run["updated_at"] = _utcnow()
                changed = True

                started = _parse_ts(run.get("started_at"))
                if started and now - started > max_seconds:
                    run["status"] = "TIMED_OUT"
                    run["finished_at"] = _utcnow()
                    run["error"] = "PERSISTENCE_GUARD_TIMEOUT; underlying worker may still need inspection"
                    continue

                if run.get("original_done"):
                    if run.get("store_active") is True:
                        continue
                    done_at = _parse_ts(run.get("original_done_at"))
                    last_change = _parse_ts(run.get("last_store_change_at"))
                    anchor = max(done_at, last_change)
                    if anchor and now - anchor >= settle_seconds:
                        run["status"] = "SUCCEEDED"
                        run["finished_at"] = _utcnow()
            if changed:
                self._write(data)

    def start_monitor(self) -> None:
        with self.lock:
            if self._monitor_started:
                return
            self._monitor_started = True
        def loop() -> None:
            while True:
                try:
                    self.monitor_once()
                except Exception:
                    pass
                time.sleep(5.0)
        threading.Thread(target=loop, name="signalforge-v253-run-monitor", daemon=True).start()


_REGISTRY = ResearchRunRegistry()
_REGISTRY.start_monitor()


async def _read_body(receive) -> bytes:
    chunks = []
    more = True
    while more:
        msg = await receive()
        if msg.get("type") != "http.request":
            continue
        chunks.append(msg.get("body", b""))
        more = bool(msg.get("more_body"))
    return b"".join(chunks)


def _json_response(send, payload: Any, status: int = 200):
    async def sender() -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})
    return sender()


async def _invoke_asgi(app, scope: Dict[str, Any], body: bytes) -> Tuple[int, bytes, list[Tuple[bytes, bytes]]]:
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    status = 500
    headers = []
    chunks = []
    for msg in messages:
        if msg.get("type") == "http.response.start":
            status = int(msg.get("status", 500))
            headers = list(msg.get("headers", []))
        elif msg.get("type") == "http.response.body":
            chunks.append(msg.get("body", b""))
    return status, b"".join(chunks), headers


def _safe_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8")) if body else None
    except Exception:
        text = body.decode("utf-8", errors="replace")
        return {"raw": text[:4000]}


def _copy_scope_for_background(scope: Dict[str, Any]) -> Dict[str, Any]:
    copied = dict(scope)
    headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"x-signalforge-v253-bypass"]
    headers.append((b"x-signalforge-v253-bypass", b"1"))
    copied["headers"] = headers
    copied.pop("state", None)
    return copied


def _background_call(app, scope: Dict[str, Any], body: bytes, run_id: str) -> None:
    try:
        status, response_body, _ = asyncio.run(_invoke_asgi(app, scope, body))
        parsed = _safe_json(response_body)
        if status >= 400:
            _REGISTRY.finish(
                run_id,
                status="FAILED",
                original_http_status=status,
                original_response=parsed,
                original_done=True,
                original_done_at=_utcnow(),
                error=f"ORIGINAL_START_ROUTE_HTTP_{status}",
            )
            return
        async_started = _response_says_async_started(parsed)
        changes = {
            "original_http_status": status,
            "original_response": parsed,
            "original_done": True,
            "original_done_at": _utcnow(),
            "original_async_started": async_started,
        }
        if str(scope.get("path") or "").endswith("/run"):
            material_count = parsed.get("materials_added") if isinstance(parsed, dict) else None
            _REGISTRY.finish(run_id, status="SUCCEEDED", material_count=material_count, **changes)
        else:
            _REGISTRY.update(run_id, status="RUNNING", **changes)
        if not async_started:
            # monitor still allows a short settle window so final store commit can become visible.
            pass
    except Exception as exc:
        _REGISTRY.finish(
            run_id,
            status="FAILED",
            original_done=True,
            original_done_at=_utcnow(),
            error=f"{type(exc).__name__}: {exc}",
        )


class SignalForgeResearchPersistenceMiddleware:
    """
    Detaches SignalForge research starts from the browser request lifecycle.

    It does not change ranking, relevance, market judgment, evidence contents, or Market Truth.
    The canonical research route still performs the real work. This middleware only:
      * creates a durable run id,
      * suppresses duplicate same-direction starts,
      * executes the canonical start request in a server-owned background thread,
      * persists run/progress metadata,
      * exposes lightweight run-status endpoints.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        if headers.get("x-signalforge-v253-bypass") == "1":
            await self.app(scope, receive, send)
            return

        base = "/api/signalforge/research-backlog"
        if method == "GET" and path == f"{base}/runs":
            query = (scope.get("query_string") or b"").decode("utf-8", errors="ignore")
            active_only = "active_only=1" in query or "active_only=true" in query.lower()
            payload = {
                "version": _VERSION,
                "runs": _REGISTRY.list_runs(active_only=active_only),
                "market_truth_writes": 0,
            }
            await _json_response(send, payload)  # type: ignore[misc]
            return
        if method == "GET" and path.startswith(f"{base}/runs/"):
            item_key = path.rsplit("/", 1)[-1]
            run = _REGISTRY.get_by_item(item_key)
            await _json_response(send, {"version": _VERSION, "run": run, "market_truth_writes": 0}, 200 if run else 404)  # type: ignore[misc]
            return

        single_prefix = f"{base}/"
        is_single_run = method == "POST" and path.startswith(single_prefix) and path.endswith("/run")
        if method == "POST" and (path == f"{base}/start" or is_single_run):
            body = await _read_body(receive)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                payload = {"_raw_sha256": hashlib.sha256(body).hexdigest()}
            item_key = unquote(path[len(single_prefix):-len("/run")]).strip("/") if is_single_run else (
                _find_id(payload) or ("payload-" + _stable_hash(payload)[:16] if payload else "__global__")
            )
            if is_single_run and (not item_key or "/" in item_key or not _REGISTRY.item_exists(item_key)):
                await _json_response(send, {"detail": f"research backlog item {item_key!r} not found", "market_truth_writes": 0}, 404)  # type: ignore[misc]
                return
            query = (scope.get("query_string") or b"").decode("utf-8", errors="ignore")
            force = (
                headers.get("x-signalforge-force-research") == "1"
                or "force=1" in query
                or "force=true" in query.lower()
            )
            request_meta = {"path": path, "method": method, "query": query}
            if force:
                request_meta["force_nonce"] = uuid.uuid4().hex
            run, should_start, reason = _REGISTRY.begin(item_key, payload, request_meta)
            if should_start:
                bg_scope = _copy_scope_for_background(scope)
                threading.Thread(
                    target=_background_call,
                    args=(self.app, bg_scope, body, run["run_id"]),
                    name=f"signalforge-v253-{run['run_id'][:8]}",
                    daemon=True,
                ).start()
            response = {
                "status": "STARTED" if run.get("status") in _ACTIVE else run.get("status"),
                "research_run_status": run.get("status"),
                "started": bool(should_start),
                "worker_started": bool(should_start),
                "worker_running": run.get("status") in _ACTIVE,
                "running": run.get("status") in _ACTIVE,
                "accepted": True,
                "run_id": run.get("run_id"),
                "item_id": None if item_key.startswith("payload-") or item_key == "__global__" else item_key,
                "item_key": item_key,
                "reason": reason,
                "duplicate_start_suppressed": run.get("duplicate_start_suppressed", 0),
                "research_continues_without_browser": True,
                "status_url": f"{base}/runs/{item_key}",
                "market_truth_writes": 0,
            }
            await _json_response(send, response, 202)  # type: ignore[misc]
            return

        await self.app(scope, receive, send)


__all__ = ["SignalForgeResearchPersistenceMiddleware", "ResearchRunRegistry", "_REGISTRY"]
