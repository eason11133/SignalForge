from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from processors import signalforge_market_action_registry as mar
from processors import validation_registry as vr
from processors import signalforge_market_execution_learning as p6
from processors import signalforge_market_learning_calibration as mlc
from processors import signalforge_opportunity_decision_closure as p4c

checks: list[tuple[str, bool, object]] = []
def check(name: str, ok: bool, detail: object = ""):
    checks.append((name, bool(ok), detail))


def thesis(tid="rfq"):
    return {
        "thesis_id": tid,
        "revision": 3,
        "representative_title": "RFQ Comparator",
        "representative_problem": "Procurement teams manually normalize supplier quotes",
        "strategic_track": "BOTH",
        "classification": "OPPORTUNITY",
        "zip2_readiness": "PARTIAL",
        "member_candidate_ids": [101],
        "claim_states": {"C10":"UNKNOWN","C11":"UNKNOWN","C14":"UNKNOWN"},
        "dimensions": {"distribution_leverage":{"state":"SUPPORTED"}},
        "founder_addressability": {"first_person_addressability_state":"SUPPORTED","dimensions":{"buyer_access":{"state":"SUPPORTED"},"legitimacy":{"state":"SUPPORTED"},"right_to_win":{"state":"SUPPORTED"}},"trust_burden":"LOW"},
        "fast_validation": {"state":"READY"},
        "best_next_action": {"mode":"MARKET_ACTION","action":"PAID_PILOT_OR_PREORDER_TEST","reason":"WTP is the decision-critical unknown"},
    }

trail = {
    "buyer_segment":{"label":"SMB procurement managers"},
    "possible_revenue_wedge":{"status":"HYPOTHESIS","statement":"Upload 5 quotes and receive a normalized comparison"},
    "revenue_wedge":{"existing_spend":"STRONG","buyer_reachability":"STRONG","decision":"TRY_NOW"},
    "current_spend":{"observations":[{"bucket":"LABOR_SPEND"}]},
    "paid_dissatisfaction":{"count":2},
    "cheapest_test":{"instruction":"Show a quote-normalization prototype to qualified procurement managers"},
    "founder_playbook":{"channels":["LinkedIn procurement groups","existing buyer referrals"],"questions":["Show me the last RFQ you normalized manually."]},
}
decision = {
    "market_track":"BOTH",
    "founder_action":"ACTION_NOW",
    "founder_actionability":{"gate_pass":True},
    "current_track":"BOTH",
}

# 6.1 test designer
D = p6.build_market_test_design_from_projection(thesis(), trail, decision)
check("designer.has_hypothesis", bool(D.get("hypothesis")), D.get("hypothesis"))
check("designer.has_target", D.get("target") == "SMB procurement managers", D.get("target"))
check("designer.has_test", D.get("test",{}).get("action_type") == "PAID_PILOT_OR_PREORDER_TEST", D.get("test"))
check("designer.has_success_failure_inconclusive", all(D.get(k) for k in ("success","failure","inconclusive")))
check("designer.no_fake_numeric_budget", D.get("max_cost") is None and str(D.get("cost_boundary")).startswith("NOT_SET"), D.get("cost_boundary"))
check("designer.rule_is_preregistration_heuristic", "NOT_MARKET_TRUTH" in str(D.get("success",{}).get("decision_rule",{}).get("authority")), D.get("success"))
check("designer.atomic_promotion_requires_prereg", bool(D.get("atomic_promotion_hint",{}).get("requires_claim_specific_preregistration_before_outcome")), D.get("atomic_promotion_hint"))

