from __future__ import annotations

import asyncio
from pathlib import Path

from processors import signalforge_market_execution_learning as p6
from processors import signalforge_market_action_registry as mar
from processors import signalforge_market_learning_calibration as mlc

checks=[]
def check(name, ok, detail=None):
    checks.append((name,bool(ok),detail))


def base_thesis():
    return {
        "thesis_id":"rfq","representative_title":"RFQ Comparator","representative_problem":"Procurement teams manually normalize supplier quotes",
        "strategic_track":"BOTH","member_candidate_ids":[101],
        "founder_addressability":{"dimensions":{"buyer_access":{"state":"SUPPORTED"},"legitimacy":{"state":"SUPPORTED"},"right_to_win":{"state":"SUPPORTED"}},"trust_burden":"LOW"},
        "dimensions":{"distribution_leverage":{"state":"SUPPORTED"}},
        "best_next_action":{"mode":"MARKET_ACTION","action":"PAID_PILOT_OR_PREORDER_TEST"},
    }
trail={
    "buyer_segment":{"label":"procurement managers"},
    "possible_revenue_wedge":{"statement":"Normalize 5 RFQs"},
    "revenue_wedge":{"existing_spend":"STRONG","buyer_reachability":"STRONG","decision":"TRY_NOW"},
    "current_spend":{"observations":[{"bucket":"LABOR_SPEND"}]},
    "paid_dissatisfaction":{"count":2},
}

# 1. Part 4 actionability must gate formal Part 6 execution.
park_decision={"market_track":"PARK","current_track":"PARK","founder_action":"PARK","founder_actionability":{"gate_pass":False}}
park_design=p6.build_market_test_design_from_projection(base_thesis(),trail,park_decision)
check("p6.part4_park_blocks_execution", park_design.get("execution_authority",{}).get("allowed") is False, park_design.get("execution_authority"))
old_design=p6.design_market_test
async def fake_park_design(**kwargs): return park_design
p6.design_market_test=fake_park_design
blocked=False
try:
    asyncio.run(p6.preregister_market_test(thesis_id="rfq"))
except ValueError as exc:
    blocked="does not authorize" in str(exc) or "blocks" in str(exc)
finally:
    p6.design_market_test=old_design
check("p6.preregister_cannot_bypass_part4", blocked)

# 2. Paid action semantics are locked; likes cannot be the success metric.
action_now={"market_track":"BOTH","current_track":"BOTH","founder_action":"ACTION_NOW","founder_actionability":{"gate_pass":True}}
design=p6.build_market_test_design_from_projection(base_thesis(),trail,action_now)
likes_blocked=False
try:
    p6._override_rule(design,{"metric":"likes","success_min":1})
except ValueError as exc:
    likes_blocked="not valid" in str(exc)
check("p6.paid_test_cannot_use_likes_metric", likes_blocked, design.get("success"))

# 3 + 4. Paid PASS with zero paid commitments is not quality evidence; sample is derived from durable records.
quality_zero_paid=mar.market_action_outcome_quality({
    "status":"COMPLETED","result":"PASS","category":"MARKET_ACTION","action_type":"PAID_PILOT_OR_PREORDER_TEST",
    "sample_target":5,"decision_rule":{"metric":"paid_commitments","metric_family":"PAID_COMMITMENT"},
    "pretest_snapshot":{"thesis_id":"rfq"},
    "observations":{
        "observation_records":[{"actor_label":f"Buyer {i}","evidence_ref":f"note:{i}"} for i in range(5)],
        "observed_behavior":"Liked the idea","outcome_counts":{"paid_commitments":0},"amount":1,"currency":"USD",
    },
})
check("p6.zero_paid_commitments_not_eligible_paid_pass", not quality_zero_paid.get("eligible") and "PAID_TEST_PASS_REQUIRES_POSITIVE_PAID_COMMITMENT" in quality_zero_paid.get("reasons",[]), quality_zero_paid)
quality_fake_sample=mar.market_action_outcome_quality({
    "status":"COMPLETED","result":"PASS","category":"MARKET_ACTION","action_type":"PAID_PILOT_OR_PREORDER_TEST",
    "sample_target":5,"decision_rule":{"metric":"paid_commitments","metric_family":"PAID_COMMITMENT"},
    "pretest_snapshot":{"thesis_id":"rfq"},
    "observations":{
        "observed_sample_size":5,"observation_records":[{"actor_label":"Buyer A","evidence_ref":"receipt:a"}],
        "observed_behavior":"Paid","outcome_counts":{"paid_commitments":1},"amount":1,"currency":"USD",
    },
})
check("p6.sample_cannot_be_inflated_by_aggregate_number", not quality_fake_sample.get("eligible") and quality_fake_sample.get("observed_sample_size")==1, quality_fake_sample)

