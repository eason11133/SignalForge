from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _stub_database() -> None:
    if "database.connection" in sys.modules:
        return
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")

    class Dummy:
        id = candidate_id = claim_id = evidence_id = case_id = None

    async def _session():  # pragma: no cover - never used by pure acceptance
        raise RuntimeError("DB stub should not be used")

    for name in (
        "ProblemCandidate", "RadarCase", "RadarClaim", "RadarClaimEvidence", "RadarEvidence",
    ):
        setattr(conn, name, Dummy)
    conn.async_session = _session
    sys.modules["database.connection"] = conn
    setattr(db_pkg, "connection", conn)


def check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, bool(ok), detail


def main() -> int:
    _stub_database()
    mt = importlib.import_module("processors.signalforge_money_trail")
    results: list[tuple[str, bool, str]] = []

    paid_row = {
        "claim_code": "C06", "claim_state": "SUPPORTED", "stance": "SUPPORT",
        "source_type": "REDDIT", "source_title": "Agency owner on review tooling",
        "excerpt": "We pay $200/month for the review tool but still have to manually QA every client delivery.",
        "source_family_key": "reddit:agency-1", "source_url": "https://example.invalid/1",
        "raw_metadata": {"tool": "ReviewTool"},
    }
    spend = mt.classify_spend_evidence(paid_row)
    results.append(check("direct paid evidence classified", any(x["bucket"] == "VENDOR_SPEND" and x["evidence_grade"] == "OBSERVED" for x in spend)))
    results.append(check("manual labor evidence classified", any(x["bucket"] == "LABOR_SPEND" for x in spend)))
    results.append(check("amount preserved, not estimated", any("$200/month" in x.get("amount_mentions", []) for x in spend)))
    results.append(check("paid dissatisfaction requires pay+dissatisfaction", mt.detect_paid_dissatisfaction(paid_row) is not None))
    results.append(check("ordinary complaint is not paid dissatisfaction", mt.detect_paid_dissatisfaction({"excerpt": "this is slow and annoying", "source_title": "complaint"}) is None))

    strong_spend = [
        {"evidence_grade": "OBSERVED", "source_family_key": "a", "bucket": "VENDOR_SPEND"},
        {"evidence_grade": "OBSERVED", "source_family_key": "b", "bucket": "LABOR_SPEND"},
    ]
    supported = {"C03": "SUPPORTED", "C05": "SUPPORTED", "C07": "SUPPORTED", "C09": "SUPPORTED", "C13": "SUPPORTED"}
    addr = {"trust_burden": "LOW_TO_MEDIUM", "hard_blocked": False, "dimensions": {"buyer_access": {"state": "SUPPORTED"}, "right_to_win": {"state": "SUPPORTED"}}}
    wedge = mt.build_revenue_wedge_projection(claim_states=supported, founder_addressability=addr, spend_items=strong_spend, paid_dissatisfaction=[{"x": 1}], current_solutions=["X"])
    results.append(check("revenue wedge can say TRY_NOW only with strong conditions", wedge["decision"] == "TRY_NOW"))
    results.append(check("revenue wedge has no fake numeric score", wedge.get("score") is None))
    killed = mt.build_revenue_wedge_projection(claim_states={**supported, "C07": "REFUTED"}, founder_addressability=addr, spend_items=strong_spend, paid_dissatisfaction=[], current_solutions=[])
    results.append(check("refuted critical gate kills wedge", killed["decision"] == "KILL"))

    trail = mt.build_money_trail_from_rows(
        thesis={
            "thesis_id": "t1", "representative_title": "AI delivery acceptance",
            "representative_problem": "AI-heavy agencies still manually verify client delivery",
            "claim_states": supported, "member_candidate_ids": [1],
            "founder_addressability": addr,
        },
        candidate_rows=[{"actor": "AI agency owner", "buyer_context": "client delivery agency"}],
        evidence_rows=[paid_row, {**paid_row, "source_family_key": "jobs:agency-2", "excerpt": "Senior engineer review time is still manual QA before client handoff."}],
        market_action={
            "action_type": "IDENTIFY_REACHABLE_BUYER_CHANNEL",
            "template": {"default_sample": 10, "success_signal": "at least one repeatable channel reaches qualified target buyers", "failure_signal": "no reachable qualified buyer channel after bounded channel probes", "cost_class": "LOW"},
        },
    )
    results.append(check("buyer segment kept separate", trail["buyer_segment"]["key"] == "AI_HEAVY_AGENCIES"))
    results.append(check("money trail never creates numeric estimate", trail["current_spend"]["numeric_estimate_created"] is False))
    results.append(check("paid dissatisfaction surfaced", trail["paid_dissatisfaction"]["count"] >= 1))
    results.append(check("possible wedge explicitly hypothesis", trail["possible_revenue_wedge"]["status"] == "HYPOTHESIS"))
    results.append(check("founder playbook has channels", len(trail["founder_playbook"]["channels"]) >= 3))
    results.append(check("founder playbook has five behavior questions", len(trail["founder_playbook"]["questions"]) == 5))
    results.append(check("cheapest test preserved bounded sample", trail["cheapest_test"]["sample_target"] == 10))

    source = (ROOT / "processors/signalforge_money_trail.py").read_text(encoding="utf-8")
    route = (ROOT / "api/routes/signalforge.py").read_text(encoding="utf-8")
    ui = (ROOT / "dashboard/src/pages/MoneyTrail.tsx").read_text(encoding="utf-8")
    app = (ROOT / "dashboard/src/App.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "dashboard/src/components/Sidebar.tsx").read_text(encoding="utf-8")

    results.append(check("money trail module has truth boundary", "never" in source.lower() and "MARKET_TRUTH" in source))
    results.append(check("no direct Radar mutation API in money trail", "update(RadarClaim" not in source and "delete(RadarClaim" not in source and "add(RadarClaim" not in source))
    results.append(check("portfolio endpoint exists", "@router.get('/money-trails')" in route))
    results.append(check("read-only direction probe exists", "@router.post('/money-trails/probe')" in route and "READ_ONLY" in source))
    results.append(check("founder homepage asks where money is", "今天哪一筆錢最值得去拿" in ui))
    results.append(check("spend reconstruction visible", "錢現在花在哪" in ui))
    results.append(check("paid dissatisfaction visible", "已經花錢還在不爽什麼" in ui))
    results.append(check("self-serve playbook visible", "不用問我，照這個做" in ui))
    results.append(check("self-serve result recording visible", "做完就直接在這裡記結果" in ui))
    results.append(check("MoneyTrail is default route", '<Route index element={<MoneyTrail />} />' in app))
    results.append(check("old opportunity workbench still reachable", 'path="opportunities" element={<OpportunityRadar />}' in app))
    results.append(check("sidebar product hierarchy changed", "今天錢在哪" in sidebar and "商機工作台" in sidebar))

    failed = [x for x in results if not x[1]]
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))
    print(f"\nRESULT: {len(results)-len(failed)}/{len(results)} PASS")
    if failed:
        return 1
    print("FINAL_STATUS: SIGNALFORGE_MONEY_TRAIL_REVENUE_WEDGE_PRODUCT_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