# 6.3 buyer pack
P = D.get("buyer_outreach_pack") or {}
check("outreach.who_where", bool(P.get("who")) and bool(P.get("where")), P)
check("outreach.ask_not_say_capture", bool(P.get("what_to_ask")) and bool(P.get("what_not_to_say")) and bool(P.get("evidence_to_capture")), P)
check("outreach.rejects_interest_as_wtp", any("interest" in str(x).lower() for x in P.get("what_not_to_say") or []), P.get("what_not_to_say"))

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    old_reg, old_lock = mar.REGISTRY_PATH, mar.REGISTRY_LOCK_PATH
    old_vreg, old_vlock = vr.REGISTRY_PATH, vr.REGISTRY_LOCK_PATH
    mar.REGISTRY_PATH, mar.REGISTRY_LOCK_PATH = root/"actions.jsonl", root/"actions.lock"
    vr.REGISTRY_PATH, vr.REGISTRY_LOCK_PATH = root/"validation.jsonl", root/"validation.lock"
    old_brain = mar._brain_portfolio
    mar._brain_portfolio = lambda root=None: {"status":"PASS","portfolio":[thesis()]}
    try:
        # 6.2 preregistration freezes rule/features; no market truth
        rec = mar.register_market_action(
            thesis_id="rfq", action_type="PAID_PILOT_OR_PREORDER_TEST", sample_target=5,
            success_criteria="At least one real paid commitment", failure_criteria="No qualified buyer pays after sample exhausted",
            part6_test_design=D, decision_rule={"metric":"paid_commitments","success_min":1,"sample_target":5,"authority":"FOUNDER_CONFIRMED_PREREGISTERED_RULE"},
            inconclusive_criteria="Sample incomplete", buyer_outreach_pack=P, learning_features=D.get("learning_features") or {},
        )
        check("preregistration.freezes_rule", rec.get("decision_rule",{}).get("success_min") == 1, rec.get("decision_rule"))
        check("preregistration.freezes_learning_features", rec.get("pretest_snapshot",{}).get("part6_learning_features",{}).get("paid_dissatisfaction_present") is True, rec.get("pretest_snapshot"))
        check("preregistration.market_truth_zero", "WRITES_NO_RADAR_OR_MARKET_TRUTH" in str(rec.get("truth_boundary") or ""), rec.get("truth_boundary"))

        # Part 6 claim preregistration is durably bound to this exact Market Action.
        old_opts = p6.claim_preregistration_options
        old_register_claim = p6.register_claim_validation
        prereg_called = {}
        async def fake_opts(action_id):
            return {"items":[{"case_id":901,"claim_code":"C10","already_pending":False}]}
        async def fake_register_claim(**kwargs):
            prereg_called.update(kwargs); return {"experiment_id":"bound-exp","market_action_id":kwargs.get("market_action_id")}
        p6.claim_preregistration_options = fake_opts
        p6.register_claim_validation = fake_register_claim
        try:
            bound = asyncio.run(p6.preregister_claim_for_action(action_id=rec["action_id"], case_id=901, claim_code="C10"))
        finally:
            p6.claim_preregistration_options = old_opts
            p6.register_claim_validation = old_register_claim
        check("preregistration.claim_experiment_bound_to_exact_action", prereg_called.get("market_action_id") == rec["action_id"] and bound.get("experiment",{}).get("market_action_id") == rec["action_id"], prereg_called)

        old_opts = p6.claim_preregistration_options
        async def fake_duplicate_opts(action_id):
            return {"items":[{"case_id":901,"claim_code":"C10","already_pending":True}]}
        p6.claim_preregistration_options = fake_duplicate_opts
        duplicate_blocked = False
        try:
            asyncio.run(p6.preregister_claim_for_action(action_id=rec["action_id"], case_id=901, claim_code="C10"))
        except ValueError as exc:
            duplicate_blocked = "already has a pending experiment" in str(exc)
        finally:
            p6.claim_preregistration_options = old_opts
        check("preregistration.duplicate_same_action_claim_blocked", duplicate_blocked)

        # 6.4 outcome result comes from frozen rule, no result override.
        incomplete = p6.evaluate_outcome_against_preregistered_rule(rec, {"contacted":3,"paid_commitments":1})
        check("outcome.incomplete_is_inconclusive_even_if_metric_hit", incomplete.get("result") == "INCONCLUSIVE", incomplete)
        passed = p6.evaluate_outcome_against_preregistered_rule(rec, {"contacted":5,"paid_commitments":1})
        failed = p6.evaluate_outcome_against_preregistered_rule(rec, {"contacted":5,"paid_commitments":0})
        check("outcome.frozen_rule_pass", passed.get("result") == "PASS", passed)
        check("outcome.frozen_rule_fail", failed.get("result") == "FAIL", failed)
        check("outcome.no_retrospective_override", passed.get("retrospective_result_override_allowed") is False, passed)

        captured = p6.capture_market_outcome(
            action_id=rec["action_id"], outcome_counts={"contacted":5,"paid_commitments":1},
            actor_labels=[f"Procurement Manager {x}" for x in "ABCDE"], evidence_refs=[f"receipt://pilot-{i:03d}" for i in range(1,6)],
            observed_behavior="Signed and paid for bounded pilot", decision_relevant_findings="Manual quote normalization remains active",
            amount=3000, currency="TWD",
        )
        check("outcome.capture_uses_computed_result", captured.get("action",{}).get("result") == "PASS", captured)
        check("outcome.capture_does_not_auto_promote", captured.get("atomic_market_truth_promoted") is False and captured.get("market_truth_writes") == 0, captured)
        check("outcome.capture_preserves_counts", captured.get("action",{}).get("observations",{}).get("outcome_counts",{}).get("paid_commitments") == 1, captured)

        # 6.5 promotion only if claim experiment predates outcome and matches thesis/candidate.
        completed = captured["action"]
        created_before = "2026-09-01T00:00:00"
        created_after = "2099-01-01T00:00:00"
        rows = [
            {"experiment_id":"exp-before","market_action_id":rec["action_id"],"case_id":901,"claim_code":"C10","event":"ACQUISITION","status":"PENDING","created_at":created_before,"pretest_snapshot":{"candidate_id":101,"strategic_snapshot":{"thesis_id":"rfq"}}},
            {"experiment_id":"exp-after","market_action_id":rec["action_id"],"case_id":901,"claim_code":"C10","event":"ACQUISITION","status":"PENDING","created_at":created_after,"pretest_snapshot":{"candidate_id":101,"strategic_snapshot":{"thesis_id":"rfq"}}},
            {"experiment_id":"exp-wrong-thesis","market_action_id":rec["action_id"],"case_id":902,"claim_code":"C10","event":"ACQUISITION","status":"PENDING","created_at":created_before,"pretest_snapshot":{"candidate_id":101,"strategic_snapshot":{"thesis_id":"other"}}},
            {"experiment_id":"exp-other-action","market_action_id":"different-action","case_id":901,"claim_code":"C10","event":"ACQUISITION","status":"PENDING","created_at":created_before,"pretest_snapshot":{"candidate_id":101,"strategic_snapshot":{"thesis_id":"rfq"}}},
        ]
        vr.REGISTRY_PATH.write_text("\n".join(json.dumps(x) for x in rows)+"\n",encoding="utf-8")
        opts = p6.promotion_options(rec["action_id"])
        ids = {x.get("experiment_id") for x in opts.get("items") or []}
        check("promotion.preoutcome_only", ids == {"exp-before"}, opts)
        check("promotion.cross_action_experiment_excluded", "exp-other-action" not in ids, opts)
        check("promotion.explicit_founder_action", all(x.get("explicit_founder_promotion_required") for x in opts.get("items") or []), opts)
        check("promotion.no_retroactive_prereg", "NO_RETROACTIVE" in str(opts.get("truth_boundary")), opts.get("truth_boundary"))

        # Delegate promotion to existing validation workflow, never direct writer.
        called = {}
        async def fake_record(**kwargs):
            called.update(kwargs); return {"market_result":{"updated_claims":[{"claim_code":"C10","state":"SUPPORTED"}]}}
        old_record = p6.record_claim_validation_outcome
        p6.record_claim_validation_outcome = fake_record
        try:
            promoted = asyncio.run(p6.promote_market_outcome(action_id=rec["action_id"], experiment_id="exp-before"))
        finally:
            p6.record_claim_validation_outcome = old_record
        check("promotion.delegates_existing_authority", called.get("experiment_id") == "exp-before" and promoted.get("direct_part6_market_truth_writer") is False, promoted)
    finally:
        mar._brain_portfolio = old_brain
        mar.REGISTRY_PATH, mar.REGISTRY_LOCK_PATH = old_reg, old_lock
        vr.REGISTRY_PATH, vr.REGISTRY_LOCK_PATH = old_vreg, old_vlock