# 5. Pre-registered max cost is enforceable and a breach cannot be a clean PASS.
action_cost={"action_type":"PAID_PILOT_OR_PREORDER_TEST","sample_target":1,"max_cost":1000,"max_cost_currency":"TWD","decision_rule":{"metric":"paid_commitments","success_min":1,"sample_target":1}}
cost_eval=p6.evaluate_outcome_against_preregistered_rule(action_cost,{"paid_commitments":1},observed_sample_size=1,actual_cost=50000,actual_cost_currency="TWD")
check("p6.max_cost_breach_forces_inconclusive", cost_eval.get("result")=="INCONCLUSIVE" and cost_eval.get("cost_evaluation",{}).get("status")=="BREACHED", cost_eval)

# 6. Claim prereg options only expose executable prepared plans.
old_find=p6._find_action; old_report=p6.claim_validation_report
old_module=None
p6._find_action=lambda aid:{"action_id":aid,"status":"REGISTERED","action_type":"PAID_PILOT_OR_PREORDER_TEST","pretest_snapshot":{"member_candidate_ids":[101]}}
# monkeypatch the lazy import without importing the DB-backed module.
import sys, types
old_od_module=sys.modules.get("processors.opportunity_decision")
async def fake_decision(*args,**kwargs):
    return {"rows":[{"candidate_id":101,"case_id":901,"claims":{"C10":"UNKNOWN"},"prepared_validation_plans":{}}]}
fake_od=types.ModuleType("processors.opportunity_decision")
fake_od.run_opportunity_decision=fake_decision
sys.modules["processors.opportunity_decision"]=fake_od
p6.claim_validation_report=lambda:{"rows":[]}
try:
    opts=asyncio.run(p6.claim_preregistration_options("a1"))
finally:
    p6._find_action=old_find; p6.claim_validation_report=old_report
    if old_od_module is None: sys.modules.pop("processors.opportunity_decision",None)
    else: sys.modules["processors.opportunity_decision"]=old_od_module
check("p6.claim_options_require_prepared_plan", opts.get("items")==[] and opts.get("status")=="NO_ATOMIC_PREREGISTRATION_OPTION", opts)

# 7. A paid pilot with zero observed switches cannot promote C14.
old_find=p6._find_action; old_report=p6.claim_validation_report
p6._find_action=lambda aid:{
    "action_id":aid,"status":"COMPLETED","result":"PASS","action_type":"PAID_PILOT_OR_PREORDER_TEST","thesis_id":"rfq",
    "completed_at":"2026-09-06T01:00:00","pretest_snapshot":{"member_candidate_ids":[101]},
    "observations":{"outcome_counts":{"paid_commitments":1,"switches":0},"actor_labels":["Buyer A"],"actor_label":"Buyer A","amount":100,"currency":"USD"},
}
p6.claim_validation_report=lambda:{"rows":[{"experiment_id":"e14","market_action_id":"a1","case_id":1,"claim_code":"C14","event":"SWITCH","status":"PENDING","created_at":"2026-09-06T00:00:00","pretest_snapshot":{"candidate_id":101,"strategic_snapshot":{"thesis_id":"rfq"}}}]}
try:
    po=p6.promotion_options("a1")
finally:
    p6._find_action=old_find; p6.claim_validation_report=old_report
check("p6.paid_pilot_does_not_imply_switch", not po.get("items") and any(x.get("reason")=="OBSERVED_SWITCH_BEHAVIOR_REQUIRED" for x in po.get("excluded",[])), po)

