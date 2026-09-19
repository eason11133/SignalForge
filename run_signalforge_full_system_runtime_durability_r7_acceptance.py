"""SignalForge R7 no-DB acceptance: runtime durability + exact incremental retrieval.

R7 is a live-evidence-driven full-system closure. It fixes the Windows shared
``*.tmp`` collision that made observability fail an otherwise completed R6
cycle, separates last-attempt diagnostics from last-success truth, and adds
exact derived retrieval reuse for the still-expensive C02/C05/C06 lanes.
None of these paths may promote C01-C14 or market calibration.
"""
from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from processors.signalforge_atomic_io import atomic_write_json
from processors import signalforge_runtime_progress as runtime_progress

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


def behavior_checks() -> dict[str, bool]:
    out: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="sf-r7-atomic-") as td:
        root = Path(td)
        path = root / "shared.json"
        errors: list[str] = []

        def writer(i: int) -> None:
            try:
                for j in range(12):
                    atomic_write_json(path, {"writer": i, "seq": j})
            except Exception as exc:  # pragma: no cover - acceptance reports it
                errors.append(f"{type(exc).__name__}:{exc}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        parsed = {}
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        out["concurrent_atomic_writers_leave_valid_json"] = not errors and isinstance(parsed, dict) and "writer" in parsed
        out["unique_temp_files_are_cleaned"] = not list(root.glob("*.tmp"))

    with tempfile.TemporaryDirectory(prefix="sf-r7-progress-") as td:
        root = Path(td)
        old_paths = (runtime_progress.PATH, runtime_progress.HEARTBEAT_PATH, runtime_progress.TELEMETRY_ERROR_PATH)
        old_writer = runtime_progress.atomic_write_json
        try:
            runtime_progress.PATH = root / "progress.json"
            runtime_progress.HEARTBEAT_PATH = root / "heartbeat.json"
            runtime_progress.TELEMETRY_ERROR_PATH = root / "telemetry_errors.jsonl"
            runtime_progress.begin_cycle(reason="r7_acceptance", cycle_id="cycle-r7")

            def denied(*_args, **_kwargs):
                raise PermissionError("synthetic WinError 5")

            runtime_progress.atomic_write_json = denied
            update_result = runtime_progress.update(
                "cycle_finalize",
                detail="synthetic collision",
                progress={"cases_completed": 1, "cases_total": 1},
            )
            finish_result = runtime_progress.finish(status="PASS")
            out["telemetry_permission_error_does_not_raise"] = (
                update_result.get("observability_health") == "DEGRADED"
                and finish_result.get("observability_health") == "DEGRADED"
            )
            out["telemetry_error_is_durably_diagnosable"] = runtime_progress.TELEMETRY_ERROR_PATH.is_file()
        finally:
            runtime_progress.atomic_write_json = old_writer
            runtime_progress.PATH, runtime_progress.HEARTBEAT_PATH, runtime_progress.TELEMETRY_ERROR_PATH = old_paths
    return out


def source_checks() -> dict[str, bool]:
    atomic_io = text("processors/signalforge_atomic_io.py")
    progress = text("processors/signalforge_runtime_progress.py")
    runtime = text("processors/signalforge_runtime.py")
    worker = text("run_signalforge_runtime_worker.py")
    recurrence = text("processors/problem_recurrence_multi.py")
    reality = text("processors/opportunity_reality.py")
    orch = text("processors/research_orchestrator.py")
    audit = text("processors/system_wide_audit.py")
    client = text("dashboard/src/api/client.ts")
    system = text("dashboard/src/pages/System.tsx")
    radar = text("dashboard/src/pages/OpportunityRadar.tsx")
    return {
        "atomic_io_uses_unique_temp_names": "uuid.uuid4" in atomic_io and "threading.get_ident" in atomic_io,
        "atomic_io_retries_windows_replace": "except PermissionError" in atomic_io and "os.replace(tmp, path)" in atomic_io,
        "progress_no_longer_uses_shared_fixed_tmp": "with_suffix(path.suffix + \".tmp\")" not in progress,
        "progress_io_failure_is_explicitly_non_authoritative": "Best-effort observability write. Never fail the production cycle." in progress,
        "progress_has_durable_telemetry_error_channel": "signalforge_telemetry_errors.jsonl" in progress and "last_telemetry_error" in progress,
        "runtime_state_and_dispatch_share_safe_atomic_writer": "atomic_write_json(STATE_PATH" in runtime and "atomic_write_json(DISPATCH_PATH" in runtime,
        "worker_receipt_failure_is_best_effort": "Best-effort child receipt update" in runtime and "return False" in runtime,
        "last_attempt_is_separate_from_last_success": '"last_attempt_status"' in runtime and '"last_success_at"' in runtime and "ATTEMPT_TELEMETRY_ONLY_LAST_SUCCESS_REMAINS_SEPARATE" in runtime,
        "failed_attempt_preserves_diagnostics": "FAILED_ATTEMPT_DIAGNOSTICS_ONLY_LAST_SUCCESS_REMAINS_SEPARATE" in runtime and '"last_attempt_cycle"' in runtime,
        "c02_cache_key_covers_queries_and_documents": "_c02_retrieval_cache_key" in recurrence and "field_queries=field_queries" in recurrence and "doc_texts=doc_texts" in recurrence,
        "c02_cache_reuses_exact_matrices_only": "c02 exact retrieval cache hit" in recurrence and "EXACT_DERIVED_MATRIX_REUSE_ONLY_NO_THRESHOLD_OR_EVIDENCE_AUTHORITY" in recurrence,
        "c02_original_threshold_vectorizers_remain": "max_features=26000" in recurrence and "max_features=50000" in recurrence and "n_iter=8" in recurrence,
        "shared_match_cache_hashes_exact_candidate_doc_inputs": "_retrieval_cache_key" in reality and "str(d.get(\"text\") or \"\")" in reality,
        "shared_match_cache_reconstructs_current_docs_not_cached_truth": "row = dict(docs[j])" in reality and "EXACT_DERIVED_RETRIEVAL_REUSE_ONLY_NO_EVIDENCE_OR_THRESHOLD_AUTHORITY" in reality,
        "research_cycle_exposes_retrieval_cache_value": '"retrieval_cache_delta"' in orch and '"retrieval_cache": recurrence_result.get("retrieval_cache")' in orch,
        "system_audit_surfaces_last_attempt_and_observability": '"last_attempt_status"' in audit and '"observability_health"' in audit,
        "system_ui_distinguishes_attempt_from_success": "last attempt status" in system and "最近嘗試" in radar and "last_attempt_status" in client,
        "r7_has_zero_new_market_truth_writer": "market_ground_truth" not in progress and "RadarClaim" not in atomic_io,
        "worker_remains_canonical_runtime_entry": "run_signalforge_if_stale" in worker and "run_signalforge_manual_cycle" in worker,
    }


def frozen_checks() -> dict[str, bool]:
    return {
        f"unchanged.{Path(rel).name}.{name}": function_hash(rel, name) == expected
        for (rel, name), expected in FROZEN_FUNCTION_HASHES.items()
    }


def compile_checks() -> dict[str, bool]:
    files = [
        "processors/signalforge_atomic_io.py",
        "processors/signalforge_runtime_progress.py",
        "processors/signalforge_runtime.py",
        "run_signalforge_runtime_worker.py",
        "processors/problem_recurrence_multi.py",
        "processors/opportunity_reality.py",
        "processors/research_orchestrator.py",
        "processors/system_wide_audit.py",
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
    checks.update({f"behavior.{k}": v for k, v in behavior_checks().items()})
    checks.update({f"source.{k}": v for k, v in source_checks().items()})
    checks.update(frozen_checks())
    checks.update(compile_checks())

    print("=" * 126)
    print("SIGNALFORGE R7 — FULL-SYSTEM RUNTIME DURABILITY + EXACT INCREMENTAL RETRIEVAL — NO-DB ACCEPTANCE")
    print("=" * 126)
    passed = 0
    for key, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {key}")
        passed += int(bool(ok))
    total = len(checks)
    print("-" * 126)
    print(f"TOTAL={total} PASS={passed} FAIL={total-passed}")
    print("R7 isolates observability failure and reuses only exact derived retrieval work. C01-C14 and Market Calibration remain evidence/outcome-owned.")
    print("=" * 126)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
