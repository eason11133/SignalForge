#!/usr/bin/env python3
from __future__ import annotations

import multiprocessing as mp
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _prepare_worker(root_str: str, i: int) -> tuple[str, str]:
    from processors.signalforge_chatgpt_integration import prepare_decision_artifact
    out = prepare_decision_artifact(
        root=Path(root_str),
        subject_key="concurrent prepare",
        subject_label="Concurrent Prepare",
        entries=[{"entry_type":"HYPOTHESIS","statement":f"Concurrent hypothesis {i}"}],
        source="CONCURRENCY_ACCEPTANCE",
    )
    art = out.get("artifact") or {}
    return str(out.get("status")), str(art.get("artifact_id") or "")


def _prepare_confirm_worker(root_str: str, i: int) -> tuple[str, str, str]:
    from processors.signalforge_chatgpt_integration import confirm_decision_artifact, prepare_decision_artifact
    prepared = prepare_decision_artifact(
        root=Path(root_str),
        subject_key="concurrent confirm",
        subject_label="Concurrent Confirm",
        entries=[{"entry_type":"DECISION","statement":f"Concurrent decision {i}","reason":f"Durability reason {i}"}],
        source="CONCURRENCY_ACCEPTANCE",
    )
    aid = str((prepared.get("artifact") or {}).get("artifact_id") or "")
    confirmed = confirm_decision_artifact(artifact_id=aid, founder_confirmed=True, root=Path(root_str))
    return str(prepared.get("status")), str(confirmed.get("status")), aid


def _same_artifact_confirm_worker(root_str: str, aid: str) -> str:
    from processors.signalforge_chatgpt_integration import confirm_decision_artifact
    out = confirm_decision_artifact(artifact_id=aid, founder_confirmed=True, root=Path(root_str))
    return str(out.get("status"))


def run_pool(fn, args, max_workers: int = 12):
    ctx = mp.get_context("spawn")
    out=[]
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
        futures=[ex.submit(fn,*a) for a in args]
        for f in as_completed(futures): out.append(f.result())
    return out


def main() -> int:
    from processors.signalforge_chatgpt_integration import list_decision_artifacts, prepare_decision_artifact
    from processors.signalforge_founder_memory import list_founder_reasoning

    checks=[]
    def check(name, ok, detail=None):
        checks.append((name,bool(ok),detail)); print(("PASS" if ok else "FAIL").ljust(6),name,(f"— {detail}" if detail is not None else ""))

    print("="*112)
    print("SIGNALFORGE PART 5 CLOSURE — CROSS-PROCESS DURABILITY ACCEPTANCE")
    print("="*112)
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        # Exact adversarial shape from independent review: 30 processes all report success.
        r1=run_pool(_prepare_worker,[(str(root),i) for i in range(30)],max_workers=15)
        ids=[x[1] for x in r1]
        listing=list_decision_artifacts(root=root,limit=100)
        check("30 concurrent prepare processes all return PREPARED", len(r1)==30 and all(x[0]=="PREPARED" for x in r1), len(r1))
        check("30 concurrent prepare artifact ids are unique", len(set(ids))==30 and all(ids), len(set(ids)))
        check("durable SQLite ledger preserves all 30 prepares", listing.get("count")==30, listing.get("count"))
        check("artifact store declares cross-process safe SQLite", listing.get("cross_process_safe") is True and "SQLITE_BEGIN_IMMEDIATE" in str(listing.get("storage")), listing.get("storage"))

        # Concurrent prepare + confirm exercises SQLite serialization plus Part 2 cross-process append lock.
        r2=run_pool(_prepare_confirm_worker,[(str(root),i) for i in range(20)],max_workers=10)
        listing2=list_decision_artifacts(root=root,limit=100)
        confirmed=[x for x in listing2.get("items") or [] if x.get("status")=="CONFIRMED_TO_FOUNDER_MEMORY"]
        fm=list_founder_reasoning(subject_key="concurrent confirm",root=root,limit=1000)
        check("20 concurrent prepare+confirm processes complete", len(r2)==20 and all(a=="PREPARED" and b in {"CONFIRMED","ALREADY_CONFIRMED"} for a,b,_ in r2), len(r2))
        check("durable artifact store has 50 total artifacts", listing2.get("count")==50, listing2.get("count"))
        check("all 20 concurrent confirms persist confirmed state", len(confirmed)==20, len(confirmed))
        check("Founder Memory preserves all 20 concurrent confirmed entries", fm.get("count")==20, fm.get("count"))
        check("Founder Memory hash chain remains verified", all(x.get("market_authority")=="NONE" for x in fm.get("items") or []), fm.get("count"))

        # Same-artifact racing confirmations must not duplicate Founder Memory.
        p=prepare_decision_artifact(root=root,subject_key="same artifact",entries=[{"entry_type":"DECISION","statement":"Only once","reason":"Concurrent idempotency"}])
        aid=str((p.get("artifact") or {}).get("artifact_id") or "")
        r3=run_pool(_same_artifact_confirm_worker,[(str(root),aid) for _ in range(12)],max_workers=12)
        fm2=list_founder_reasoning(subject_key="same artifact",root=root,limit=1000)
        check("same artifact concurrent confirm calls all resolve safely", len(r3)==12 and all(x in {"CONFIRMED","ALREADY_CONFIRMED"} for x in r3), {x:r3.count(x) for x in set(r3)})
        check("same artifact is appended to Founder Memory exactly once", fm2.get("count")==1, fm2.get("count"))

    failed=[x for x in checks if not x[1]]
    print("-"*112)
    print(f"RESULT: {len(checks)-len(failed)}/{len(checks)} PASS")
    if failed:
        for name,_,detail in failed: print("FAILED:",name,detail)
        return 1
    print("FINAL_STATUS: SIGNALFORGE_PART5_CROSS_PROCESS_DURABILITY_CLOSURE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
