from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
checks: list[tuple[str, bool, object]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    checks.append((name, bool(ok), detail))


def run_many(code: str, args: list[list[str]], cwd: Path, timeout: int = 90) -> list[subprocess.CompletedProcess[str]]:
    env = os.environ.copy()
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + prior if prior else "")
    procs: list[tuple[list[str], subprocess.Popen[str]]] = []
    for extra in args:
        cmd = [PYTHON, "-c", code, *extra]
        procs.append((cmd, subprocess.Popen(cmd, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)))
    results: list[subprocess.CompletedProcess[str]] = []
    for cmd, proc in procs:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill(); out, err = proc.communicate()
            results.append(subprocess.CompletedProcess(cmd, 124, out, err + "\nTIMEOUT"))
        else:
            results.append(subprocess.CompletedProcess(cmd, proc.returncode, out, err))
    return results


with tempfile.TemporaryDirectory(prefix="sf_p6_durable_") as td:
    work = Path(td)

    # 1) 30 distinct Market Actions register concurrently in separate processes.
    market_worker = r'''
import sys
from processors import signalforge_market_action_registry as mar
idx = int(sys.argv[1])
items = []
for i in range(30):
    items.append({
        "thesis_id": f"t{i}",
        "revision": 1,
        "representative_title": f"Thesis {i}",
        "strategic_track": "BOTH",
        "classification": "FIXTURE",
        "zip2_readiness": "SUPPORTED",
        "founder_addressability": {"first_person_addressability_state": "SUPPORTED"},
        "fast_validation": {},
        "best_next_action": {"mode": "MARKET_ACTION", "action": "OUTREACH", "reason": "fixture", "voi": 1},
        "member_candidate_ids": [1000+i],
        "claim_states": {},
        "dimensions": {},
    })
mar._brain_portfolio = lambda root=None: {"status": "PASS", "portfolio": items}
r = mar.register_market_action(thesis_id=f"t{idx}", action_type="OUTREACH", sample_target=1, success_criteria="one qualified reply", failure_criteria="no qualified reply")
print(r["action_id"])
'''
    results = run_many(market_worker, [[str(i)] for i in range(30)], work)
    ok_procs = [r for r in results if r.returncode == 0]
    registry = work / ".radar_runtime/signalforge_market_actions.jsonl"
    rows = [json.loads(x) for x in registry.read_text(encoding="utf-8").splitlines() if x.strip()] if registry.exists() else []
    ids = {str(r.get("thesis_id")) for r in rows}
    action_ids = {str(r.get("action_id")) for r in rows}
    check("market_action.30_processes_report_success", len(ok_procs) == 30, [(r.returncode, r.stderr[-200:]) for r in results if r.returncode != 0])
    check("market_action.30_distinct_rows_durable", len(rows) == 30 and ids == {f"t{i}" for i in range(30)}, len(rows))
    check("market_action.action_ids_unique", len(action_ids) == 30, len(action_ids))

    # 2) 24 pre-seeded validation experiments complete concurrently.
    vr_path = work / ".radar_runtime/validation_experiments.jsonl"
    vr_path.parent.mkdir(parents=True, exist_ok=True)
    pending = [{
        "engine_version": "fixture",
        "experiment_id": f"exp-{i}",
        "created_at": "2026-09-06T00:00:00",
        "case_id": 2000+i,
        "title": f"Case {i}",
        "claim_code": "C10",
        "event": "ACQUISITION",
        "status": "PENDING",
        "pretest_snapshot": {"candidate_id": 3000+i},
        "plan": {"fixture": True},
        "note": None,
        "result": None,
        "completed_at": None,
        "actor_label": None,
    } for i in range(24)]
    vr_path.write_text("\n".join(json.dumps(x) for x in pending) + "\n", encoding="utf-8")
    validation_worker = r'''
import sys
from processors import validation_registry as vr
idx = int(sys.argv[1])
r = vr.complete_validation_experiment(experiment_id=f"exp-{idx}", result="FAIL", note="fixture", actor_label=f"Buyer {idx}")
print(r["experiment_id"] if r else "NONE")
'''
    results2 = run_many(validation_worker, [[str(i)] for i in range(24)], work)
    rows2 = [json.loads(x) for x in vr_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    completed = [r for r in rows2 if r.get("status") == "COMPLETED"]
    check("validation.24_processes_report_success", sum(r.returncode == 0 for r in results2) == 24, [(r.returncode, r.stderr[-200:]) for r in results2 if r.returncode != 0])
    check("validation.24_distinct_completions_durable", len(rows2) == 24 and len(completed) == 24, (len(rows2), len(completed)))
    check("validation.experiment_ids_preserved", {r.get("experiment_id") for r in rows2} == {f"exp-{i}" for i in range(24)})

    # 3) Same validation experiment: exactly one process may immutably complete it.
    same = [{
        "engine_version": "fixture",
        "experiment_id": "exp-same",
        "created_at": "2026-09-06T00:00:00",
        "case_id": 9999,
        "claim_code": "C10",
        "event": "ACQUISITION",
        "status": "PENDING",
        "pretest_snapshot": {"candidate_id": 9999},
        "plan": {"fixture": True},
        "result": None,
    }]
    vr_path.write_text(json.dumps(same[0]) + "\n", encoding="utf-8")
    same_worker = r'''
import sys
from processors import validation_registry as vr
idx = int(sys.argv[1])
try:
    r = vr.complete_validation_experiment(experiment_id="exp-same", result="FAIL", note=f"worker-{idx}", actor_label=f"Buyer-{idx}")
    print("COMPLETED", r["result_note"])
except ValueError as exc:
    if "already COMPLETED" in str(exc):
        print("ALREADY_COMPLETED")
    else:
        raise
'''
    results3 = run_many(same_worker, [[str(i)] for i in range(12)], work)
    final_same = [json.loads(x) for x in vr_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    successes = sum("COMPLETED worker-" in (r.stdout or "") for r in results3)
    already = sum("ALREADY_COMPLETED" in (r.stdout or "") for r in results3)
    check("validation.same_experiment_single_winner", successes == 1 and already == 11, (successes, already))
    check("validation.same_experiment_one_durable_row", len(final_same) == 1 and final_same[0].get("status") == "COMPLETED", final_same)

    # 4) Same Market Action: exactly one outcome completion; others fail immutability.
    # Reuse one durable registered action from test 1 by replacing registry with a single row.
    one = rows[0]
    registry.write_text(json.dumps(one) + "\n", encoding="utf-8")
    aid = str(one["action_id"])
    market_complete_worker = r'''
import sys
from processors import signalforge_market_action_registry as mar
aid = sys.argv[1]
idx = int(sys.argv[2])
try:
    r = mar.complete_market_action(action_id=aid, result="INCONCLUSIVE", observations={"observed_sample_size": 0}, note=f"worker-{idx}")
    print("COMPLETED", r["result_note"])
except ValueError as exc:
    if "already completed" in str(exc):
        print("ALREADY_COMPLETED")
    else:
        raise
'''
    results4 = run_many(market_complete_worker, [[aid, str(i)] for i in range(12)], work)
    final_market = [json.loads(x) for x in registry.read_text(encoding="utf-8").splitlines() if x.strip()]
    successes4 = sum("COMPLETED worker-" in (r.stdout or "") for r in results4)
    already4 = sum("ALREADY_COMPLETED" in (r.stdout or "") for r in results4)
    check("market_action.same_action_single_winner", successes4 == 1 and already4 == 11, (successes4, already4))
    check("market_action.same_action_one_durable_row", len(final_market) == 1 and final_market[0].get("status") == "COMPLETED", final_market)

print("="*108)
print("SIGNALFORGE PART 6 — MARKET EXECUTION & LEARNING — MULTIPROCESS DURABILITY ACCEPTANCE")
print("="*108)
for name, ok, detail in checks:
    print(("PASS" if ok else "FAIL").ljust(6), name, ("— " + str(detail)[:500]) if detail not in ("", None) else "")
passed = sum(ok for _, ok, _ in checks)
print("-"*108)
print(f"RESULT: {passed}/{len(checks)} PASS")
if passed != len(checks):
    raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_MARKET_EXECUTION_LEARNING_PART6_DURABILITY_ACCEPTANCE_PASS")
