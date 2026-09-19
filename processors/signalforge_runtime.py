"""SignalForge operating loop V2 — wake catch-up + cross-process lease.

The Founder may have uvicorn, the scheduler and a manual CLI open at the same
 time. M13 used only an asyncio.Lock, which is process-local and could leave the
 runtime status showing RUNNING while a second process executed a cycle.

M14 uses one small atomic lease file so only one real Radar cycle may own the
 Company Truth mutation path at a time. Manual CLI cycles also pass through this
 runtime so last_success_at/freshness reflect what actually happened.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from processors.research_orchestrator import run_research_cycle, print_research_cycle
from processors.founder_daily_surface import build_founder_daily_surface
from processors.historical_replay import capture_forward_policy_snapshot
from processors import signalforge_runtime_progress as runtime_progress
from processors.signalforge_atomic_io import atomic_write_json, append_jsonl_best_effort

ENGINE_VERSION = "signalforge-runtime-v12-r9-postproduction-durability"
STATE_PATH = Path(".radar_runtime/signalforge_runtime.json")
LEASE_PATH = Path(".radar_runtime/signalforge_runtime.lock")
UPGRADE_GUARD_PATH = Path(".radar_runtime/signalforge_upgrade_guard.json")
DISPATCH_PATH = Path(".radar_runtime/signalforge_runtime_dispatch.json")
WORKER_LOG_PATH = Path(".radar_runtime/signalforge_runtime_worker.log")
RUNTIME_IO_ERROR_PATH = Path(".radar_runtime/signalforge_runtime_io_errors.jsonl")
WORKER_SCRIPT = Path(__file__).resolve().parents[1] / "run_signalforge_runtime_worker.py"
STALE_HOURS = max(0.5, float(os.getenv("SIGNALFORGE_STALE_HOURS", "2") or 2))
LEASE_STALE_HOURS = max(2.0, float(os.getenv("SIGNALFORGE_LEASE_STALE_HOURS", "4") or 4))
MANUAL_AUTO_LEASE_WAIT_SECONDS = max(0.0, float(os.getenv("SIGNALFORGE_MANUAL_AUTO_LEASE_WAIT_SECONDS", "30") or 30))

_lock = asyncio.Lock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _record_runtime_io_error(*, operation: str, exc: Exception) -> None:
    append_jsonl_best_effort(
        RUNTIME_IO_ERROR_PATH,
        {
            "engine_version": ENGINE_VERSION,
            "recorded_at": _utcnow().isoformat(),
            "pid": os.getpid(),
            "operation": operation,
            "error": f"{type(exc).__name__}: {exc}",
            "truth_boundary": "RUNTIME_STATE_IO_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        },
    )


def _save(state: dict[str, Any]) -> None:
    try:
        atomic_write_json(STATE_PATH, state)
    except Exception as exc:
        _record_runtime_io_error(operation="runtime_state", exc=exc)
        raise


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False

    # os.kill(pid, 0) is the normal POSIX existence probe, but Windows maps
    # os.kill onto process/control-event semantics. Use a read-only Win32
    # process handle there so lease health can never terminate or signal the
    # owner process by accident.
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_query_limited_information = 0x1000
            still_active = 259
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _lease_info() -> dict[str, Any] | None:
    if not LEASE_PATH.exists():
        return None
    try:
        data = json.loads(LEASE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _lease_is_stale(info: dict[str, Any] | None) -> bool:
    if not info:
        return True
    started = _parse(info.get("started_at"))
    if started is None:
        return True
    age = (_utcnow() - started).total_seconds() / 3600.0
    if age >= LEASE_STALE_HOURS:
        return True
    pid = int(info.get("pid") or 0)
    return not _pid_alive(pid)


def _acquire_lease(reason: str) -> tuple[bool, dict[str, Any]]:
    LEASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine_version": ENGINE_VERSION,
        "pid": os.getpid(),
        "started_at": _utcnow().isoformat(),
        "reason": reason,
    }
    for _ in range(2):
        try:
            with LEASE_PATH.open("x", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            return True, payload
        except FileExistsError:
            current = _lease_info()
            if _lease_is_stale(current):
                try:
                    LEASE_PATH.unlink()
                except FileNotFoundError:
                    pass
                continue
            return False, current or {}
    return False, _lease_info() or {}


def _release_lease() -> None:
    info = _lease_info()
    if not info:
        return
    if int(info.get("pid") or 0) != os.getpid():
        return
    try:
        LEASE_PATH.unlink()
    except FileNotFoundError:
        pass




def _upgrade_guard_info() -> dict[str, Any] | None:
    if not UPGRADE_GUARD_PATH.exists():
        return None
    try:
        data = json.loads(UPGRADE_GUARD_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        expires = _parse(data.get("expires_at"))
        if expires is not None and expires <= _utcnow():
            try:
                UPGRADE_GUARD_PATH.unlink()
            except FileNotFoundError:
                pass
            return None
        return data
    except Exception:
        return None


def _clear_upgrade_guard() -> None:
    try:
        UPGRADE_GUARD_PATH.unlink()
    except FileNotFoundError:
        pass


def _dispatch_info() -> dict[str, Any] | None:
    if not DISPATCH_PATH.exists():
        return None
    try:
        data = json.loads(DISPATCH_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_dispatch(data: dict[str, Any]) -> None:
    try:
        atomic_write_json(DISPATCH_PATH, data)
    except Exception as exc:
        _record_runtime_io_error(operation="dispatch_state", exc=exc)
        raise


def _dispatch_state() -> dict[str, Any] | None:
    data = _dispatch_info()
    if not data:
        return None
    out = dict(data)
    pid = int(out.get("pid") or 0)
    worker_alive = _pid_alive(pid)
    out["worker_alive"] = worker_alive
    launched = _parse(out.get("launched_at"))
    out["age_seconds"] = (
        round(max(0.0, (_utcnow() - launched).total_seconds()), 1)
        if launched is not None else None
    )

    # R4: the first real R3 live cycle exposed a benign parent/child receipt
    # race where the parent could persist DISPATCHED after the child had already
    # written WORKER_STARTED. Derive an effective execution state from the
    # authoritative worker PID + canonical runtime lease/progress so the Founder
    # surface cannot stay stuck at DISPATCHED while the worker is demonstrably
    # running. This is observability only; no truth or scheduling authority.
    persisted_status = str(out.get("status") or "")
    out["persisted_status"] = persisted_status
    lease = _lease_info()
    lease_active = bool(lease and not _lease_is_stale(lease))
    lease_pid = int((lease or {}).get("pid") or 0)
    progress = runtime_progress.get_progress()
    progress_pid = int(progress.get("pid") or 0)
    progress_status = str(progress.get("status") or "").upper()

    if worker_alive and (
        (lease_active and lease_pid == pid)
        or (progress_status == "RUNNING" and progress_pid == pid)
    ):
        out["status"] = "WORKER_RUNNING"
        out["effective_status_reason"] = "LIVE_WORKER_OWNS_RUNTIME"
    elif worker_alive and progress_status in {"PASS", "FAIL"} and progress_pid == pid:
        out["status"] = "WORKER_FINISHING"
        out["effective_status_reason"] = "WORKER_ALIVE_AFTER_RUNTIME_FINISH"
    else:
        out["effective_status_reason"] = "PERSISTED_RECEIPT"
    return out


def launch_signalforge_cycle_nonblocking(
    *,
    force: bool = False,
    reason: str = "scheduled",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Dispatch one SignalForge cycle in a separate Python process.

    This function is intentionally synchronous and fast. It must never execute
    the CPU/network-heavy research cycle on the FastAPI/AsyncIOScheduler event
    loop. Cross-process mutation authority remains owned by the existing lease
    inside ``run_signalforge_if_stale``.
    """
    before = get_signalforge_runtime_status()
    if before.get("running"):
        return {
            "status": "BUSY_CROSS_PROCESS",
            "accepted": False,
            "owner": before.get("lease"),
            "dispatch": _dispatch_state(),
        }

    existing = _dispatch_state()
    if existing and existing.get("worker_alive"):
        return {
            "status": "ALREADY_DISPATCHED",
            "accepted": False,
            "dispatch": existing,
        }

    if not WORKER_SCRIPT.is_file():
        return {
            "status": "DISPATCH_FAIL",
            "accepted": False,
            "error": f"worker script missing: {WORKER_SCRIPT}",
        }

    WORKER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    dispatch_id = f"sfdisp_{uuid.uuid4().hex[:16]}"
    cmd = [
        sys.executable,
        str(WORKER_SCRIPT),
        "--reason", str(reason),
        "--dispatch-id", dispatch_id,
    ]
    if force:
        cmd.append("--force")
    if force_refresh:
        cmd.append("--force-refresh")

    creationflags = 0
    if os.name == "nt":
        # Keep the worker independent of the API request lifetime while avoiding
        # an extra console window. The worker still writes its own durable log.
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    launched_at = _utcnow().isoformat()
    launch_receipt = {
        "engine_version": ENGINE_VERSION,
        "dispatch_id": dispatch_id,
        "status": "LAUNCHING",
        "accepted": True,
        "pid": None,
        "launched_at": launched_at,
        "reason": reason,
        "force": bool(force),
        "force_refresh": bool(force_refresh),
        "worker_script": str(WORKER_SCRIPT),
        "worker_log": str(WORKER_LOG_PATH),
        "truth_boundary": "PROCESS_DISPATCH_ONLY_NO_MARKET_TRUTH_AUTHORITY",
    }
    _save_dispatch(launch_receipt)
    try:
        with WORKER_LOG_PATH.open("a", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd,
                cwd=str(WORKER_SCRIPT.parent),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=(os.name != "nt"),
                creationflags=creationflags,
            )
    except Exception as exc:
        payload = {
            **launch_receipt,
            "status": "DISPATCH_FAIL",
            "accepted": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _save_dispatch(payload)
        return payload

    # The child may start before Popen returns. Merge rather than overwrite so a
    # fast WORKER_STARTED/WORKER_FINISHED update cannot be lost.
    current = _dispatch_info() or {}
    child_status = str(current.get("status") or "") if current.get("dispatch_id") == dispatch_id else ""
    payload = {
        **launch_receipt,
        **(current if current.get("dispatch_id") == dispatch_id else {}),
        "status": child_status if child_status.startswith("WORKER_") else "DISPATCHED",
        "accepted": True,
        "pid": int(proc.pid),
        "error": current.get("error") if child_status.startswith("WORKER_") else None,
    }
    _save_dispatch(payload)
    return payload


def record_worker_dispatch_state(
    *,
    status: str,
    error: str | None = None,
    dispatch_id: str | None = None,
) -> bool:
    """Best-effort child receipt update; it never owns production truth."""
    try:
        data = _dispatch_info() or {}
        if dispatch_id and data.get("dispatch_id") not in {None, dispatch_id}:
            return False
        if int(data.get("pid") or 0) not in {0, os.getpid()}:
            return False
        data.update({
            "engine_version": ENGINE_VERSION,
            "dispatch_id": dispatch_id or data.get("dispatch_id"),
            "pid": os.getpid(),
            "status": str(status),
            "worker_updated_at": _utcnow().isoformat(),
            "error": error,
            "truth_boundary": "PROCESS_DISPATCH_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        })
        _save_dispatch(data)
        return True
    except Exception as exc:
        _record_runtime_io_error(operation="worker_dispatch_receipt", exc=exc)
        return False


def _is_manual_reason(reason: str) -> bool:
    return str(reason or "").startswith("manual_")


async def _wait_for_auto_owner() -> None:
    if MANUAL_AUTO_LEASE_WAIT_SECONDS <= 0:
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MANUAL_AUTO_LEASE_WAIT_SECONDS
    while loop.time() < deadline:
        info = _lease_info()
        if not info or _lease_is_stale(info):
            return
        reason = str(info.get("reason") or "")
        if reason not in {"startup_catchup", "scheduler_or_wake", "scheduled"}:
            return
        await asyncio.sleep(0.5)


def get_signalforge_runtime_status() -> dict[str, Any]:
    state = _load()
    now = _utcnow()
    last = _parse(state.get("last_success_at"))
    age_hours = None if last is None else max(0.0, (now - last).total_seconds() / 3600)
    fresh = age_hours is not None and age_hours < STALE_HOURS
    lease = _lease_info()
    lease_active = bool(lease and not _lease_is_stale(lease))
    upgrade_guard = _upgrade_guard_info()
    raw_status = state.get("status", "NEVER_RUN")
    effective_status = "INTERRUPTED" if raw_status == "RUNNING" and not lease_active else raw_status
    progress = runtime_progress.get_progress()
    return {
        "engine_version": ENGINE_VERSION,
        "status": effective_status,
        "state_status": raw_status,
        "running": lease_active,
        "lease": lease if lease_active else None,
        "upgrade_guard": upgrade_guard,
        "last_started_at": state.get("last_started_at"),
        "last_success_at": state.get("last_success_at"),
        "last_finished_at": state.get("last_finished_at"),
        "last_reason": state.get("last_reason"),
        "last_error": state.get("last_error"),
        "last_attempt_started_at": state.get("last_attempt_started_at"),
        "last_attempt_finished_at": state.get("last_attempt_finished_at"),
        "last_attempt_status": state.get("last_attempt_status"),
        "last_attempt_error": state.get("last_attempt_error"),
        "last_attempt_cycle": state.get("last_attempt_cycle") or {},
        "data_age_hours": round(age_hours, 3) if age_hours is not None else None,
        "stale_after_hours": STALE_HOURS,
        "fresh": fresh,
        "next_due_at": (
            (last + timedelta(hours=STALE_HOURS)).isoformat()
            if last is not None else now.isoformat()
        ),
        "last_cycle": state.get("last_cycle") or {},
        "progress": runtime_progress.get_progress(),
        "observability_health": progress.get("observability_health") or "UNKNOWN",
        "last_telemetry_error": progress.get("last_telemetry_error"),
        "dispatch": _dispatch_state(),
    }


async def _refresh_brain_for_founder_surface(*, reason: str) -> dict[str, Any]:
    """Refresh derived Brain before Founder publication without owning Radar truth."""
    runtime_progress.update(
        "brain_v2_derived_refresh",
        detail="refreshing strategic portfolio before Founder publication",
        progress={"current": 0, "total": 1, "unit": "derived_refresh"},
        complete_previous=True,
    )
    try:
        from processors.signalforge_brain_v2_engine import (
            build_brain_v2_research_advisory,
            refresh_signalforge_brain_v2,
        )
        from processors.signalforge_brain_v2_runtime import mark_brain_v2_run_finished, mark_brain_v2_run_started
        mark_brain_v2_run_started(reason=f"{reason}:pre_founder_surface")
        try:
            result = await asyncio.wait_for(
                refresh_signalforge_brain_v2(),
                timeout=max(5.0, float(os.getenv("SIGNALFORGE_BRAIN_SURFACE_REFRESH_TIMEOUT_SECONDS", "20") or 20)),
            )
            mark_brain_v2_run_finished(result=result)
            advisory: dict[str, Any]
            advisory_error: str | None = None
            try:
                advisory = build_brain_v2_research_advisory(result, limit=24)
            except Exception as advisory_exc:
                advisory_error = f"{type(advisory_exc).__name__}: {advisory_exc}"
                advisory = {
                    "status": "BRAIN_ADVISORY_BUILD_FAILED_NON_BLOCKING",
                    "candidate_ids": [],
                    "deferred_candidate_ids": [],
                    "items": [],
                    "deferred_items": [],
                    "candidate_actions": {},
                    "error": advisory_error,
                    "authority": "NONE",
                }
            runtime_progress.update(
                "brain_v2_derived_refresh",
                detail="strategic portfolio refreshed",
                progress={"current": 1, "total": 1, "unit": "derived_refresh"},
                complete_previous=False,
            )
            return {
                "status": result.get("status"),
                "refresh_skipped": bool(result.get("refresh_skipped")),
                "refreshed_at": result.get("refreshed_at"),
                "elapsed_ms": result.get("elapsed_ms"),
                "counts": result.get("counts") or {},
                "strategic_summary": result.get("strategic_summary") or {},
                "advisory": advisory,
                "advisory_source": "SAME_REFRESH_SNAPSHOT",
                "advisory_error": advisory_error,
                "truth_boundary": "DERIVED_BRAIN_REFRESH_CANNOT_MUTATE_OR_ROLL_BACK_RADAR_ATOMIC_TRUTH",
            }
        except Exception as exc:
            mark_brain_v2_run_finished(error=exc)
            raise
    except Exception as exc:
        runtime_progress.update(
            "brain_v2_derived_refresh",
            detail="derived refresh failed; Founder surface will mark Brain stale",
            progress={"current": 1, "total": 1, "unit": "derived_refresh"},
            complete_previous=False,
        )
        return {
            "status": "FAIL_DERIVED_NON_BLOCKING",
            "error": f"{type(exc).__name__}: {exc}",
            "truth_boundary": "DERIVED_BRAIN_FAILURE_HAS_ZERO_PRODUCTION_TRUTH_AUTHORITY",
        }


def _warm_cache_readiness(cycle: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize exact-derived cache warmth without claiming speedup or truth."""
    phase_value = cycle.get("phase_value") if isinstance(cycle.get("phase_value"), Mapping) else {}
    c02 = (phase_value.get("c02_recurrence") or {}) if isinstance(phase_value, Mapping) else {}
    c02_cache = c02.get("retrieval_cache") if isinstance(c02, Mapping) and isinstance(c02.get("retrieval_cache"), Mapping) else {}
    profile = cycle.get("cycle_profile") if isinstance(cycle.get("cycle_profile"), Mapping) else {}
    shared = profile.get("retrieval_cache") if isinstance(profile.get("retrieval_cache"), Mapping) else {}
    c02_hit = bool(c02_cache.get("hit"))
    shared_hits = int(shared.get("hits", 0) or 0)
    shared_misses = int(shared.get("misses", 0) or 0)
    shared_writes = int(shared.get("writes", 0) or 0)
    if c02_hit or shared_hits > 0:
        status = "WARM_HITS_CONFIRMED"
    elif bool(c02_cache) or shared_misses > 0 or shared_writes > 0:
        status = "COLD_PRIMED_NO_HITS_YET"
    else:
        status = "NO_CACHE_ACTIVITY"
    return {
        "status": status,
        "c02_exact_matrix_hit": c02_hit,
        "shared_exact_retrieval_hits": shared_hits,
        "shared_exact_retrieval_misses": shared_misses,
        "shared_exact_retrieval_writes": shared_writes,
        "performance_claimed": False,
        "truth_boundary": "CACHE_WARMTH_IS_PERFORMANCE_TELEMETRY_ONLY_NO_C01_C14_OR_MARKET_TRUTH_AUTHORITY",
    }


def _safe_warm_cache_readiness(cycle: Mapping[str, Any]) -> dict[str, Any]:
    """Keep performance telemetry outside production-cycle authority.

    R8 live acceptance reached the post-production Brain refresh and then failed
    because this observability-only projection referenced a missing runtime
    symbol.  A telemetry projection is not allowed to turn a completed research
    cycle into production FAIL.  The direct helper remains strict/testable; this
    boundary converts only telemetry-projection failures into explicit degraded
    diagnostics.
    """
    try:
        return _warm_cache_readiness(cycle)
    except Exception as exc:
        return {
            "status": "DEGRADED_OBSERVABILITY_NON_BLOCKING",
            "error": f"{type(exc).__name__}: {exc}",
            "performance_claimed": False,
            "production_impact": "NONE",
            "truth_boundary": "CACHE_TELEMETRY_FAILURE_CANNOT_FAIL_PRODUCTION_OR_WRITE_C01_C14_MARKET_TRUTH",
        }


def _attempt_cycle_projection(
    cycle: Mapping[str, Any] | None,
    *,
    brain_refresh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Durable attempt diagnostics; never substitutes for last-success truth."""
    src = cycle if isinstance(cycle, Mapping) else {}
    brain = brain_refresh if isinstance(brain_refresh, Mapping) else {}
    return {
        "phase_seconds": src.get("phase_seconds") or {},
        "phase_value": src.get("phase_value") or {},
        "cycle_profile": src.get("cycle_profile") or {},
        "production_admission": src.get("production_admission") or {},
        "execution_workload": src.get("execution_workload") or {},
        "execution_governor": src.get("execution_governor") or {},
        "operating_queue": src.get("operating_queue") or {},
        "brain_refresh": brain,
        "post_brain_routing": src.get("post_brain_routing") or {},
        "strategic_routing_coherence": src.get("strategic_routing_coherence") or {},
        "warm_cache_readiness": src.get("warm_cache_readiness") or {},
        "final_reality_mode": str((src.get("final") or {}).get("reality_mode") or "") if isinstance(src.get("final"), Mapping) else "",
        "truth_boundary": "ATTEMPT_DIAGNOSTICS_ONLY_LAST_SUCCESS_AND_ATOMIC_MARKET_TRUTH_REMAIN_SEPARATE",
    }


async def _run_owned_cycle(
    *,
    reason: str,
    print_output: bool,
    force_refresh: bool = False,
) -> dict[str, Any]:
    acquired, lease = _acquire_lease(reason)
    if not acquired:
        return {
            **get_signalforge_runtime_status(),
            "skipped": True,
            "skip_reason": "BUSY_CROSS_PROCESS",
            "owner": lease,
        }

    runtime_progress.begin_cycle(reason=reason)
    # Re-assert worker start only after the canonical lease is owned. This
    # closes the R3 launch-receipt race without changing lease authority.
    record_worker_dispatch_state(status="WORKER_STARTED")
    state = _load()
    attempt_started = _utcnow().isoformat()
    state.update({
        "engine_version": ENGINE_VERSION,
        "status": "RUNNING",
        "running": True,
        "last_started_at": attempt_started,
        "last_reason": reason,
        "last_error": None,
        "last_attempt_started_at": attempt_started,
        "last_attempt_finished_at": None,
        "last_attempt_status": "RUNNING",
        "last_attempt_error": None,
        "last_attempt_cycle": {
            "reason": reason,
            "started_at": attempt_started,
            "truth_boundary": "ATTEMPT_TELEMETRY_ONLY_LAST_SUCCESS_REMAINS_SEPARATE",
        },
    })
    _save(state)

    cycle: dict[str, Any] = {}
    brain_refresh: dict[str, Any] = {}

    try:
        # Independent process-liveness heartbeat. It does not report semantic
        # progress and cannot mutate truth; it only proves the isolated worker
        # remains alive while a blocking/CPU/network substep is quiet.
        with runtime_progress.watchdog(interval_seconds=10.0):
            if print_output:
                cycle = await print_research_cycle(
                    rounds=1,
                    force_refresh=force_refresh,
                )
            else:
                cycle = await run_research_cycle(
                    rounds=1,
                    force_refresh=force_refresh,
                )
        brain_refresh = await _refresh_brain_for_founder_surface(reason=reason)
        # Re-route the Founder operating loop against the post-cycle Brain. R5
        # published a daily snapshot using the Brain advisory captured before
        # source/discovery mutations, so new strategic MARKET_ACTION /
        # FOUNDER_DISCOVERY recommendations could remain invisible until the
        # next production cycle. R6 refreshes routing only; claim truth is untouched.
        try:
            from processors.signalforge_brain_v2_integration import safe_brain_research_advisory
            from processors.signalforge_execution_governor import (
                annotate_execution_routes,
                operating_queue,
                strategic_routing_coherence,
            )
            same_refresh = brain_refresh.get("advisory") if isinstance(brain_refresh.get("advisory"), Mapping) else None
            brain_refresh_status = str(brain_refresh.get("status") or "").upper()
            if same_refresh and brain_refresh_status in {"PASS", "PASS_EMPTY"} and str(same_refresh.get("status") or "").upper() not in {
                "BRAIN_ADVISORY_BUILD_FAILED_NON_BLOCKING",
                "BRAIN_ADVISORY_UNAVAILABLE_NON_BLOCKING",
            }:
                latest_brain_advisory = dict(same_refresh)
                advisory_source = "SAME_REFRESH_SNAPSHOT"
            else:
                latest_brain_advisory = safe_brain_research_advisory(limit=24)
                advisory_source = "PERSISTED_FALLBACK"
            final_decision = dict(cycle.get("final") or {})
            rerouted_rows, rerouted_governor = annotate_execution_routes(
                list(final_decision.get("rows", []) or []),
                brain_advisory=latest_brain_advisory,
                corpus_changed=False,
                machine_limit=int((cycle.get("production_admission") or {}).get("bounded_active_workload_limit", 24) or 24),
            )
            coherence = strategic_routing_coherence(
                rerouted_rows,
                brain_advisory=latest_brain_advisory,
            )
            final_decision["rows"] = rerouted_rows
            final_decision["top"] = rerouted_rows[: len(final_decision.get("top", []) or []) or 50]
            final_decision["execution_governor"] = rerouted_governor
            final_decision["operating_queue"] = operating_queue(rerouted_rows, limit=100)
            final_decision["strategic_routing_coherence"] = coherence
            cycle["final"] = final_decision
            cycle["execution_governor"] = rerouted_governor
            cycle["operating_queue"] = final_decision["operating_queue"]
            cycle["strategic_routing_coherence"] = coherence
            cycle["post_brain_routing"] = {
                "brain_advisory_status": latest_brain_advisory.get("status"),
                "brain_advisory_source": advisory_source,
                "brain_advisory_error": latest_brain_advisory.get("error") or brain_refresh.get("advisory_error"),
                "brain_candidate_count": len(latest_brain_advisory.get("candidate_ids") or []),
                "brain_candidate_action_count": len(latest_brain_advisory.get("candidate_actions") or {}),
                "route_counts": rerouted_governor.get("route_counts") or {},
                "strategic_routing_coherence": coherence,
                "truth_boundary": "POST_BRAIN_ROUTING_CHANGES_WORK_ONLY_NO_C01_C14_AUTHORITY",
            }
        except Exception as route_exc:
            cycle["post_brain_routing"] = {
                "status": "FAIL_NON_BLOCKING",
                "error": f"{type(route_exc).__name__}: {route_exc}",
                "truth_boundary": "ROUTING_REFRESH_FAILURE_CANNOT_MUTATE_RADAR_TRUTH",
            }
        cycle["warm_cache_readiness"] = _safe_warm_cache_readiness(cycle)
        runtime_progress.update(
            "founder_daily_surface",
            detail="building canonical Founder daily surface from post-cycle Brain",
            progress={
                "active_cases": int((cycle.get("production_admission") or {}).get("active_machine_research", 0) or 0),
                "changes": len(cycle.get("changes", []) or []),
            },
        )
        daily = await build_founder_daily_surface(
            limit=10,
            save_snapshot=True,
            decision=cycle.get("final") or None,
        )
        runtime_progress.update(
            "forward_policy_snapshot",
            detail="recording pre-outcome decision snapshot",
            progress={"founder_cards": len(daily.get("cards", []) or [])},
        )
        forward_policy = await capture_forward_policy_snapshot(
            decision=cycle.get("final") or None,
            source=reason,
        )
        finished = _utcnow()
        state.update({
            "status": "PASS",
            "running": False,
            "last_success_at": finished.isoformat(),
            "last_finished_at": finished.isoformat(),
            "last_attempt_finished_at": finished.isoformat(),
            "last_attempt_status": "PASS",
            "last_attempt_error": None,
            "last_attempt_cycle": {
                "reason": reason,
                "started_at": state.get("last_attempt_started_at"),
                "finished_at": finished.isoformat(),
                "status": "PASS",
                **_attempt_cycle_projection(cycle, brain_refresh=brain_refresh),
                "observability_health": runtime_progress.get_progress().get("observability_health"),
                "truth_boundary": "ATTEMPT_TELEMETRY_ONLY_LAST_SUCCESS_REMAINS_SEPARATE",
            },
            "last_cycle": {
                "changes": len(cycle.get("changes", []) or []),
                "llm_calls": int(cycle.get("llm_calls", 0) or 0),
                "llm_cost_twd": float(cycle.get("llm_cost_twd", 0) or 0),
                "quality_before": (cycle.get("quality_before") or {}).get("status"),
                "quality_after": (cycle.get("quality_after") or {}).get("status"),
                "founder_cards": len(daily.get("cards", []) or []),
                "validation_boundary": daily.get("validation_boundary") or {},
                "source_health": cycle.get("source_health") or {},
                "phase_seconds": cycle.get("phase_seconds") or {},
                "phase_value": cycle.get("phase_value") or {},
                "cycle_profile": cycle.get("cycle_profile") or {},
                "production_admission": cycle.get("production_admission") or {},
                "execution_workload": cycle.get("execution_workload") or {},
                "execution_governor": cycle.get("execution_governor") or {},
                "operating_queue": cycle.get("operating_queue") or {},
                "brain_refresh": brain_refresh,
                "post_brain_routing": cycle.get("post_brain_routing") or {},
                "strategic_routing_coherence": cycle.get("strategic_routing_coherence") or {},
                "warm_cache_readiness": cycle.get("warm_cache_readiness") or {},
                "recurrence": {
                    "supported": int((cycle.get("recurrence") or {}).get("c02_supported", 0) or 0),
                    "coverage_gap": int((cycle.get("recurrence") or {}).get("coverage_gap_actions", 0) or 0),
                },
                "materiality": {
                    "material_documents": int((cycle.get("materiality") or {}).get("material_documents", 0) or 0),
                    "support_links_created": int((cycle.get("materiality") or {}).get("support_links_created", 0) or 0),
                    "cases_supported_after": int((cycle.get("materiality") or {}).get("cases_supported_after", 0) or 0),
                },
                "solution_gap": {
                    "ai_calls": int((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("ai_calls", 0)) or 0),
                    "same_problem": int((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("same_problem", 0)) or 0),
                    "support_links": int((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("support_links", 0)) or 0),
                    "c07_same_cycle_evaluated": int((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("c07_same_cycle_evaluated", 0)) or 0),
                    "c07_same_cycle_supported": int((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("c07_same_cycle_supported", 0)) or 0),
                    "allocation_version": str((((cycle.get("rounds") or [{}])[0].get("solution_gap") or {}).get("allocation_version", "")) or ""),
                },
                "final_reality_mode": str((cycle.get("final") or {}).get("reality_mode") or ""),
                "problem_discovery": {
                    "status": (cycle.get("problem_discovery") or {}).get("status"),
                    "reason": (cycle.get("problem_discovery") or {}).get("reason"),
                    "new_candidates": int((cycle.get("problem_discovery") or {}).get("new_candidates", 0) or 0),
                    "new_cases": int((cycle.get("problem_discovery") or {}).get("new_cases", 0) or 0),
                    "candidates_deferred_before_radar": int((cycle.get("problem_discovery") or {}).get("candidates_deferred_before_radar", 0) or 0),
                    "pre_enrichment_deferred": int((cycle.get("problem_discovery") or {}).get("pre_enrichment_deferred", 0) or 0),
                    "pre_enrichment_deferred_reasons": (cycle.get("problem_discovery") or {}).get("pre_enrichment_deferred_reasons") or {},
                    "admission_states": (cycle.get("problem_discovery") or {}).get("admission_states") or {},
                },
                "forward_policy_snapshot": {
                    "recorded_at": forward_policy.get("recorded_at"),
                    "snapshot_path": forward_policy.get("snapshot_path"),
                    "case_count": forward_policy.get("case_count", 0),
                    "decision_engine_version": forward_policy.get("decision_engine_version"),
                },
            },
        })
        _save(state)
        runtime_progress.finish(
            status="PASS",
            metrics={
                "phase_seconds": cycle.get("phase_seconds") or {},
                "phase_value": cycle.get("phase_value") or {},
                "production_admission": cycle.get("production_admission") or {},
                "execution_governor": cycle.get("execution_governor") or {},
                "brain_refresh": brain_refresh,
                "founder_cards": len(daily.get("cards", []) or []),
            },
        )
        brain_v2_launch: dict[str, Any] = {
            "status": "SYNC_REFRESH_USED",
            "result": brain_refresh,
            "production_impact": "NONE",
        }
        if str(brain_refresh.get("status") or "").upper().startswith("FAIL"):
            try:
                from processors.signalforge_brain_v2_runtime import launch_brain_v2_refresh_nonblocking
                brain_v2_launch = launch_brain_v2_refresh_nonblocking(reason=f"{reason}:fallback")
            except Exception as brain_v2_exc:
                brain_v2_launch = {
                    "status": "BRAIN_V2_DERIVED_LAUNCH_FAIL_NON_BLOCKING",
                    "production_impact": "NONE",
                    "error": f"{type(brain_v2_exc).__name__}: {brain_v2_exc}",
                }
        return {**get_signalforge_runtime_status(), "skipped": False, "cycle": cycle, "brain_v2_launch": brain_v2_launch}
    except Exception as exc:
        finished = _utcnow()
        error_text = f"{type(exc).__name__}: {exc}"
        progress_snapshot = runtime_progress.get_progress()
        state.update({
            "status": "FAIL",
            "running": False,
            "last_finished_at": finished.isoformat(),
            "last_error": error_text,
            "last_attempt_finished_at": finished.isoformat(),
            "last_attempt_status": "FAIL",
            "last_attempt_error": error_text,
            "last_attempt_cycle": {
                "reason": reason,
                "started_at": state.get("last_attempt_started_at"),
                "finished_at": finished.isoformat(),
                "status": "FAIL",
                "failed_phase": progress_snapshot.get("phase"),
                "last_completed_phase": progress_snapshot.get("last_completed_phase"),
                "progress": progress_snapshot.get("progress") or {},
                "metrics": progress_snapshot.get("metrics") or {},
                **_attempt_cycle_projection(cycle, brain_refresh=brain_refresh),
                "observability_health": progress_snapshot.get("observability_health"),
                "last_telemetry_error": progress_snapshot.get("last_telemetry_error"),
                "truth_boundary": "FAILED_ATTEMPT_DIAGNOSTICS_ONLY_LAST_SUCCESS_REMAINS_SEPARATE",
            },
        })
        _save(state)
        runtime_progress.finish(
            status="FAIL",
            error=error_text,
        )
        raise
    finally:
        _release_lease()


async def run_signalforge_if_stale(*, force: bool = False, reason: str = "scheduled") -> dict[str, Any]:
    async with _lock:
        manual = _is_manual_reason(reason)
        if manual:
            _clear_upgrade_guard()
            await _wait_for_auto_owner()
        else:
            guard = _upgrade_guard_info()
            if guard:
                before = get_signalforge_runtime_status()
                return {
                    **before,
                    "skipped": True,
                    "skip_reason": "UPGRADE_GUARD",
                    "upgrade_guard": guard,
                }
        before = get_signalforge_runtime_status()
        if not force and before.get("fresh"):
            return {**before, "skipped": True, "skip_reason": "FRESH"}
        return await _run_owned_cycle(reason=reason, print_output=False, force_refresh=False)


async def run_signalforge_manual_cycle(*, force_refresh: bool = False) -> dict[str, Any]:
    """Run the CLI cycle through the same runtime/lease and update freshness."""
    async with _lock:
        _clear_upgrade_guard()
        await _wait_for_auto_owner()
        return await _run_owned_cycle(
            reason="manual_cli",
            print_output=True,
            force_refresh=force_refresh,
        )
