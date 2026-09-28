"""SignalForge R3 no-DB acceptance: process-isolated runtime dispatch.

R3 closes a live product defect discovered after R2 install: POST /trigger and
GET /status could time out while a CPU/network-heavy research cycle ran in the
same FastAPI event loop. This suite proves isolation/dispatch only. It grants no
market-truth authority and freezes R2 admission plus R1 evidence gates.
"""
from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import tempfile
import time
import sys
import types
from pathlib import Path

# No-DB import harness: signalforge_runtime imports heavy production modules at
# module import time. Stub only those dependencies so the dispatch layer can be
# behavior-tested without connecting to PostgreSQL or changing truth.
def _stub_async_result(*args, **kwargs):
    async def _inner():
        return {}
    return _inner()

research_stub = types.ModuleType("processors.research_orchestrator")
research_stub.run_research_cycle = _stub_async_result
research_stub.print_research_cycle = _stub_async_result
sys.modules["processors.research_orchestrator"] = research_stub

founder_stub = types.ModuleType("processors.founder_daily_surface")
founder_stub.build_founder_daily_surface = _stub_async_result
sys.modules["processors.founder_daily_surface"] = founder_stub

replay_stub = types.ModuleType("processors.historical_replay")
replay_stub.capture_forward_policy_snapshot = _stub_async_result
sys.modules["processors.historical_replay"] = replay_stub

import processors.signalforge_runtime as runtime

ROOT = Path(__file__).resolve().parent