# 8. Repeated actions from one thesis are one independent calibration entity.
rows=[]
common_true={"paid_dissatisfaction_present":True,"existing_spend_present":True,"manual_labor_spend_present":True,"distribution_gate_pass":True,"market_track":"BOTH","founder_action":"ACTION_NOW","calibration_domain":"FAST_VALIDATION","action_semantic_family":"PAID_COMMITMENT"}
common_false={**common_true,"paid_dissatisfaction_present":False}
for i in range(8):
    rows.append({"action_id":f"same-{i}","thesis_id":"same-thesis","result":"PASS","action_type":"PAID_PILOT","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"PAID_COMMITMENT"},"learning_features":common_true})
for i in range(8):
    rows.append({"action_id":f"other-{i}","thesis_id":f"other-{i%5}","result":"FAIL","action_type":"PAID_PILOT","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"PAID_COMMITMENT"},"learning_features":common_false})
rep=mlc.market_learning_calibration_report(rows,domain="FAST_VALIDATION",semantic_family="PAID_COMMITMENT")
seg=rep.get("segments",{}).get("PAID_COMMITMENT",{})
true_row=next((x for x in seg.get("features",{}).get("paid_dissatisfaction_present",[]) if x.get("bucket")=="TRUE"),{})
check("p6.repeated_same_thesis_cannot_create_independence", true_row.get("entities")==1 and true_row.get("ranking_adjustment")=="UNVALIDATED", true_row)

# 9. Founder discovery is domain-isolated and never changes market ranking.
fd_rows=[]
for i in range(8):
    fd_rows.append({"thesis_id":f"fdp-{i}","result":"PASS","category":"FOUNDER_DISCOVERY","action_type":"IDENTIFY_REACHABLE_BUYER_CHANNEL","eligible_domains":["FOUNDER_ADDRESSABILITY"],"outcome_quality":{"eligible_domains":["FOUNDER_ADDRESSABILITY"],"semantic_family":"FOUNDER_BUYER_ACCESS"},"learning_features":{"distribution_gate_pass":True,"calibration_domain":"FOUNDER_ADDRESSABILITY","action_semantic_family":"FOUNDER_BUYER_ACCESS"}})
for i in range(8):
    fd_rows.append({"thesis_id":f"fdf-{i}","result":"FAIL","category":"FOUNDER_DISCOVERY","action_type":"IDENTIFY_REACHABLE_BUYER_CHANNEL","eligible_domains":["FOUNDER_ADDRESSABILITY"],"outcome_quality":{"eligible_domains":["FOUNDER_ADDRESSABILITY"],"semantic_family":"FOUNDER_BUYER_ACCESS"},"learning_features":{"distribution_gate_pass":False,"calibration_domain":"FOUNDER_ADDRESSABILITY","action_semantic_family":"FOUNDER_BUYER_ACCESS"}})
market_rep=mlc.market_learning_calibration_report(fd_rows)
adj=mlc.calibration_adjustment_for_features({"distribution_gate_pass":True,"calibration_domain":"FOUNDER_ADDRESSABILITY","action_semantic_family":"FOUNDER_BUYER_ACCESS"}, mlc.market_learning_calibration_report(fd_rows,domain="FOUNDER_ADDRESSABILITY",semantic_family="FOUNDER_BUYER_ACCESS"))
check("p6.founder_discovery_not_market_calibration", market_rep.get("eligible_outcomes")==0 and not adj.get("applied_to_ranking"), (market_rep,adj))

# 10. Different target variables/action semantics are not mixed into one success rate.
mixed=[]
for i in range(8):
    mixed.append({"thesis_id":f"paid-{i}","result":"PASS","action_type":"PAID_PILOT","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"PAID_COMMITMENT"},"learning_features":{"existing_spend_present":True,"calibration_domain":"FAST_VALIDATION","action_semantic_family":"PAID_COMMITMENT"}})
for i in range(8):
    mixed.append({"thesis_id":f"outreach-{i}","result":"FAIL","action_type":"OUTREACH","eligible_domains":["FAST_VALIDATION"],"outcome_quality":{"eligible_domains":["FAST_VALIDATION"],"semantic_family":"QUALIFIED_RESPONSE"},"learning_features":{"existing_spend_present":False,"calibration_domain":"FAST_VALIDATION","action_semantic_family":"QUALIFIED_RESPONSE"}})
mixrep=mlc.market_learning_calibration_report(mixed)
check("p6.calibration_separates_action_semantics", set(mixrep.get("segments",{}))=={"PAID_COMMITMENT","QUALIFIED_RESPONSE"} and not mixrep.get("actionable_adjustments"), mixrep.get("segments"))

# Underlying truth writer is claim-specific: PAID_PILOT can no longer fan out to C14.
gt=Path("processors/market_ground_truth.py").read_text(encoding="utf-8")
check("p6.market_ground_truth_paid_pilot_not_composite_switch", 'registered_claim in {"C10", "C11"}' in gt and 'claim_codes = (registered_claim,)' in gt, None)

print("="*116)
print("SIGNALFORGE PART 6 SEMANTIC / CALIBRATION CLOSURE — INDEPENDENT ADVERSARIAL ACCEPTANCE")
print("="*116)
for n,ok,d in checks:
    print(("PASS" if ok else "FAIL").ljust(6), n, ("— "+str(d)[:900]) if d not in (None,"") else "")
print("-"*116)
passed=sum(x[1] for x in checks)
print(f"RESULT: {passed}/{len(checks)} PASS")
if passed != len(checks): raise SystemExit(1)
print("FINAL_STATUS: SIGNALFORGE_PART6_SEMANTIC_CLOSURE_ACCEPTANCE_PASS")
