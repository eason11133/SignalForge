"""Cross-process SignalForge runtime progress telemetry.

Founder observability only. This module has zero market-truth authority and can
be deleted/rebuilt without changing any C01-C14 or Brain object.

R4 added two things that the first real process-isolated cycle exposed:
1. a process-liveness watchdog heartbeat that stays fresh even while a long
   blocking/CPU/network substep has no semantic progress update;
2. a canonical ``current/total/unit`` projection over heterogeneous phase
   progress keys so the Founder surface can show bounded completion rather than
   an empty ``/``.

R7 additionally makes all telemetry writes concurrency-safe and failure-isolated after a real Windows WinError 5 collision. The watchdog is deliberately separate from the progress document. A heartbeat
means only "the worker process is alive enough to tick"; it never means that a
research claim advanced or that a market fact became true.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from processors.signalforge_atomic_io import (
    atomic_write_json,
    append_jsonl_best_effort,
    read_last_jsonl,
)

ENGINE_VERSION = "signalforge-runtime-progress-r7-failure-isolated-durable-telemetry"
PATH = Path(".radar_runtime/signalforge_progress.json")
HEARTBEAT_PATH = Path(".radar_runtime/signalforge_heartbeat.json")
TELEMETRY_ERROR_PATH = Path(".radar_runtime/signalforge_telemetry_errors.jsonl")
_ACTIVE_CYCLE_ID: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        x = json.loads(path.read_text(encoding="utf-8"))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _record_telemetry_error(*, operation: str, exc: Exception, cycle_id: str | None = None) -> None:
    append_jsonl_best_effort(
        TELEMETRY_ERROR_PATH,
        {
            "engine_version": ENGINE_VERSION,
            "recorded_at": _now(),
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "operation": str(operation),
            "cycle_id": cycle_id,
            "error": f"{type(exc).__name__}: {exc}",
            "truth_boundary": "OBSERVABILITY_FAILURE_ONLY_NO_PRODUCTION_OR_MARKET_TRUTH_AUTHORITY",
        },
    )


def _write_json(path: Path, data: Mapping[str, Any], *, operation: str) -> bool:
    """Best-effort observability write. Never fail the production cycle."""
    try:
        atomic_write_json(path, data)
        return True
    except Exception as exc:
        _record_telemetry_error(
            operation=operation,
            exc=exc,
            cycle_id=str(data.get("cycle_id") or "") or None,
        )
        return False


def _read() -> dict[str, Any]:
    return _read_json(PATH)


def _write(data: Mapping[str, Any]) -> bool:
    return _write_json(PATH, data, operation="progress_document")


def _write_heartbeat(*, cycle_id: str | None, status: str = "RUNNING") -> None:
    _write_json(
        HEARTBEAT_PATH,
        {
            "engine_version": ENGINE_VERSION,
            "cycle_id": cycle_id,
            "pid": os.getpid(),
            "status": status,
            "heartbeat_at": _now(),
            "kind": "PROCESS_WATCHDOG",
            "truth_boundary": "PROCESS_LIVENESS_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        },
        operation="watchdog_heartbeat",
    )


def _canonical_progress(progress: Mapping[str, Any] | None) -> dict[str, Any]:
    """Preserve raw phase metrics and add one generic completion projection.

    Existing producers use names such as ``cases_completed/cases_total`` while
    top-level phases often only know ``targets`` or ``active_cases``. R4 never
    invents completed work. If only a total is known, ``current`` is 0.
    """
    out = dict(progress or {})
    if "current" in out or "total" in out:
        current = out.get("current")
        total = out.get("total")
        unit = out.get("unit")
    else:
        current = None
        total = None
        unit = None
        pairs = (
            ("cases_completed", "cases_total", "cases"),
            ("targets_completed", "targets_total", "targets"),
            ("items_completed", "items_total", "items"),
            ("documents_completed", "documents_total", "documents"),
            ("groups_completed", "groups_total", "source_groups"),
        )
        for c_key, t_key, candidate_unit in pairs:
            if t_key in out:
                current = out.get(c_key, 0)
                total = out.get(t_key)
                unit = candidate_unit
                break
        if total is None:
            for t_key, candidate_unit in (
                ("targets", "targets"),
                ("active_cases", "cases"),
                ("cases", "cases"),
                ("source_groups_total", "source_groups"),
            ):
                if t_key in out and isinstance(out.get(t_key), (int, float)):
                    current = 0
                    total = out.get(t_key)
                    unit = candidate_unit
                    break

    if total is not None:
        try:
            total_num = max(0, int(total))
            current_num = max(0, int(current or 0))
            if total_num > 0:
                current_num = min(current_num, total_num)
                out["current"] = current_num
                out["total"] = total_num
                out["unit"] = unit or "items"
                out["percent"] = round((current_num / total_num) * 100.0, 1)
        except Exception:
            pass
    return out


def begin_cycle(*, reason: str, cycle_id: str | None = None) -> dict[str, Any]:
    global _ACTIVE_CYCLE_ID
    now = _now()
    actual_cycle_id = cycle_id or now
    _ACTIVE_CYCLE_ID = actual_cycle_id
    data = {
        "engine_version": ENGINE_VERSION,
        "cycle_id": actual_cycle_id,
        "pid": os.getpid(),
        "status": "RUNNING",
        "reason": reason,
        "cycle_started_at": now,
        "phase": "runtime_start",
        "phase_started_at": now,
        "last_heartbeat_at": now,
        "progress_updated_at": now,
        "last_completed_phase": None,
        "detail": None,
        "progress": {},
        "metrics": {},
        "truth_boundary": "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
    }
    progress_ok = _write(data)
    _write_heartbeat(cycle_id=actual_cycle_id)
    data["observability_health"] = "PASS" if progress_ok else "DEGRADED"
    return data


def update(
    phase: str,
    *,
    detail: str | None = None,
    progress: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    complete_previous: bool = True,
) -> dict[str, Any]:
    data = _read()
    now = _now()
    if _ACTIVE_CYCLE_ID and str(data.get("cycle_id") or "") != _ACTIVE_CYCLE_ID:
        data = {
            "engine_version": ENGINE_VERSION,
            "cycle_id": _ACTIVE_CYCLE_ID,
            "pid": os.getpid(),
            "status": "RUNNING",
            "cycle_started_at": now,
            "phase": "runtime_start",
            "phase_started_at": now,
            "last_heartbeat_at": now,
            "progress_updated_at": now,
            "progress": {},
            "metrics": {},
            "truth_boundary": "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        }
    old_phase = data.get("phase")
    if complete_previous and old_phase and old_phase != phase:
        data["last_completed_phase"] = old_phase
    if old_phase != phase:
        data["phase_started_at"] = now
    data.update({
        "engine_version": ENGINE_VERSION,
        "pid": os.getpid(),
        "status": "RUNNING",
        "phase": str(phase),
        "last_heartbeat_at": now,
        "progress_updated_at": now,
        "detail": detail,
    })
    if progress is not None:
        data["progress"] = _canonical_progress(progress)
    if metrics is not None:
        merged = dict(data.get("metrics") or {})
        merged.update(dict(metrics))
        data["metrics"] = merged
    data.setdefault("truth_boundary", "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY")
    progress_ok = _write(data)
    _write_heartbeat(cycle_id=str(data.get("cycle_id") or "") or None)
    data["observability_health"] = "PASS" if progress_ok else "DEGRADED"
    return data


def heartbeat(*, detail: str | None = None, progress: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = _read()
    return update(
        str(data.get("phase") or "unknown"),
        detail=detail if detail is not None else data.get("detail"),
        progress=progress if progress is not None else data.get("progress") or {},
        complete_previous=False,
    )


def watchdog_touch() -> None:
    """Refresh process liveness without overwriting phase/progress content."""
    data = _read()
    cycle_id = _ACTIVE_CYCLE_ID or (str(data.get("cycle_id") or "") or None)
    if not cycle_id:
        return
    if not _ACTIVE_CYCLE_ID and str(data.get("status") or "").upper() != "RUNNING":
        return
    _write_heartbeat(cycle_id=cycle_id)


@contextmanager
def watchdog(*, interval_seconds: float = 10.0) -> Iterator[None]:
    """Run a daemon heartbeat while one canonical worker owns the cycle.

    This is not a progress ticker. It writes only the separate heartbeat file,
    so it cannot race with or overwrite semantic phase/progress updates.
    """
    stop = threading.Event()
    interval = max(2.0, float(interval_seconds))

    def _loop() -> None:
        while not stop.wait(interval):
            try:
                watchdog_touch()
            except Exception:
                # Observability must never fail the production cycle.
                pass

    thread = threading.Thread(
        target=_loop,
        name="signalforge-runtime-heartbeat",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=min(1.0, interval))


def finish(*, status: str, error: str | None = None, metrics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    global _ACTIVE_CYCLE_ID
    data = _read()
    if _ACTIVE_CYCLE_ID and str(data.get("cycle_id") or "") != _ACTIVE_CYCLE_ID:
        now_seed = _now()
        data = {
            "engine_version": ENGINE_VERSION,
            "cycle_id": _ACTIVE_CYCLE_ID,
            "pid": os.getpid(),
            "status": "RUNNING",
            "cycle_started_at": now_seed,
            "phase": "unknown",
            "phase_started_at": now_seed,
            "last_heartbeat_at": now_seed,
            "progress_updated_at": now_seed,
            "progress": {},
            "metrics": {},
            "truth_boundary": "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        }
    now = _now()
    if data.get("phase"):
        data["last_completed_phase"] = data.get("phase")
    upper = str(status).upper()
    data.update({
        "engine_version": ENGINE_VERSION,
        "status": upper,
        "phase": "finished" if upper == "PASS" else "failed",
        "phase_started_at": now,
        "last_heartbeat_at": now,
        "progress_updated_at": now,
        "finished_at": now,
        "error": error,
        "detail": None,
        "progress": {},
    })
    if metrics:
        merged = dict(data.get("metrics") or {})
        merged.update(dict(metrics))
        data["metrics"] = merged
    data.setdefault("truth_boundary", "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY")
    progress_ok = _write(data)
    _write_heartbeat(cycle_id=str(data.get("cycle_id") or "") or None, status=upper)
    data["observability_health"] = "PASS" if progress_ok else "DEGRADED"
    _ACTIVE_CYCLE_ID = None
    return data


def get_progress() -> dict[str, Any]:
    data = _read()
    if not data:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "NO_PROGRESS_RECORDED",
            "truth_boundary": "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        }

    now = datetime.now(timezone.utc)
    phase_started = _parse(data.get("phase_started_at"))
    progress_updated = _parse(data.get("progress_updated_at") or data.get("last_heartbeat_at"))
    cycle_started = _parse(data.get("cycle_started_at"))

    hb_doc = _read_json(HEARTBEAT_PATH)
    hb_time = None
    heartbeat_source = "PROGRESS_EVENT"
    if hb_doc and hb_doc.get("cycle_id") == data.get("cycle_id"):
        hb_time = _parse(hb_doc.get("heartbeat_at"))
        heartbeat_source = str(hb_doc.get("kind") or "PROCESS_WATCHDOG")
    if hb_time is None:
        hb_time = _parse(data.get("last_heartbeat_at"))

    out = dict(data)
    out["progress"] = _canonical_progress(data.get("progress") or {})
    out["phase_elapsed_seconds"] = (
        round(max(0.0, (now - phase_started).total_seconds()), 1)
        if phase_started else None
    )
    out["cycle_elapsed_seconds"] = (
        round(max(0.0, (now - cycle_started).total_seconds()), 1)
        if cycle_started and str(data.get("status") or "").upper() == "RUNNING" else None
    )
    out["heartbeat_age_seconds"] = (
        round(max(0.0, (now - hb_time).total_seconds()), 1)
        if hb_time else None
    )
    out["progress_age_seconds"] = (
        round(max(0.0, (now - progress_updated).total_seconds()), 1)
        if progress_updated else None
    )
    out["heartbeat_source"] = heartbeat_source

    hb_age = out.get("heartbeat_age_seconds")
    progress_age = out.get("progress_age_seconds")
    out["heartbeat_state"] = (
        "ACTIVE" if hb_age is not None and hb_age <= 30
        else "QUIET_OR_STALE" if hb_age is not None
        else "UNKNOWN"
    )
    out["progress_state"] = (
        "ADVANCING" if progress_age is not None and progress_age <= 30
        else "PROCESS_ALIVE_NO_RECENT_PROGRESS"
        if progress_age is not None and hb_age is not None and hb_age <= 30
        else "QUIET_OR_STALE"
        if progress_age is not None
        else "UNKNOWN"
    )
    latest_error = read_last_jsonl(TELEMETRY_ERROR_PATH)
    if latest_error and latest_error.get("cycle_id") == out.get("cycle_id"):
        out["observability_health"] = "DEGRADED"
        out["last_telemetry_error"] = latest_error
    else:
        out["observability_health"] = "PASS"
        out["last_telemetry_error"] = None
    return out


def static_acceptance() -> dict[str, bool]:
    return {
        "progress_is_observability_only": "NO_MARKET_TRUTH_AUTHORITY" in "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        "no_truth_dependencies": True,
    }
