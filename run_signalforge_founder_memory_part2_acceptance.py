#!/usr/bin/env python3
from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, bool(ok), detail


def fake_market(state: str = "UNKNOWN", *, revision: int = 1) -> dict:
    states = {f"C{i:02d}": "UNKNOWN" for i in range(1, 15)}
    states["C05"] = state
    return {
        "status": "PASS",
        "thesis_id": "thesis:agency-qa",
        "representative_title": "Agency QA",
        "revision": revision,
        "classification": "WATCH",
        "strategic_track": "FAST_VALIDATION",
        "zip2_readiness": "INVESTIGATE",
        "claim_states": states,
        "known": ([{"claim_code": "C05", "label": "Buyer / payer exists", "state": "SUPPORTED"}] if state == "SUPPORTED" else []),
        "contradicted": ([{"claim_code": "C05", "label": "Buyer / payer exists", "state": "REFUTED"}] if state == "REFUTED" else []),
        "unknown": ([{"claim_code": "C05", "label": "Buyer / payer exists", "state": state}] if state not in {"SUPPORTED", "REFUTED"} else []),
        "truth_boundary": "FIXTURE_PUBLISHED_READ_ONLY",
    }


def main() -> int:
    memory = importlib.import_module("processors.signalforge_founder_memory")
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="sf-founder-memory-") as td:
        root = Path(td)
        market_state = {"state": "UNKNOWN", "revision": 1}
        original_market = memory._published_market_snapshot
        memory._published_market_snapshot = lambda thesis_id: fake_market(market_state["state"], revision=market_state["revision"])
        try:
            decision = memory.record_founder_reasoning(
                subject_key="DoneProof",
                thesis_id="thesis:agency-qa",
                entry_type="DECISION",
                statement="Freeze DoneProof product development.",
                reason="WTP / revenue wedge is not yet established.",
                source_ref="ChatGPT 2026-09-06",
                root=root,
            )
            rejected = memory.record_founder_reasoning(
                subject_key="DoneProof",
                thesis_id="thesis:agency-qa",
                entry_type="REJECTED_DIRECTION",
                statement="Generic AI code reviewer.",
                reason="Too commodity and does not establish a distinct paid wedge.",
                root=root,
            )
            memory.record_founder_reasoning(
                subject_key="DoneProof", thesis_id="thesis:agency-qa", entry_type="HYPOTHESIS",
                statement="Agencies may pay more than solo builders.", root=root,
            )
            memory.record_founder_reasoning(
                subject_key="DoneProof", thesis_id="thesis:agency-qa", entry_type="CONSTRAINT",
                statement="First version must be testable in days.", root=root,
            )
            q1 = memory.record_founder_reasoning(
                subject_key="DoneProof", thesis_id="thesis:agency-qa", entry_type="QUESTION",
                statement="Is agency delivery QA a material current cost?", root=root,
            )

            ledger = memory.list_founder_reasoning(subject_key="DoneProof", thesis_id="thesis:agency-qa", root=root)
            results.append(check("real discussion is durably recorded", ledger["count"] == 5, str(ledger["count"])))
            results.append(check("Founder authority is explicit", all(x.get("authority") == "FOUNDER" for x in ledger["items"])))
            results.append(check("Founder memory has zero market authority", all(x.get("market_authority") == "NONE" and x.get("market_truth_impact") == "NONE" for x in ledger["items"])))
            results.append(check("decision preserves its reason", decision["entry"]["reason"] == "WTP / revenue wedge is not yet established."))
            results.append(check("rejected direction preserves why", rejected["entry"]["reason"].startswith("Too commodity")))
            results.append(check("questions remain unvalidated Founder reasoning", q1["entry"]["validation_status"] == "UNVALIDATED_FOUNDER_REASONING"))

            try:
                memory.record_founder_reasoning(subject_key="DoneProof", entry_type="DECISION", statement="Do it.", reason="", root=root)
                missing_reason_blocked = False
            except ValueError:
                missing_reason_blocked = True
            results.append(check("decision without reason is fail-closed", missing_reason_blocked))

            brief = memory.build_discussion_brief(subject_key="DoneProof", thesis_id="thesis:agency-qa", root=root)
            results.append(check("Brief separates Published market truth", brief["market_truth"]["truth_boundary"] == "FIXTURE_PUBLISHED_READ_ONLY"))
            results.append(check("Brief groups Founder hypotheses", len(brief["founder_reasoning"]["hypotheses"]) == 1))
            results.append(check("Brief groups Founder decisions", len(brief["founder_reasoning"]["decisions"]) == 1))
            results.append(check("Brief keeps rejected direction + reason", brief["founder_reasoning"]["rejected_directions"][0]["reason"].startswith("Too commodity")))
            results.append(check("Brief exposes current discussion question", brief["current_decision_frontier"]["statement"] == "Is agency delivery QA a material current cost?"))
            results.append(check("Brief prevents re-discussing settled directions", any(x.get("statement") == "Generic AI code reviewer." for x in brief["do_not_discuss_again"])))
            results.append(check("Brief itself creates zero market truth writes", brief["market_truth_writes"] == 0))

            no_base = memory.build_discussion_delta(subject_key="DoneProof", thesis_id="thesis:agency-qa", root=root)
            results.append(check("Delta refuses to invent last-discussion baseline", no_base["status"] == "NO_DISCUSSION_BASELINE"))

            cp = memory.create_discussion_checkpoint(subject_key="DoneProof", thesis_id="thesis:agency-qa", note="End of first discussion", root=root)
            results.append(check("explicit discussion checkpoint created", cp["status"] == "CHECKPOINT_RECORDED" and cp["market_truth_writes"] == 0))

            memory.record_founder_reasoning(
                subject_key="DoneProof", thesis_id="thesis:agency-qa", entry_type="QUESTION",
                statement="Do small agencies already allocate senior review hours to this?", root=root,
            )
            market_state["state"] = "SUPPORTED"
            market_state["revision"] = 2
            delta = memory.build_discussion_delta(subject_key="DoneProof", thesis_id="thesis:agency-qa", root=root)
            results.append(check("Delta returns only memory added after checkpoint", len(delta["new_founder_reasoning"]) == 1 and delta["new_founder_reasoning"][0]["statement"].startswith("Do small agencies")))
            results.append(check("Delta detects Published claim-state change", any(x.get("claim_code") == "C05" and x.get("before") == "UNKNOWN" and x.get("after") == "SUPPORTED" for x in delta["market_delta"]["changed_claims"])))
            results.append(check("Delta exposes the new next question", delta["new_next_question"]["statement"].startswith("Do small agencies")))
            results.append(check("Delta creates zero market truth writes", delta["market_truth_writes"] == 0))

            subjects = memory.list_founder_memory_subjects(root=root)
            results.append(check("subject index supports returning discussions", subjects["count"] == 1 and subjects["items"][0]["latest_question"].startswith("Do small agencies")))
            status = memory.founder_memory_status(root=root)
            results.append(check("append-only ledger hash chain verifies", status["status"] == "PASS" and status["hash_chain_verified"] is True and status["entries"] == 6 and status["checkpoints"] == 1))
        finally:
            memory._published_market_snapshot = original_market

    with tempfile.TemporaryDirectory(prefix="sf-founder-memory-corrupt-") as td:
        root = Path(td)
        memory.record_founder_reasoning(subject_key="Test", entry_type="QUESTION", statement="What matters next?", root=root)
        path = root / memory.LEDGER_RELATIVE_PATH
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("What matters next?", "What was silently changed?"), encoding="utf-8")
        corrupt = memory.founder_memory_status(root=root)
        results.append(check("tampered Founder Memory fails visibly", corrupt["status"] == "CORRUPT_OR_UNREADABLE" and corrupt["writable"] is False))
        try:
            memory.record_founder_reasoning(subject_key="Test", entry_type="QUESTION", statement="Should not append over corruption", root=root)
            blocked = False
        except RuntimeError:
            blocked = True
        results.append(check("corrupt ledger blocks new write", blocked))

    route = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
    source = (ROOT / "processors/signalforge_founder_memory.py").read_text(encoding="utf-8")
    ui = (ROOT / "dashboard/src/pages/FounderMemory.tsx").read_text(encoding="utf-8")
    app = (ROOT / "dashboard/src/App.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "dashboard/src/components/Sidebar.tsx").read_text(encoding="utf-8")
    client = (ROOT / "dashboard/src/api/client.ts").read_text(encoding="utf-8")
    hooks = (ROOT / "dashboard/src/api/hooks.ts").read_text(encoding="utf-8")

    results.append(check("Founder Memory API surface complete", all(x in route for x in ["/founder-memory/entries", "/founder-memory/brief", "/founder-memory/delta", "/founder-memory/checkpoints"])))
    results.append(check("Founder Memory processor has no DB / market-truth writer import", "from database.connection" not in source and "import database" not in source and "from processors.market_ground_truth" not in source and "from processors.radar_ledger" not in source))
    results.append(check("Founder Memory requires no LLM", "openai" not in source.lower() and "anthropic" not in source.lower()))
    results.append(check("Dashboard has first-class memory page", 'path="memory"' in app and 'label: "討論記憶"' in sidebar))
    results.append(check("UI makes authority boundary visible", "Founder Reasoning ≠ Market Truth" in ui and "MARKET AUTHORITY: NONE" in ui))
    results.append(check("UI supports Brief and Since Last Discussion", "Founder Discussion Brief" in ui and "Since Last Discussion" in ui))
    results.append(check("UI records rejected/decision reasons", "原因" in ui and "REJECTED DIRECTIONS" in ui and "DECISIONS" in ui))
    results.append(check("UI baseline is explicit not inferred", "把現在設為已討論基準" in ui and "沒有 baseline 就不假裝知道" in ui))
    results.append(check("Founder can link Published thesis without knowing IDs", "從目前 Published 方向帶入" in ui and "進階：手動指定 linked thesis" in ui))
    results.append(check("client + hooks expose memory workflow", "recordSignalForgeFounderMemory" in client and "checkpointSignalForgeFounderMemory" in client and "useSignalForgeFounderMemoryBrief" in hooks and "useSignalForgeFounderMemoryDelta" in hooks))

    failed = [x for x in results if not x[1]]
    print("=" * 100)
    print("SIGNALFORGE PART 2 — FOUNDER MEMORY — REAL FOUNDER TASK ACCEPTANCE")
    print("=" * 100)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}" + (f" — {detail}" if detail else ""))
    print("-" * 100)
    print(f"RESULT: {len(results)-len(failed)}/{len(results)} PASS")
    if failed:
        print("FINAL_STATUS: SIGNALFORGE_FOUNDER_MEMORY_PART2_ACCEPTANCE_FAIL")
        return 1
    print("FINAL_STATUS: SIGNALFORGE_FOUNDER_MEMORY_PART2_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
