"""SignalForge R4 no-DB acceptance: live telemetry completion.

R4 is intentionally Founder observability / dispatch-truth only. It closes gaps
observed during the first real R3 process-isolated cycle: persisted dispatch
could stay DISPATCHED while the worker owned the lease, heterogeneous progress
keys rendered as an empty current/total pair, and long C05/C06/C07 substeps had
no semantic heartbeat. No market-truth authority is granted here.
"""
from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Stub heavy imports before importing runtime so this suite remains no-DB.
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

from processors import signalforge_runtime_progress as progress
import processors.signalforge_runtime as runtime

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
    rt = text("processors/signalforge_runtime.py")
    pr = text("processors/signalforge_runtime_progress.py")
    worker = text("run_signalforge_runtime_worker.py")
    solution = text("processors/solution_gap_research.py")
    orch = text("processors/research_orchestrator.py")
    banner = text("dashboard/src/signalforgeFounderRuntimeClosure.ts")
    system = text("dashboard/src/pages/System.tsx")
    return {
        "dispatch_effective_state_uses_live_lease": (
            'out["status"] = "WORKER_RUNNING"' in rt
            and 'out["persisted_status"] = persisted_status' in rt
            and 'LIVE_WORKER_OWNS_RUNTIME' in rt
        ),
        "worker_reasserts_started_after_lease": (
            'runtime_progress.begin_cycle(reason=reason)' in rt
            and 'record_worker_dispatch_state(status="WORKER_STARTED")' in rt
        ),
        "dispatch_id_is_passed_to_worker": (
            '"--dispatch-id", dispatch_id' in rt
            and 'parser.add_argument("--dispatch-id"' in worker
        ),
        "watchdog_is_separate_liveness_channel": (
            "HEARTBEAT_PATH" in pr
            and "PROCESS_WATCHDOG" in pr
            and "with runtime_progress.watchdog(interval_seconds=10.0)" in rt
        ),
        "canonical_current_total_projection_exists": (
            "def _canonical_progress" in pr
            and 'out["current"]' in pr
            and 'out["total"]' in pr
            and 'out["percent"]' in pr
        ),
        "liveness_and_progress_are_separate": (
            'out["progress_age_seconds"]' in pr
            and 'out["progress_state"]' in pr
            and "PROCESS_ALIVE_NO_RECENT_PROGRESS" in pr
        ),
        "c06_c07_has_inner_case_and_ai_heartbeats": (
            'detail="c06/c07 case verification"' in solution
            and 'detail="c06/c07 AI pair adjudication"' in solution
            and 'detail="c06/c07 case complete"' in solution
        ),
        "c05_has_inner_case_and_ai_heartbeats": (
            'detail="c05 buyer case verification"' in orch
            and 'detail="c05 buyer AI adjudication"' in orch
            and 'detail="c05 buyer verification complete"' in orch
        ),
        "all_expensive_prefetch_lanes_use_bounded_active_universe": (
            "bounded = _active_workload_rows" in orch
            and "buyer_prefetch = _claim_prefetch_rows(\n            post_discovery_active_rows," in orch
            and "solution_prefetch = _claim_prefetch_rows(\n            sorted(\n                post_discovery_active_rows," in orch
            and "for row in post_discovery_active_rows" in orch
        ),
        "admission_telemetry_separates_eligible_total_from_execution_set": (
            '"active_machine_research_semantics": "ELIGIBLE_TOTAL_NOT_EXECUTION_SET"' in orch
            and '"bounded_active_workload"' in orch
            and '"bounded_active_workload_limit"' in orch
            and '"execution_workload"' in orch
            and '"all_expensive_lanes_bounded": True' in orch
        ),
        "founder_banner_renders_bounded_progress": (
            "worker alive, no semantic progress" in banner
            and "cp?.current" in banner
            and "cp?.total" in banner
        ),
        "system_ui_exposes_liveness_vs_progress": (
            'k="dispatch persisted status"' in system
            and 'k="heartbeat source"' in system
            and 'k="progress state"' in system
            and 'k="progress age seconds"' in system
        ),
        "telemetry_has_zero_market_truth_authority": (
            "RUNTIME_OBSERVABILITY_ONLY_NO_MARKET_TRUTH_AUTHORITY" in pr
            and "PROCESS_LIVENESS_ONLY_NO_MARKET_TRUTH_AUTHORITY" in pr
        ),
    }


