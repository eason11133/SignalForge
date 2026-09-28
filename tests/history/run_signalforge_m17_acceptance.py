from __future__ import annotations

import ast
import asyncio
import builtins
import json
import py_compile
import symtable
import tempfile
from pathlib import Path

PYTHON_FILES = [
    "api/main.py",
    "api/routes/signalforge.py",
    "processors/signalforge_runtime.py",
    "processors/system_wide_audit.py",
    "show_signalforge_full_system_audit.py",
    "run_radar_cycle.py",
    "processors/research_orchestrator.py",
    "processors/opportunity_reality.py",
    "processors/materiality_research.py",
    "processors/founder_daily_surface.py",
]


def _defined(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def target(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                target(item)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                target(t)
        elif isinstance(node, ast.AnnAssign):
            target(node.target)
    return names


def undefined_globals(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    defined = _defined(tree)
    builtin_names = set(dir(builtins))
    table = symtable.symtable(source, str(path), "exec")
    unresolved: set[str] = set()

    def walk(scope) -> None:
        for child in scope.get_children():
            for symbol in child.get_symbols():
                if not (symbol.is_referenced() and symbol.is_global()):
                    continue
                name = symbol.get_name()
                if name == "__file__" or name in defined or name in builtin_names:
                    continue
                unresolved.add(name)
            walk(child)

    walk(table)
    return sorted(unresolved)


def static_contract_check() -> dict:
    root = Path.cwd()
    unresolved: dict[str, list[str]] = {}
    for rel in PYTHON_FILES:
        path = root / rel
        py_compile.compile(str(path), doraise=True)
        names = undefined_globals(path)
        if names:
            unresolved[rel] = names
    if unresolved:
        raise AssertionError(f"undefined globals: {unresolved}")

    runtime = (root / "processors/signalforge_runtime.py").read_text(encoding="utf-8")
    api_main = (root / "api/main.py").read_text(encoding="utf-8")
    route = (root / "api/routes/signalforge.py").read_text(encoding="utf-8")
    audit = (root / "processors/system_wide_audit.py").read_text(encoding="utf-8")
    runner = (root / "run_radar_cycle.py").read_text(encoding="utf-8")
    orch = (root / "processors/research_orchestrator.py").read_text(encoding="utf-8")
    founder = (root / "processors/founder_daily_surface.py").read_text(encoding="utf-8")

    required = {
        "runtime": [
            "signalforge-runtime-v4-published-truth-barrier",
            "UPGRADE_GUARD_PATH",
            "UPGRADE_GUARD",
            "_wait_for_auto_owner",
            "INTERRUPTED",
        ],
        "api_main": [
            "_delayed_signalforge_startup",
            "SIGNALFORGE_STARTUP_CATCHUP_DELAY_SECONDS",
        ],
        "route": [
            "_load_published_daily",
            "NO_PUBLISHED_SNAPSHOT",
            "snapshot['published'] = True",
        ],
        "audit": [
            "system-wide-audit-v5-m17-published-truth-boundary",
            "deferred_while_cycle_running",
            "Unpublished DB truth is intentionally hidden",
        ],
        "runner": ["raise SystemExit(20)", "BUSY_CROSS_PROCESS"],
        "orch": [
            "auto-research-orchestrator-v22-m16-go-live-finalization",
            'elif gate not in {"CURRENT_SOLUTION", "UNRESOLVED_GAP"}:',
            "gap_prefetch",
        ],
        "founder": [
            "founder-daily-surface-v5-published-final-decision",
            "decision: dict[str, Any] | None = None",
            "if decision is None:",
        ],
    }
    sources = {
        "runtime": runtime,
        "api_main": api_main,
        "route": route,
        "audit": audit,
        "runner": runner,
        "orch": orch,
        "founder": founder,
    }
    for group, markers in required.items():
        for marker in markers:
            if marker not in sources[group]:
                raise AssertionError(f"missing {group} marker: {marker}")

    if "build_founder_daily_surface" in route:
        raise AssertionError("GET /daily still recomputes mutable DB truth")
    if audit.index('if runtime.get("running")') > audit.index("async with async_session() as session"):
        raise AssertionError("audit checks live DB before the publish boundary")
    if orch.count("updated = await run_opportunity_decision(limit=50)") != 1:
        raise AssertionError("M16 one-final-decision contract regressed")
    runtime_source = (root / "processors/signalforge_runtime.py").read_text(encoding="utf-8")
    if 'decision=cycle.get("final") or None' not in runtime_source:
        raise AssertionError("Founder snapshot does not reuse the final cycle decision")

    return {"python_files": len(PYTHON_FILES), "undefined_globals": 0}


def _load_runtime_isolated():
    import importlib.util
    import sys
    import types

    saved = {name: sys.modules.get(name) for name in (
        "processors.research_orchestrator",
        "processors.founder_daily_surface",
        "processors.historical_replay",
    )}
    try:
        research = types.ModuleType("processors.research_orchestrator")
        async def _never_cycle(*args, **kwargs):
            raise AssertionError("guard test unexpectedly entered a research cycle")
        research.run_research_cycle = _never_cycle
        research.print_research_cycle = _never_cycle
        sys.modules[research.__name__] = research

        founder = types.ModuleType("processors.founder_daily_surface")
        founder.build_founder_daily_surface = _never_cycle
        sys.modules[founder.__name__] = founder

        replay = types.ModuleType("processors.historical_replay")
        replay.capture_forward_policy_snapshot = _never_cycle
        sys.modules[replay.__name__] = replay

        spec = importlib.util.spec_from_file_location(
            "_signalforge_runtime_m17_acceptance",
            Path("processors/signalforge_runtime.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


async def runtime_barrier_behavior_check() -> dict:
    runtime = _load_runtime_isolated()

    with tempfile.TemporaryDirectory(prefix="signalforge_m17_") as td:
        base = Path(td)
        runtime.STATE_PATH = base / "state.json"
        runtime.LEASE_PATH = base / "lease.json"
        runtime.UPGRADE_GUARD_PATH = base / "guard.json"

        runtime.STATE_PATH.write_text(
            json.dumps({"status": "RUNNING", "last_success_at": None}),
            encoding="utf-8",
        )
        status = runtime.get_signalforge_runtime_status()
        if status.get("status") != "INTERRUPTED" or status.get("running"):
            raise AssertionError(f"stale RUNNING state not normalized: {status}")

        from datetime import timedelta
        runtime.UPGRADE_GUARD_PATH.write_text(
            json.dumps({
                "reason": "m17_acceptance",
                "expires_at": (runtime._utcnow() + timedelta(minutes=5)).isoformat(),
            }),
            encoding="utf-8",
        )
        guarded = await runtime.run_signalforge_if_stale(
            force=False,
            reason="startup_catchup",
        )
        if not guarded.get("skipped") or guarded.get("skip_reason") != "UPGRADE_GUARD":
            raise AssertionError(f"startup guard failed: {guarded}")
        if runtime.LEASE_PATH.exists():
            raise AssertionError("guarded startup acquired a mutation lease")

        runtime._clear_upgrade_guard()
        if runtime.UPGRADE_GUARD_PATH.exists():
            raise AssertionError("manual guard clear failed")

    return {"startup_blocked": True, "stale_running_normalized": True, "manual_clear": True}


def _load_audit_isolated():
    import importlib.util
    import sys
    import types

    names = [
        "database.connection",
        "processors.quality_guard",
        "processors.calibration",
        "processors.validation_cohort",
        "processors.signalforge_runtime",
        "processors.historical_replay",
        "processors.market_closure_readiness",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    try:
        db = types.ModuleType("database.connection")
        class _Dummy:
            id = object()
        class _AsyncSessionSentinel:
            def __call__(self, *args, **kwargs):
                raise AssertionError("audit touched live DB while cycle was running")
        db.async_session = _AsyncSessionSentinel()
        for attr in (
            "ProblemCandidate", "RadarCase", "RadarClaim", "RadarEvidence",
            "RadarClaimEvidence", "Post", "NewsEvent", "JobListing", "GithubRepo",
            "HFModel", "SOQuestion", "PackageDownload", "YCCompany", "ProductReview",
        ):
            setattr(db, attr, _Dummy)
        sys.modules[db.__name__] = db

        quality = types.ModuleType("processors.quality_guard")
        async def _audit_quality(*args, **kwargs):
            raise AssertionError("quality audit should not run against in-flight DB truth")
        quality.audit_quality = _audit_quality
        sys.modules[quality.__name__] = quality

        calibration = types.ModuleType("processors.calibration")
        calibration.calibration_report = lambda: (_ for _ in ()).throw(AssertionError("calibration should be deferred"))
        sys.modules[calibration.__name__] = calibration

        cohort = types.ModuleType("processors.validation_cohort")
        cohort.load_validation_cohort = lambda: (_ for _ in ()).throw(AssertionError("cohort should be deferred"))
        sys.modules[cohort.__name__] = cohort

        runtime = types.ModuleType("processors.signalforge_runtime")
        runtime.get_signalforge_runtime_status = lambda: {
            "running": True,
            "lease": {"pid": 1234, "reason": "startup_catchup"},
            "last_success_at": "2026-08-25T10:47:54+00:00",
        }
        sys.modules[runtime.__name__] = runtime

        replay = types.ModuleType("processors.historical_replay")
        replay.forward_policy_snapshot_status = lambda: (_ for _ in ()).throw(AssertionError("replay should be deferred"))
        sys.modules[replay.__name__] = replay

        closure = types.ModuleType("processors.market_closure_readiness")
        closure.market_closure_readiness = lambda: (_ for _ in ()).throw(AssertionError("market closure should be deferred"))
        sys.modules[closure.__name__] = closure

        spec = importlib.util.spec_from_file_location(
            "_system_wide_audit_m17_acceptance",
            Path("processors/system_wide_audit.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


async def published_audit_behavior_check() -> dict:
    audit = _load_audit_isolated()
    audit._load_published_founder_snapshot = lambda: {
        "generated_at": "2026-08-25T10:47:54",
        "verdict_counts": {"WATCH": 49, "INVESTIGATE": 6},
        "cards": [{"case_id": 1, "verdict": "INVESTIGATE"}],
        "quality": {"status": "PASS", "critical_count": 0},
    }
    result = await audit.run_system_wide_audit()
    if not result.get("deferred_while_cycle_running"):
        raise AssertionError("audit did not fail closed while cycle running")
    if result.get("areas"):
        raise AssertionError("audit exposed live DB-derived areas while cycle running")
    if (result.get("published_founder") or {}).get("verdict_counts") != {"WATCH": 49, "INVESTIGATE": 6}:
        raise AssertionError("last published Founder truth was not preserved")
    return {"published_only": True, "live_db_hidden": True}


def published_daily_behavior_check() -> dict:
    source = Path("api/routes/signalforge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_load_published_daily"
    )
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"SNAPSHOT": None, "json": json, "dict": dict}
    exec(compile(module, "<published_daily>", "exec"), ns)
    with tempfile.TemporaryDirectory(prefix="signalforge_daily_") as td:
        snapshot = Path(td) / "founder_daily.json"
        ns["SNAPSHOT"] = snapshot
        expected = {"generated_at": "t0", "verdict_counts": {"WATCH": 1}, "cards": []}
        snapshot.write_text(json.dumps(expected), encoding="utf-8")
        loaded = ns["_load_published_daily"]()
        if loaded != expected:
            raise AssertionError("published daily snapshot loader changed truth")
    return {"snapshot_read_only": True}


async def main() -> None:
    print("=" * 126)
    print("SIGNALFORGE M17 PUBLISHED-TRUTH / RELOAD-BARRIER ACCEPTANCE")
    print("=" * 126)
    print("No crawler. No full recurrence. No LLM. No DB mutation. No threshold weakening.")
    print()

    static = static_contract_check()
    barrier = await runtime_barrier_behavior_check()
    published_audit = await published_audit_behavior_check()
    daily = published_daily_behavior_check()

    print(f"STATIC Python={static['python_files']} undefined_globals={static['undefined_globals']}")
    print("UPGRADE / RELOAD BARRIER status=PASS startup_blocked=YES stale_running=INTERRUPTED")
    print("PUBLISHED AUDIT status=PASS live_db_hidden=YES")
    print("FOUNDER DAILY status=PASS read_only_published_snapshot=YES")
    print("M16 EVIDENCE CONTRACT status=PASS C06_shadow_fix=PRESERVED final_decision_count=1 Founder_rebuild=REUSED")
    print()
    print("SIGNALFORGE_M17_ACCEPTANCE_PASS")
    print("Next: python run_radar_cycle.py ; then python show_signalforge_full_system_audit.py")
    print("=" * 126)


if __name__ == "__main__":
    asyncio.run(main())