FROZEN_FUNCTION_HASHES = {
    ("processors/signalforge_production_admission.py", "assess_candidate_admission"):
        "5559c09a6f3f2facb19a1aa9ae1a86077da167f219510d2c59428e9271b739f5",
    ("processors/signalforge_production_admission.py", "assess_pre_enrichment_discovery"):
        "7306054e54276321c413c54b84b9c73aff8c6645d27cf1430edc1716ef47aee6",
    ("processors/problem_recurrence_multi.py", "_semantic_structural_detail"):
        "96f8e8eaf2332659b727a70722a0aa2dfa658c0f01c0637865b3d6fbd694a2c6",
    ("processors/problem_recurrence_multi.py", "_ensure_support_evidence"):
        "a157dad95f846d8b0a9e64d3a0765e50d45f2fe39393945d591811858918c467",
    ("processors/radar_ledger.py", "initial_links"):
        "4ce699ee3899267e450d3777f01d5587cf6b037ab8b285217bd93aeec74705f9",
    ("processors/radar_ledger.py", "evaluate"):
        "3cd46c70a55dd648d70be6bbd53ed977d71d4c043cf45249a4c2860ebb77ba67",
}


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def function_hash(rel: str, name: str) -> str:
    source = text(rel)
    tree = ast.parse(source)
    lines = source.splitlines(True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = "".join(lines[node.lineno - 1:node.end_lineno])
            return hashlib.sha256(segment.encode("utf-8")).hexdigest()
    raise AssertionError(f"function not found: {rel}:{name}")


def static_contracts() -> dict[str, bool]:
    route = text("api/routes/signalforge.py")
    main = text("api/main.py")
    rt = text("processors/signalforge_runtime.py")
    worker = text("run_signalforge_runtime_worker.py")
    banner = text("dashboard/src/signalforgeFounderRuntimeClosure.ts")
    system = text("dashboard/src/pages/System.tsx")
    return {
        "manual_trigger_uses_process_dispatch": (
            "launch_signalforge_cycle_nonblocking(force=True, reason='manual_api')" in route
            and "asyncio.create_task(run_signalforge_if_stale" not in route
        ),
        "trigger_is_202_accepted_surface": "@router.post('/trigger', status_code=202)" in route,
        "scheduler_dispatches_not_executes_heavy_cycle": (
            "scheduler.add_job(\n        launch_signalforge_cycle_nonblocking" in main
            and 'kwargs={"force": False, "reason": "scheduler_or_wake"}' in main
        ),
        "startup_catchup_dispatches_not_executes_heavy_cycle": (
            'launch_signalforge_cycle_nonblocking(force=False, reason="startup_catchup")' in main
            and 'await run_signalforge_if_stale(force=False, reason="startup_catchup")' not in main
        ),
        "launcher_uses_subprocess_popen": "subprocess.Popen(" in rt,
        "launcher_uses_current_venv_python": "sys.executable" in rt,
        "launcher_has_durable_worker_log": "WORKER_LOG_PATH" in rt and 'stdout=log' in rt,
        "status_exposes_dispatch_and_progress": (
            '"dispatch": _dispatch_state()' in rt
            and '"progress": runtime_progress.get_progress()' in rt
        ),
        "worker_reenters_canonical_runtime_lease": (
            "run_signalforge_if_stale" in worker
            and "run_signalforge_manual_cycle" in worker
        ),
        "dispatch_has_zero_market_truth_authority": "PROCESS_DISPATCH_ONLY_NO_MARKET_TRUTH_AUTHORITY" in rt,
        "worker_script_does_not_import_truth_writers_directly": (
            "radar_ledger" not in worker
            and "materiality_research" not in worker
            and "problem_recurrence_multi" not in worker
        ),
        "global_banner_surfaces_dispatch_before_lease": (
            "dispatchActive" in banner
            and "dispatch ${dispatchStatus.toLowerCase()}" in banner
        ),
        "system_ui_surfaces_dispatch_receipt": (
            'k="dispatch status"' in system
            and 'k="dispatch worker alive"' in system
            and 'k="dispatch pid"' in system
        ),
    }


def _behavior_dispatch_returns_without_running_cycle() -> dict[str, bool]:
    class DummyProc:
        pid = 424242

    calls: list[dict] = []
    original_popen = runtime.subprocess.Popen
    original_state = runtime.STATE_PATH
    original_lease = runtime.LEASE_PATH
    original_guard = runtime.UPGRADE_GUARD_PATH
    original_dispatch = runtime.DISPATCH_PATH
    original_log = runtime.WORKER_LOG_PATH
    original_worker = runtime.WORKER_SCRIPT
    original_pid_alive = runtime._pid_alive
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            worker = root / "run_signalforge_runtime_worker.py"
            worker.write_text("# test worker\n", encoding="utf-8")
            runtime.STATE_PATH = root / "state.json"
            runtime.LEASE_PATH = root / "lease.json"
            runtime.UPGRADE_GUARD_PATH = root / "guard.json"
            runtime.DISPATCH_PATH = root / "dispatch.json"
            runtime.WORKER_LOG_PATH = root / "worker.log"
            runtime.WORKER_SCRIPT = worker
            runtime._pid_alive = lambda pid: int(pid or 0) == 424242

            def fake_popen(cmd, **kwargs):
                calls.append({"cmd": list(cmd), "kwargs": dict(kwargs)})
                return DummyProc()

            runtime.subprocess.Popen = fake_popen
            t0 = time.perf_counter()
            result = runtime.launch_signalforge_cycle_nonblocking(
                force=True, reason="manual_api"
            )
            elapsed = time.perf_counter() - t0
            dispatch = json.loads(runtime.DISPATCH_PATH.read_text(encoding="utf-8"))
            status = runtime.get_signalforge_runtime_status()
            return {
                "dispatch_returns_under_250ms_without_cycle_execution": elapsed < 0.25,
                "dispatch_returns_accepted_and_pid": (
                    result.get("status") == "DISPATCHED"
                    and result.get("accepted") is True
                    and result.get("pid") == 424242
                ),
                "dispatch_invokes_worker_with_force_and_reason": (
                    len(calls) == 1
                    and "--force" in calls[0]["cmd"]
                    and "manual_api" in calls[0]["cmd"]
                ),
                "dispatch_receipt_is_cross_process_visible": (
                    dispatch.get("pid") == 424242
                    and (status.get("dispatch") or {}).get("worker_alive") is True
                ),
            }
    finally:
        runtime.subprocess.Popen = original_popen
        runtime.STATE_PATH = original_state
        runtime.LEASE_PATH = original_lease
        runtime.UPGRADE_GUARD_PATH = original_guard
        runtime.DISPATCH_PATH = original_dispatch
        runtime.WORKER_LOG_PATH = original_log
        runtime.WORKER_SCRIPT = original_worker
        runtime._pid_alive = original_pid_alive


def frozen_gate_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "api/main.py",
        "api/routes/signalforge.py",
        "processors/signalforge_runtime.py",
        "processors/signalforge_runtime_progress.py",
        "run_signalforge_runtime_worker.py",
    ]
    out: dict[str, bool] = {}
    for rel in files:
        try:
            py_compile.compile(str(ROOT / rel), doraise=True)
            out[f"compile.{rel}"] = True
        except Exception:
            out[f"compile.{rel}"] = False
    return out


def main() -> int:
    checks: dict[str, bool] = {}
    checks.update({f"source.{k}": v for k, v in static_contracts().items()})
    checks.update({f"behavior.{k}": v for k, v in _behavior_dispatch_returns_without_running_cycle().items()})
    checks.update(frozen_gate_checks())
    checks.update(compile_checks())

    print("=" * 118)
    print("SIGNALFORGE R3 — RUNTIME PROCESS ISOLATION + LIVE ACCEPTANCE CLOSURE — NO-DB ACCEPTANCE")
    print("=" * 118)
    passed = 0
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL':4s}  {name}")
        passed += int(ok)
    print("-" * 118)
    print(f"TOTAL={len(checks)} PASS={passed} FAIL={len(checks)-passed}")
    print("R3 changes dispatch/observability only; market calibration remains 0 / UNVALIDATED.")
    print("=" * 118)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