def behavior_progress_projection() -> dict[str, bool]:
    original_path = progress.PATH
    original_hb = progress.HEARTBEAT_PATH
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            progress.PATH = root / "progress.json"
            progress.HEARTBEAT_PATH = root / "heartbeat.json"
            progress.begin_cycle(reason="r4_test", cycle_id="cycle-r4")
            progress.update(
                "c06_c07_solution_research",
                detail="case verification",
                progress={"cases_completed": 2, "cases_total": 5, "ai_calls": 1},
            )
            before = json.loads(progress.PATH.read_text(encoding="utf-8"))
            progress.watchdog_touch()
            after = json.loads(progress.PATH.read_text(encoding="utf-8"))
            out = progress.get_progress()
            cp = out.get("progress") or {}
            hb = json.loads(progress.HEARTBEAT_PATH.read_text(encoding="utf-8"))
            return {
                "cases_completed_maps_to_current_total": (
                    cp.get("current") == 2 and cp.get("total") == 5
                    and cp.get("unit") == "cases" and cp.get("percent") == 40.0
                ),
                "watchdog_does_not_overwrite_progress_document": before == after,
                "watchdog_heartbeat_is_cycle_scoped": (
                    hb.get("cycle_id") == "cycle-r4"
                    and hb.get("kind") == "PROCESS_WATCHDOG"
                ),
                "heartbeat_is_active": out.get("heartbeat_state") == "ACTIVE",
            }
    finally:
        progress.PATH = original_path
        progress.HEARTBEAT_PATH = original_hb


def behavior_effective_dispatch() -> dict[str, bool]:
    original_dispatch = runtime.DISPATCH_PATH
    original_lease = runtime.LEASE_PATH
    original_pid_alive = runtime._pid_alive
    original_progress_get = runtime.runtime_progress.get_progress
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime.DISPATCH_PATH = root / "dispatch.json"
            runtime.LEASE_PATH = root / "lease.json"
            runtime._pid_alive = lambda pid: int(pid or 0) == 424242
            runtime.runtime_progress.get_progress = lambda: {
                "status": "RUNNING", "pid": 424242
            }
            runtime.DISPATCH_PATH.write_text(json.dumps({
                "dispatch_id": "d1",
                "status": "DISPATCHED",
                "pid": 424242,
                "launched_at": runtime._utcnow().isoformat(),
            }), encoding="utf-8")
            runtime.LEASE_PATH.write_text(json.dumps({
                "pid": 424242,
                "started_at": runtime._utcnow().isoformat(),
                "reason": "manual_api",
            }), encoding="utf-8")
            out = runtime._dispatch_state() or {}
            return {
                "persisted_dispatched_is_preserved_for_diagnostics": out.get("persisted_status") == "DISPATCHED",
                "live_owner_projects_worker_running": out.get("status") == "WORKER_RUNNING",
                "effective_reason_is_explicit": out.get("effective_status_reason") == "LIVE_WORKER_OWNS_RUNTIME",
            }
    finally:
        runtime.DISPATCH_PATH = original_dispatch
        runtime.LEASE_PATH = original_lease
        runtime._pid_alive = original_pid_alive
        runtime.runtime_progress.get_progress = original_progress_get


def frozen_gate_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/signalforge_runtime_progress.py",
        "processors/signalforge_runtime.py",
        "processors/solution_gap_research.py",
        "processors/research_orchestrator.py",
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
    checks.update({f"behavior.{k}": v for k, v in behavior_progress_projection().items()})
    checks.update({f"behavior.{k}": v for k, v in behavior_effective_dispatch().items()})
    checks.update(frozen_gate_checks())
    checks.update(compile_checks())

    print("=" * 118)
    print("SIGNALFORGE R4 — LIVE TELEMETRY + DISPATCH TRUTH CLOSURE — NO-DB ACCEPTANCE")
    print("=" * 118)
    passed = 0
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL':4s}  {name}")
        passed += int(ok)
    print("-" * 118)
    print(f"TOTAL={len(checks)} PASS={passed} FAIL={len(checks)-passed}")
    print("R4 is observability-only; C01-C14 truth authority and market calibration are unchanged.")
    print("=" * 118)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