# 6.6 calibration: zero stays unvalidated.
zero = mlc.market_learning_calibration_report([])
check("calibration.zero_remains_unvalidated", zero.get("status") == "UNVALIDATED" and zero.get("general_predictive_accuracy") == "UNVALIDATED", zero)

# Strong prospective contrast can become a transparent feature-level tie-breaker.
rows=[]
for i in range(8):
    rows.append({"action_id":f"p{i}","thesis_id":f"paid-{i}","result":"PASS","action_type":"PAID_PILOT","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"PAID_COMMITMENT"},"learning_features":{"paid_dissatisfaction_present":True,"existing_spend_present":True,"manual_labor_spend_present":True,"distribution_gate_pass":True,"market_track":"BOTH","founder_action":"ACTION_NOW","calibration_domain":"FAST_VALIDATION","action_semantic_family":"PAID_COMMITMENT"}})
for i in range(8):
    rows.append({"action_id":f"f{i}","thesis_id":f"nopaid-{i}","result":"FAIL","action_type":"PAID_PILOT","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"PAID_COMMITMENT"},"learning_features":{"paid_dissatisfaction_present":False,"existing_spend_present":False,"manual_labor_spend_present":False,"distribution_gate_pass":False,"market_track":"BOTH","founder_action":"ACTION_NOW","calibration_domain":"FAST_VALIDATION","action_semantic_family":"PAID_COMMITMENT"}})
report=mlc.market_learning_calibration_report(rows)
paid_true=next(x for x in report["features"]["paid_dissatisfaction_present"] if x["bucket"]=="TRUE")
paid_false=next(x for x in report["features"]["paid_dissatisfaction_present"] if x["bucket"]=="FALSE")
check("calibration.prospective_signal_can_upweight", paid_true.get("ranking_adjustment") == "UPWEIGHT", paid_true)
check("calibration.prospective_signal_can_downweight", paid_false.get("ranking_adjustment") == "DOWNWEIGHT", paid_false)
check("calibration.still_no_general_accuracy", report.get("general_predictive_accuracy") == "UNVALIDATED", report.get("general_predictive_accuracy"))

# Part 4 feedback is discrete/transparent and comes after Founder actionability.
up={"founder_action":"ACTION_NOW","rank":1,"title":"up","market_learning_calibration":{"adjustment":"UPWEIGHT"}}
down={"founder_action":"ACTION_NOW","rank":1,"title":"down","market_learning_calibration":{"adjustment":"DOWNWEIGHT"}}
check("calibration.future_ranking_consumes_validated_tiebreaker", p4c._action_rank(up) < p4c._action_rank(down), (p4c._action_rank(up),p4c._action_rank(down)))
source = Path("processors/signalforge_opportunity_decision_closure.py").read_text(encoding="utf-8")
check("calibration.ranking_method_transparent", "VALIDATED_MARKET_LEARNING_TIEBREAKER" in source and "opaque" in source.lower())

# Source/API/UI authority and product surface checks.
p6src=Path("processors/signalforge_market_execution_learning.py").read_text(encoding="utf-8")
routes=Path("api/routes/signalforge.py").read_text(encoding="utf-8")
client=Path("dashboard/src/api/client.ts").read_text(encoding="utf-8")
hooks=Path("dashboard/src/api/hooks.ts").read_text(encoding="utf-8")
page=Path("dashboard/src/pages/MarketExecution.tsx").read_text(encoding="utf-8")
app=Path("dashboard/src/App.tsx").read_text(encoding="utf-8")
sidebar=Path("dashboard/src/components/Sidebar.tsx").read_text(encoding="utf-8")
check("source.part6_has_no_direct_market_ground_truth_import", "from processors.market_ground_truth import" not in p6src and "record_market_result(" not in p6src)
check("source.part6_uses_existing_validation_workflow", "record_claim_validation_outcome" in p6src and "register_claim_validation" in p6src)
check("api.full_execution_surface", all(x in routes for x in ("/market-execution/design","/market-execution/preregister","/capture","/promotion-options","/promote","/market-execution/calibration")))
check("client_hooks.full_execution_surface", all(x in client+hooks for x in ("designSignalForgeMarketTest","preregisterSignalForgeMarketTest","captureSignalForgeMarketOutcome","promoteSignalForgeMarketOutcome","useSignalForgeMarketLearningCalibration")))
check("ui.no_result_dropdown", "result dropdown" in page and "Outcome" in page and "Pre-register" in page)
check("ui.explicit_promotion", "Eligible Evidence Promotion" in page and "Promote" in page)
check("ui.route_sidebar", 'path="execute"' in app and 'to: "/execute"' in sidebar)

print("="*108)
print("SIGNALFORGE PART 6 — MARKET EXECUTION & LEARNING — FOUNDER ACCEPTANCE")
print("="*108)
for name, ok, detail in checks:
    print(("PASS" if ok else "FAIL").ljust(6), name, ("— "+str(detail)[:500]) if detail not in ("",None) else "")
passed=sum(ok for _,ok,_ in checks)
print("-"*108)
print(f"RESULT: {passed}/{len(checks)} PASS")
if passed != len(checks):
    raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_MARKET_EXECUTION_LEARNING_PART6_ACCEPTANCE_PASS")
