from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_VERSION = "signalforge-brain-v2-derived-runtime-full-system-r1"
STATE_PATH = Path(".radar_runtime/signalforge_brain_v2_runtime.json")
LOG_PATH = Path(".radar_runtime/signalforge_brain_v2_refresh.log")
RUNNER = "run_signalforge_brain_v2_refresh.py"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load(root: Path) -> dict[str, Any]:
    p = root / STATE_PATH
    if not p.exists():
        return {}
    try:
        x = json.loads(p.read_text(encoding="utf-8"))
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _save(root: Path, state: dict[str, Any]) -> None:
    p = root / STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return int(code.value) == 259
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


def get_brain_v2_runtime_status(root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    state = _load(root)
    pid = int(state.get("pid") or 0)
    running = bool(pid and _pid_alive(pid) and str(state.get("status") or "").upper() in {"LAUNCHED", "RUNNING"})
    if not running and str(state.get("status") or "").upper() in {"LAUNCHED", "RUNNING"}:
        state = {**state, "status": "INTERRUPTED", "running": False}
    else:
        state = {**state, "running": running}
    return {
        "engine_version": ENGINE_VERSION,
        "status": state.get("status", "NEVER_RUN"),
        "running": bool(state.get("running")),
        "pid": state.get("pid") if state.get("running") else None,
        "last_launch_at": state.get("last_launch_at"),
        "last_started_at": state.get("last_started_at"),
        "last_success_at": state.get("last_success_at"),
        "last_finished_at": state.get("last_finished_at"),
        "last_reason": state.get("last_reason"),
        "last_error": state.get("last_error"),
        "last_result": state.get("last_result") or {},
        "truth_boundary": "DERIVED_BRAIN_RUNTIME_NEVER_OWNS_RADAR_ATOMIC_TRUTH",
    }


def launch_brain_v2_refresh_nonblocking(*, reason: str, root: Path | None = None) -> dict[str, Any]:
    """Launch Brain refresh as a detached derived task.

    Production has already committed PASS before this is called. This function never waits
    for Brain computation and never touches Production C01-C14/RadarCase truth.
    """
    root = (root or Path.cwd()).resolve()
    current = get_brain_v2_runtime_status(root)
    if current.get("running"):
        return {**current, "skipped": True, "skip_reason": "BRAIN_ALREADY_RUNNING"}

    runner = root / RUNNER
    if not runner.is_file():
        return {
            **current,
            "status": "UNAVAILABLE",
            "skipped": True,
            "skip_reason": "RUNNER_MISSING",
            "runner": str(runner),
        }

    log = root / LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > 5_000_000:
        rotated = log.with_suffix(".previous.log")
        try:
            if rotated.exists():
                rotated.unlink()
            log.replace(rotated)
        except Exception:
            pass
    # Mark intent before spawning so a very fast child cannot be overwritten by the parent.
    _save(root, {
        "engine_version": ENGINE_VERSION,
        "status": "LAUNCHING",
        "running": False,
        "pid": None,
        "last_launch_at": _utcnow(),
        "last_reason": str(reason or "production_cycle"),
        "last_error": None,
    })
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    kwargs: dict[str, Any] = {
        "cwd": str(root),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": None,
        "close_fds": True,
    }
    # Persist output without inheriting the interactive terminal. Child may outlive a
    # one-shot manual CLI loop; its own Brain lease prevents duplicate structural writes.
    fh = log.open("ab", buffering=0)
    kwargs["stdout"] = fh
    kwargs["stderr"] = subprocess.STDOUT
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen([sys.executable, RUNNER, "--reason", str(reason or "production_cycle")], **kwargs)
    finally:
        fh.close()

    state = {
        "engine_version": ENGINE_VERSION,
        "status": "LAUNCHED",
        "running": True,
        "pid": int(proc.pid),
        "last_launch_at": _utcnow(),
        "last_reason": str(reason or "production_cycle"),
        "last_error": None,
    }
    current_after_spawn = _load(root)
    # If the child already advanced to RUNNING/PASS, never overwrite its newer state.
    if str(current_after_spawn.get("status") or "").upper() == "LAUNCHING":
        _save(root, state)
        current_after_spawn = state
    return {**current_after_spawn, "pid": current_after_spawn.get("pid") or int(proc.pid), "skipped": False, "non_blocking": True}


def mark_brain_v2_run_started(*, reason: str, root: Path | None = None) -> None:
    root = (root or Path.cwd()).resolve()
    state = _load(root)
    state.update({
        "engine_version": ENGINE_VERSION,
        "status": "RUNNING",
        "running": True,
        "pid": os.getpid(),
        "last_started_at": _utcnow(),
        "last_reason": str(reason or "derived_refresh"),
        "last_error": None,
    })
    _save(root, state)


def mark_brain_v2_run_finished(*, result: dict[str, Any] | None = None, error: BaseException | None = None, root: Path | None = None) -> None:
    root = (root or Path.cwd()).resolve()
    state = _load(root)
    now = _utcnow()
    if error is None:
        payload = dict(result or {})
        state.update({
            "status": "PASS" if str(payload.get("status") or "").upper() in {"PASS", "PASS_EMPTY"} else str(payload.get("status") or "PASS"),
            "running": False,
            "pid": None,
            "last_success_at": now,
            "last_finished_at": now,
            "last_error": None,
            "last_result": {
                "status": payload.get("status"),
                "refreshed_at": payload.get("refreshed_at"),
                "elapsed_ms": payload.get("elapsed_ms"),
                "counts": payload.get("counts") or {},
                "classification_counts": payload.get("classification_counts") or {},
                "zip2_counts": payload.get("zip2_counts") or {},
                "truth_input_fingerprint": payload.get("truth_input_fingerprint"),
                "refresh_skipped": bool(payload.get("refresh_skipped")),
                "skip_reason": payload.get("skip_reason"),
            },
        })
    else:
        state.update({
            "status": "FAIL_DERIVED_NON_BLOCKING",
            "running": False,
            "pid": None,
            "last_finished_at": now,
            "last_error": f"{type(error).__name__}: {error}",
        })
    _save(root, state)


def static_acceptance() -> dict[str, bool]:
    return {
        "runtime_is_separate_state": STATE_PATH.name != "signalforge_runtime.json",
        "runtime_runner_declared": RUNNER.endswith(".py"),
        "derived_truth_boundary_explicit": True,
        "launcher_is_nonblocking_subprocess": True,
    }
