#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path.cwd()

# The closure checks are pure processor tests. In isolated package verification,
# provide a minimal DB import stub only when the real repo DB module is absent.
try:
    import database.connection  # type: ignore # noqa: F401
except Exception:
    import types
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")
    class Dummy:
        id = candidate_id = claim_id = evidence_id = case_id = None
    async def _session():
        raise RuntimeError("DB stub should not be used by Part 1-3 closure pure tests")
    for name in ("ProblemCandidate", "RadarCase", "RadarClaim", "RadarClaimEvidence", "RadarEvidence"):
        setattr(conn, name, Dummy)
    conn.async_session = _session
    sys.modules["database.connection"] = conn
    setattr(db_pkg, "connection", conn)

from processors import signalforge_founder_idea_loop as p1
from processors import signalforge_founder_memory as p2
from processors import signalforge_trust_falsification as p3

checks: list[tuple[str, bool, Any]] = []

def check(name: str, ok: bool, detail: Any = None) -> None:
    checks.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, "" if detail is None else "— " + str(detail))

# ---------- Part 1 ----------
frontier = p1.build_decision_frontier(
    published_money_trail={"revenue_wedge": {}, "paid_dissatisfaction": {"count": 0}},
    fresh_summary={"coverage": "PARTIAL", "problem_discussions": 0, "existing_solutions": 0, "paid_signals": 0, "post_purchase_complaints": 0},
)
check("P1 partial coverage cannot support market-absence kill wording", "不適用" in frontier["kill_if"] and "PARTIAL" in frontier["kill_if"], frontier["kill_if"])

third_person = {
    "kind": "DISCUSSION", "title": "Report says customers have a problem",
    "excerpt": "Many users experience a broken workflow and failure",
    "signals": {"pain": ["problem", "broken", "failure"], "workaround": [], "paid": [], "dissatisfaction": []},
    "source": "X", "url": "https://example/a",
}
s = p1.summarize_fresh_probe({"traces": [third_person], "sources": [{"source": "X", "status": "SUCCESS", "count": 1, "transport": {}}]})
check("P1 firsthand_pain requires firsthand wording", s["firsthand_pain"] == 0, s["firsthand_pain"])

customer_trace = p1._make_trace(source="X", kind="DISCUSSION", title="Customer workflow problem", excerpt="The customer reports a broken workflow.", url="https://example/b")
cs = p1.summarize_fresh_probe({"traces": [customer_trace], "sources": [{"source": "X", "status": "SUCCESS", "count": 1, "transport": {}}]})
check("P1 generic customer mention is not payment evidence", cs["paid_signals"] == 0, customer_trace["signals"])
check("P1 workaround matcher respects token boundaries", "custom" not in (customer_trace.get("signals") or {}).get("workaround", []), customer_trace["signals"])

dollar_trace = p1._make_trace(source="X", kind="ISSUE", title="Parser fails on $ variable", excerpt="Bug when a string contains the $ token; workaround is manually escaping it.", url="https://example/c")
ds = p1.summarize_fresh_probe({"traces": [dollar_trace], "sources": [{"source": "X", "status": "SUCCESS", "count": 1, "transport": {}}]})
check("P1 bare dollar syntax is not paid dissatisfaction", ds["post_purchase_complaints"] == 0, dollar_trace["signals"])

commercial = {
    "kind": "DISCUSSION", "title": "We use VendorX",
    "excerpt": "We pay $49/month for VendorX but still do this manually.",
    "signals": {"pain": [], "workaround": ["manually"], "paid": ["currency_amount"], "dissatisfaction": ["but still", "manually"]},
    "source": "HN", "url": "https://example/d",
}
ss = p1.summarize_fresh_probe({"traces": [commercial], "sources": [{"source": "HN", "status": "SUCCESS", "count": 1, "transport": {}}]})
check("P1 paid commercial solution mention can surface as existing solution", ss["existing_solutions"] >= 1, ss["existing_solutions"])

queries = p1.expand_founder_query("理髮店臨時取消空位補位")
check("P1 common Chinese local-service idea reaches English-heavy sources", any(re.search(r"[A-Za-z]", q) for q in queries), queries)
unknown_queries = p1.expand_founder_query("量子廚房玄學排程")
# Unsupported Chinese is allowed only if runtime exposes the language limitation.
orig_searchers = p1._SEARCHERS
p1._SEARCHERS = (lambda q: {"source": "FIXTURE", "status": "SUCCESS", "query": q, "count": 0, "traces": [], "transport": {}},)
try:
    limited = p1.run_fresh_fast_probe("量子廚房玄學排程")
