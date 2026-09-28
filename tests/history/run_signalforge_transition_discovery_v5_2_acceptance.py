"""Deterministic engineering acceptance for SignalForge V5.2 discovery semantics.
No DB writes, no crawler, no LLM.
"""
from processors.transition_gap_discovery import classify_document
from processors.solo_transition_opportunity import assess_solo_transition


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{name}: {'PASS' if ok else 'FAIL'}" + (f" | {detail}" if detail else ""))
    if not ok:
        raise SystemExit(2)


print("=" * 108)
print("SIGNALFORGE V5.2 — CHANGE-FIRST DISCOVERY ACCEPTANCE")
print("No DB writes. No crawler. No LLM. No synthetic market outcome.")
print("=" * 108)

change = classify_document(
    "A real-time voice AI API is now available for production call handling and the provider released a public API.",
    "news",
)
check("CHANGE_SIGNAL_PREFILTER", change["has_change"], str(change))

lag = classify_document(
    "Independent dental clinic office managers manually answer appointment phone calls and spend 15 hours per week scheduling and re-entering booking data.",
    "community",
)
check("LEGACY_WORKFLOW_PREFILTER", lag["has_lag"] and lag["economic"], str(lag))

frontier = classify_document(
    "SGLang CUDA kernel regression causes KV cache corruption in distributed inference.",
    "github",
)
check("FRONTIER_NOT_CHANGE_OPPORTUNITY", not frontier["has_change"] and frontier["frontier"], str(frontier))

broad = classify_document("AI models are unreliable and hallucinate.", "community")
check("BROAD_AI_NOT_LAGGING_WORKFLOW", not broad["has_lag"], str(broad))

candidate = {
    "title": "Independent dental clinics manually handle appointment calls despite production voice APIs",
    "problem_statement": "Independent dental clinic office managers manually handle recurring appointment scheduling calls despite production voice APIs",
    "actor": "independent dental clinic office managers",
    "task": "handle inbound appointment scheduling calls",
    "object": "appointment scheduling workflow",
    "failure_mode": "staff manually answer repetitive appointment calls and re-enter booking data",
    "consequence": "15 hours per week spent on manual call handling and data entry",
    "buyer_context": "independent dental clinic practice manager",
    "workaround": "staff answer phone calls manually and re-enter bookings",
    "fingerprint": {
        "transition_evidence_verified": True,
        "change_signal": "production real-time voice API is now available",
        "legacy_workflow": "clinic staff still answer appointment calls and re-enter bookings manually",
        "transition_gap": "the concrete clinic workflow remains manual after the enabling API became available",
        "transition_evidence_refs": ["news:1", "community:2"],
    },
}
assessment = assess_solo_transition(
    candidate,
    claim_states={"C03": "SUPPORTED", "C05": "SUPPORTED", "C09": "SUPPORTED"},
    company_reality={"overall": "CAN_DO"},
    commercial_reality={},
    attention={},
)
check(
    "VERIFIED_PAIR_CAN_SUPPORT_TRANSITION",
    assessment.get("transition_gap") == "SUPPORTED" and assessment.get("classification") == "SOLO_INVESTIGATE",
    str(assessment),
)

bad = assess_solo_transition(
    {
        "title": "AI model output is unreliable",
        "problem_statement": "AI model output is unreliable",
        "actor": "users",
        "task": "use AI",
        "object": "AI model",
        "failure_mode": "unreliable",
        "consequence": "wasted time",
        "buyer_context": "unclear",
        "workaround": "none mentioned",
    },
    claim_states={"C03": "SUPPORTED", "C05": "SUPPORTED", "C07": "SUPPORTED", "C09": "SUPPORTED", "C12": "SUPPORTED"},
    company_reality={"overall": "CAN_DO"},
)
check("OLD_BROAD_AI_STILL_PARKED", bad.get("classification") == "RESEARCH_THEME", str(bad))

print("SIGNALFORGE_TRANSITION_GAP_DISCOVERY_V5_2_ACCEPTANCE_PASS")