finally:
    p1._SEARCHERS = orig_searchers
check("P1 unmapped Chinese fails visibly as limited language coverage", limited.get("language_coverage") == "LIMITED_FOR_ENGLISH_HEAVY_SOURCES", limited.get("language_coverage"))

# ---------- Part 2 ----------
root = Path(tempfile.mkdtemp(prefix="sf_p2_basic_"))
r = p2.record_founder_reasoning(subject_key="memory-test", entry_type="HYPOTHESIS", statement="Founder thinks this might work", root=root)
check("P2 Founder reasoning retains zero Market Truth authority", r["entry"]["market_authority"] == "NONE" and r["market_truth_writes"] == 0)

race_root = tempfile.mkdtemp(prefix="sf_p2_race_")
child = r'''
import sys
from pathlib import Path
from processors.signalforge_founder_memory import record_founder_reasoning
root=Path(sys.argv[1]); i=sys.argv[2]
try:
    x=record_founder_reasoning(subject_key='race-memory',entry_type='HYPOTHESIS',statement=f'hypothesis {i}',root=root)
    print('OK',x['entry']['entry_id'])
except Exception as e:
    print('ERR',type(e).__name__,str(e))
'''
env = {**os.environ, "PYTHONPATH": str(ROOT)}
procs = [subprocess.Popen([sys.executable, "-c", child, race_root, str(i)], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(30)]
outs = [p.communicate() for p in procs]
reported = sum(1 for out, _ in outs if out.startswith("OK"))
durable = p2.list_founder_reasoning(subject_key="race-memory", root=Path(race_root), limit=1000)["count"]
check("P2 cross-process Founder Memory has no lost updates", reported == 30 and durable == 30, {"reported": reported, "durable": durable})

delta_root = Path(tempfile.mkdtemp(prefix="sf_p2_delta_"))
p2.record_founder_reasoning(subject_key="delta-test", entry_type="QUESTION", statement="Old question?", root=delta_root)
p2.create_discussion_checkpoint(subject_key="delta-test", root=delta_root)
p2.record_founder_reasoning(subject_key="delta-test", entry_type="CONSTRAINT", statement="New constraint only", root=delta_root)
delta = p2.build_discussion_delta(subject_key="delta-test", root=delta_root)
check("P2 Delta does not relabel old question as new", delta.get("new_next_question") is None, delta.get("new_next_question"))

sup_root = Path(tempfile.mkdtemp(prefix="sf_p2_sup_"))
p2.record_founder_reasoning(subject_key="decision-test", entry_type="DECISION", statement="Build A", reason="Initial reason", root=sup_root)
p2.record_founder_reasoning(subject_key="decision-test", entry_type="DECISION", statement="Do not build A", reason="New evidence changed the decision", root=sup_root)
brief = p2.build_discussion_brief(subject_key="decision-test", root=sup_root)
active = [x.get("statement") for x in brief.get("do_not_discuss_again") or [] if x.get("type") == "DECISION"]
check("P2 active guidance contains only latest decision", active == ["Do not build A"], active)

tamper_root = Path(tempfile.mkdtemp(prefix="sf_p2_tamper_"))
p2.record_founder_reasoning(subject_key="tamper-test", entry_type="HYPOTHESIS", statement="Original statement", root=tamper_root)
path = tamper_root / p2.LEDGER_RELATIVE_PATH
path.write_text(path.read_text(encoding="utf-8").replace("Original statement", "Changed silently"), encoding="utf-8")
st = p2.founder_memory_status(root=tamper_root)
check("P2 tampering remains fail-visible", st["status"] == "CORRUPT_OR_UNREADABLE" and not st["writable"], st["status"])

# Part 2 / Part 5 integration: one shared lock identity must survive the merge.
p2_source = (ROOT / "processors/signalforge_founder_memory.py").read_text(encoding="utf-8")
check(
    "P2 keeps Part5 shared cross-process lock domain",
    "from processors.signalforge_process_lock import cross_process_file_lock" in p2_source
    and 'LOCK_RELATIVE_PATH = Path(".radar_runtime/signalforge_founder_reasoning.lock")' in p2_source
    and "def _cross_process_lock(" not in p2_source,
)

# ---------- Part 3 ----------
# Verify the *executed* search query retains three distinct counter lenses without network I/O.
seen: list[str] = []
def fake_search(q: str) -> dict[str, Any]:
    seen.append(q)
    return {"source": "FIXTURE", "status": "SUCCESS", "query": q, "count": 0, "traces": [], "transport": {}}
orig_searchers = p1._SEARCHERS
p1._SEARCHERS = (fake_search,)
try:
    executed = []
    for item in p3.build_falsification_queries("AI coding agents forget project rules after context compaction during long software delivery tasks"):
        run = p3._run_falsification_query(item)
        executed.append(run.get("search_query_used"))
finally:
    p1._SEARCHERS = orig_searchers
check("P3 Try-to-Kill preserves distinct counter-hypothesis queries", len(set(executed)) == 3, executed)

neg_samples = [
    ({"title": "Not good enough", "excerpt": "The built-in tool is not good enough; we still need a separate product."}, "CURRENT_SOLUTION_GOOD_ENOUGH"),
    ({"title": "Easy migration", "excerpt": "Switching cost is low and migration is easy."}, "SWITCHING_OR_TRUST_BARRIER"),
    ({"title": "No security review", "excerpt": "No security review is required for this lightweight tool."}, "SWITCHING_OR_TRUST_BARRIER"),
    ({"title": "Still alive", "excerpt": "The product did not shut down and is gaining traction."}, "FAILED_OR_SHRINKING_ATTEMPT"),
]
false_hits = []
for sample, cat in neg_samples:
    cats = p3.classify_counterevidence_candidate(sample)
    if cat in cats:
        false_hits.append({"text": sample["excerpt"], "false_category": cat, "all": cats})
check("P3 counterevidence direction/negation is bounded correctly", not false_hits, false_hits)

ev = [
    {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "buyer", "stance": "SUPPORT", "validated": True, "source_type": "VENDOR", "source_title": "Vendor docs A", "source_url": "https://vendor.example/a", "excerpt": "A"},
    {"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "buyer", "stance": "SUPPORT", "validated": True, "source_type": "VENDOR", "source_title": "Vendor docs B", "source_url": "https://vendor.example/b", "excerpt": "B"},
]
rep = p3.build_evidence_replay_from_rows(thesis={"thesis_id": "t", "claim_states": {"C05": "SUPPORTED"}}, evidence_rows=ev)
claim = next(x for x in rep["claims"] if x["claim_code"] == "C05")
check("P3 Evidence Replay fails closed on unknown source family", claim["independent_source_families"] == 0 and claim["unknown_source_family_links"] == 2, claim)

ev2 = ev + [{"claim_code": "C05", "claim_state": "SUPPORTED", "claim_statement": "buyer", "stance": "CONTRADICT", "validated": False, "source_type": "SHADOW", "source_title": "Shadow", "source_url": "https://shadow", "excerpt": "x"}]
rep2 = p3.build_evidence_replay_from_rows(thesis={"thesis_id": "t", "claim_states": {"C05": "SUPPORTED"}}, evidence_rows=ev2)
check("P3 Evidence Replay still excludes unvalidated links", rep2["summary"]["validated_evidence_links"] == 2, rep2["summary"])

trail = {"claim_states": {"C03": "SUPPORTED", "C05": "PARTIAL", "C07": "UNKNOWN", "C09": "SUPPORTED"}, "revenue_wedge": {"decision": "INVESTIGATE", "existing_spend": "PARTIAL"}, "paid_dissatisfaction": {"count": 1}, "published_evidence_count": 5}
disp = p3.evaluate_kill_advance_park(trail)
check("P3 fresh falsification cannot own disposition", disp["fresh_search_can_trigger_disposition"] is False and disp["current_disposition"] == "CONTINUE", disp["current_disposition"])

failed = p3.summarize_falsification_runs([{"falsification_theme": "X", "falsification_query": "q", "sources": [{"source": "A", "status": "FAILED", "count": 0, "transport": {}}], "traces": []}])
check("P3 all-search failure remains no-market-conclusion", failed["interpretation"] == "SEARCH_FAILED_NO_MARKET_CONCLUSION", failed["interpretation"])

passed = sum(1 for _, ok, _ in checks if ok)
failed_count = len(checks) - passed
print("-" * 100)
print(f"RESULT: {passed}/{len(checks)} PASS")
print(json.dumps({"total": len(checks), "pass": passed, "fail": failed_count}, ensure_ascii=False))
if failed_count:
    raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_PARTS1_3_FOUNDER_ACCEPTANCE_CLOSURE_PASS")
