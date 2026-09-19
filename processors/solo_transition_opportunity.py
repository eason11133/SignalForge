"""SignalForge Solo-Founder Transition Gap Gate.

Purpose
-------
SignalForge should not rank the world's hardest problems as Founder opportunities.
This module is a deterministic, evidence-bound gate that distinguishes:

* RESEARCH_THEME: important/broad/frontier problem, not a current solo-founder opportunity.
* SOLO_WATCH: a sufficiently atomic problem, but one or more buyer/transition/economic gates remain unknown.
* SOLO_INVESTIGATE: a concrete transition/adoption gap with a plausible solo capture path.
* SOLO_VALIDATE: the same, with the existing reality gates strong enough for a customer validation test.

It never invents a product, buyer, willingness-to-pay, transition, or solution. UNKNOWN stays UNKNOWN.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

ENGINE_VERSION = "solo-transition-opportunity-v2-change-first-evidence"

UNCLEAR_VALUES = {
    "", "unknown", "unclear", "none", "none mentioned", "n/a", "na",
    "specific user/group or unclear", "specific user or group or unclear",
}

# These do not mean the market problem is unimportant. They mean the stated
# problem sits at a frontier/foundational layer that a generic solo software
# founder should not be told is directly captureable without explicit company truth.
FRONTIER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brocm\b|\bcuda\b|\bcudagraph\b|\baiter\b", "GPU_KERNEL_OR_RUNTIME_ENGINEERING"),
    (r"\bvllm\b|\bsglang\b|\btensor parallel\b|\bexpert parallel\b|\bdisaggregated serving\b", "DISTRIBUTED_LLM_SERVING"),
    (r"\bspeculative decoding\b|\bkv cache\b|\bkernel\b|\btriton\b", "LOW_LEVEL_INFERENCE_ENGINEERING"),
    (r"\btrain(?:ing)? (?:a |the )?(?:foundation )?model\b|\bpretrain", "FOUNDATION_MODEL_RESEARCH"),
    (r"\bmodel alignment\b|\bemergent misalignment\b|\bmechanistic interpret", "MODEL_RESEARCH"),
    (r"\bcausal genetics\b|\bmendelian randomization\b|\bcolocalization\b|\bpharmacovigilance\b", "SPECIALIZED_BIOMEDICAL_RESEARCH"),
)

BROAD_PROBLEM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^ai model(?:s)? (?:do(?:es)? not|doesn't) produce reliable outputs?$", "BROAD_AI_RELIABILITY"),
    (r"^ai model output(?:s)? (?:is|are) unreliable$", "BROAD_AI_RELIABILITY"),
    (r"^ai model assumptions? lead to incorrect outputs?$", "BROAD_MODEL_ASSUMPTIONS"),
    (r"^ai (?:is|isn't|is not) reliable$", "BROAD_AI_RELIABILITY"),
    (r"^llm hallucinations?$", "BROAD_HALLUCINATION"),
    (r"^model reliability$", "BROAD_MODEL_RELIABILITY"),
    (r"^incorrect outputs?$", "BROAD_OUTPUT_QUALITY"),
)

PHENOMENON_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"over[- ]reliance|too dependent|dependence on (?:ai|tools)|skill gap|getting dumber", "BEHAVIOR_OR_SKILL_PHENOMENON"),
    (r"people (?:are|become)|users (?:are|become).*(?:lazy|dependent)", "BEHAVIOR_OR_SKILL_PHENOMENON"),
)

REGULATED_PATTERNS = re.compile(
    r"\b(?:clinical|patient|diagnosis|medical device|hipaa|banking core|securities trading|legal advice|critical infrastructure)\b",
    re.I,
)
PHYSICAL_PATTERNS = re.compile(
    r"\b(?:manufacturing line|warehouse robotics|hardware installation|physical installation|construction|vehicle fleet|robotics hardware)\b",
    re.I,
)

MATERIAL_CONSEQUENCE_PATTERNS = re.compile(
    r"\b(?:hours?|days?|minutes?|cost|spend|waste|lost|loss|revenue|sales|churn|delay|blocked|downtime|failed deploy|manual|headcount|labor|labour|fine|penalt|refund|conversion|backlog|rework)\b",
    re.I,
)

GENERIC_ACTORS = {
    "users", "user", "people", "developers", "developer", "engineers", "engineer",
    "businesses", "business", "companies", "company", "teams", "team",
    "specific user/group", "specific users/groups",
}
GENERIC_TASKS = {
    "use ai", "use ai tools", "use software", "coding", "debugging code", "run ai models locally",
}
GENERIC_FAILURES = {
    "unreliable", "incorrect outputs", "wrong outputs", "does not work", "doesn't work",
    "model assumptions", "poor performance", "bad quality", "skill gap",
}


def _field(candidate: Any, name: str, default: Any = "") -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _low(value: Any) -> str:
    return _clean(value).lower()


def _known(value: Any) -> bool:
    return _low(value) not in UNCLEAR_VALUES


def _claim(claims: Mapping[str, Any] | None, code: str) -> str:
    raw = (claims or {}).get(code, "UNKNOWN")
    if hasattr(raw, "state"):
        raw = getattr(raw, "state", "UNKNOWN")
    return str(raw or "UNKNOWN").upper()


def _all_text(candidate: Any) -> str:
    return " ".join(
        _clean(_field(candidate, key))
        for key in (
            "title", "problem_statement", "actor", "task", "object",
            "failure_mode", "consequence", "buyer_context", "workaround",
        )
        if _clean(_field(candidate, key))
    )


def _first_pattern(text: str, patterns: tuple[tuple[str, str], ...]) -> str | None:
    for pattern, reason in patterns:
        if re.search(pattern, text, re.I):
            return reason
    return None


def _problem_specificity(candidate: Any) -> tuple[int, list[str]]:
    actor = _low(_field(candidate, "actor"))
    task = _low(_field(candidate, "task"))
    obj = _low(_field(candidate, "object"))
    failure = _low(_field(candidate, "failure_mode"))
    consequence = _low(_field(candidate, "consequence"))
    buyer = _low(_field(candidate, "buyer_context"))
    canonical = _low(_field(candidate, "problem_statement") or _field(candidate, "title"))

    score = 0
    gaps: list[str] = []

    if _known(actor) and actor not in GENERIC_ACTORS:
        score += 18
    elif _known(actor):
        score += 8
        gaps.append("ACTOR_TOO_GENERIC")
    else:
        gaps.append("ACTOR_UNKNOWN")

    if _known(task) and task not in GENERIC_TASKS and len(task.split()) >= 3:
        score += 20
    elif _known(task):
        score += 9
        gaps.append("WORKFLOW_TOO_GENERIC")
    else:
        gaps.append("WORKFLOW_UNKNOWN")

    if _known(obj) and len(obj.split()) >= 1:
        score += 10
    else:
        gaps.append("WORK_OBJECT_UNKNOWN")

    if _known(failure) and failure not in GENERIC_FAILURES and len(failure.split()) >= 3:
        score += 24
    elif _known(failure):
        score += 8
        gaps.append("FAILURE_TOO_GENERIC")
    else:
        gaps.append("FAILURE_UNKNOWN")

    if _known(consequence) and consequence not in {"unclear", "potential skill gap between junior and experienced engineers"}:
        score += 16
    else:
        gaps.append("CONSEQUENCE_NOT_CONCRETE")

    if _known(buyer):
        score += 12
    else:
        gaps.append("BUYER_CONTEXT_UNKNOWN")

    broad = _first_pattern(canonical, BROAD_PROBLEM_PATTERNS)
    if broad:
        score -= 38
        gaps.append(broad)

    if len(canonical.split()) <= 4:
        score -= 8

    return max(0, min(100, int(score))), list(dict.fromkeys(gaps))


def fingerprint_is_founder_unit(fp: Mapping[str, Any] | None) -> bool:
    """Strict filter used during discovery. Old broad fingerprints also fail safely."""
    fp = dict(fp or {})
    if fp.get("actionable_problem") is not True:
        return False
    if fp.get("opinion_or_news_only") is True:
        return False
    if float(fp.get("confidence", 0) or 0) < 0.65:
        return False

    explicit = fp.get("opportunity_unit_ready")
    if explicit is False:
        return False

    candidate = {
        "title": fp.get("canonical_problem"),
        "problem_statement": fp.get("canonical_problem"),
        "actor": fp.get("actor"),
        "task": fp.get("task"),
        "object": fp.get("object"),
        "failure_mode": fp.get("failure_mode"),
        "consequence": fp.get("consequence"),
        "buyer_context": fp.get("buyer_context"),
        "workaround": fp.get("workaround"),
    }
    specificity, _ = _problem_specificity(candidate)
    text = _low(_all_text(candidate))
    if _first_pattern(text, BROAD_PROBLEM_PATTERNS):
        return False
    # A community discussion may not name the paying buyer yet, so discovery can
    # keep a narrow problem atom at 62+. The Founder surface has a much harder buyer gate.
    return specificity >= 62


def assess_solo_transition(
    candidate: Any,
    *,
    claim_states: Mapping[str, Any] | None = None,
    company_reality: Mapping[str, Any] | None = None,
    commercial_reality: Mapping[str, Any] | None = None,
    attention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    claims = dict(claim_states or {})
    company = dict(company_reality or {})
    commerce = dict(commercial_reality or {})
    att = dict(attention or {})

    text = _low(_all_text(candidate))
    canonical = _low(_field(candidate, "problem_statement") or _field(candidate, "title"))
    buyer_context = _field(candidate, "buyer_context")
    workaround = _field(candidate, "workaround")
    consequence = _field(candidate, "consequence")

    specificity, specificity_gaps = _problem_specificity(candidate)
    frontier = _first_pattern(text, FRONTIER_PATTERNS)
    broad = _first_pattern(canonical, BROAD_PROBLEM_PATTERNS)
    phenomenon = _first_pattern(text, PHENOMENON_PATTERNS)
    regulated = bool(REGULATED_PATTERNS.search(text))
    physical = bool(PHYSICAL_PATTERNS.search(text))

    if frontier:
        problem_shape = "FRONTIER_TECH"
    elif broad or specificity < 45:
        problem_shape = "BROAD_THEME"
    elif phenomenon and not _known(buyer_context):
        problem_shape = "PHENOMENON"
    else:
        problem_shape = "PROBLEM_ATOM"

    c03 = _claim(claims, "C03")
    c05 = _claim(claims, "C05")
    c06 = _claim(claims, "C06")
    c07 = _claim(claims, "C07")
    c09 = _claim(claims, "C09")
    c11 = _claim(claims, "C11")
    c12 = _claim(claims, "C12")

    fingerprint = _field(candidate, "fingerprint", {})
    if not isinstance(fingerprint, Mapping):
        fingerprint = {}
    transition_pair_verified = (
        fingerprint.get("transition_evidence_verified") is True
        and _known(fingerprint.get("change_signal"))
        and _known(fingerprint.get("legacy_workflow"))
        and _known(fingerprint.get("transition_gap"))
        and len(fingerprint.get("transition_evidence_refs") or []) >= 2
    )

    # C12/C07 remain canonical reality claims. A V5.2 change-first pair may also
    # support the transition dimension before the later claim-research cycle, but
    # only when two persisted source refs were semantically verified together.
    change_signal = "SUPPORTED" if (c12 == "SUPPORTED" or transition_pair_verified) else "UNKNOWN"
    workaround_known = _known(workaround) or _known(fingerprint.get("legacy_workflow"))
    adoption_gap = (
        "SUPPORTED"
        if (c07 == "SUPPORTED" and workaround_known) or transition_pair_verified
        else "UNKNOWN"
    )
    transition_gap = (
        "SUPPORTED"
        if change_signal == "SUPPORTED" and adoption_gap == "SUPPORTED"
        else "PARTIAL"
        if change_signal == "SUPPORTED" or adoption_gap == "SUPPORTED"
        else "UNKNOWN"
    )

    buyer_owned = c05 == "SUPPORTED" and _known(buyer_context)
    material_consequence = bool(MATERIAL_CONSEQUENCE_PATTERNS.search(_clean(consequence)))
    if c11 == "SUPPORTED" and buyer_owned:
        economic_necessity = "EVIDENCED"
    elif c03 == "SUPPORTED" and buyer_owned and material_consequence:
        economic_necessity = "EVIDENCED"
    elif c03 == "SUPPORTED" and (buyer_owned or material_consequence):
        economic_necessity = "PARTIAL"
    else:
        economic_necessity = "UNKNOWN"

    company_fit = str(company.get("overall") or "UNKNOWN").upper()
    hard_solo_blockers: list[str] = []
    if frontier:
        hard_solo_blockers.append(frontier)
    if regulated:
        hard_solo_blockers.append("REGULATED_DOMAIN_BARRIER")
    if physical:
        hard_solo_blockers.append("PHYSICAL_OPERATIONS_BARRIER")
    if broad:
        hard_solo_blockers.append(broad)
    if problem_shape == "PHENOMENON":
        hard_solo_blockers.append("PHENOMENON_WITHOUT_ACTIONABLE_WORKFLOW")

    if hard_solo_blockers:
        solo_fit = "NOT_FIT_NOW"
    elif problem_shape != "PROBLEM_ATOM" or specificity < 65:
        solo_fit = "UNKNOWN"
    elif company_fit == "CAN_DO":
        solo_fit = "LIKELY_CAPTUREABLE"
    elif company_fit == "CAN_ACQUIRE":
        solo_fit = "POSSIBLE"
    else:
        solo_fit = "UNKNOWN"

    disqualifiers = list(hard_solo_blockers)
    if specificity < 65:
        disqualifiers.append("PROBLEM_NOT_ATOMIC_ENOUGH")
    if not _known(buyer_context):
        disqualifiers.append("BUYER_CONTEXT_UNKNOWN")
    if c05 != "SUPPORTED":
        disqualifiers.append("BUYER_REALITY_NOT_SUPPORTED")
    if transition_gap != "SUPPORTED":
        disqualifiers.append("TRANSITION_GAP_NOT_SUPPORTED")
    if economic_necessity != "EVIDENCED":
        disqualifiers.append("ECONOMIC_NECESSITY_NOT_EVIDENCED")
    if c09 != "SUPPORTED" or solo_fit not in {"LIKELY_CAPTUREABLE", "POSSIBLE"}:
        disqualifiers.append("SOLO_CAPTURE_PATH_NOT_SUPPORTED")
    disqualifiers = list(dict.fromkeys(disqualifiers))

    transition_evidence_ready = (c07 == "SUPPORTED" and c12 == "SUPPORTED") or transition_pair_verified
    investigate_ready = (
        problem_shape == "PROBLEM_ATOM"
        and specificity >= 65
        and c03 == "SUPPORTED"
        and c05 == "SUPPORTED"
        and transition_evidence_ready
        and c09 == "SUPPORTED"
        and _known(buyer_context)
        and transition_gap == "SUPPORTED"
        and economic_necessity == "EVIDENCED"
        and solo_fit in {"LIKELY_CAPTUREABLE", "POSSIBLE"}
    )
    validate_ready = investigate_ready and c06 == "SUPPORTED" and c11 == "SUPPORTED"

    if problem_shape in {"FRONTIER_TECH", "BROAD_THEME", "PHENOMENON"} or solo_fit == "NOT_FIT_NOW":
        classification = "RESEARCH_THEME"
    elif validate_ready:
        classification = "SOLO_VALIDATE"
    elif investigate_ready:
        classification = "SOLO_INVESTIGATE"
    else:
        classification = "SOLO_WATCH"

    transition_points = {"SUPPORTED": 100, "PARTIAL": 45, "UNKNOWN": 0}[transition_gap]
    economic_points = {"EVIDENCED": 100, "PARTIAL": 45, "UNKNOWN": 0}[economic_necessity]
    solo_points = {
        "LIKELY_CAPTUREABLE": 100,
        "POSSIBLE": 70,
        "UNKNOWN": 20,
        "NOT_FIT_NOW": 0,
    }[solo_fit]
    buyer_points = 100 if buyer_owned else 35 if _known(buyer_context) else 0
    evidence_points = sum(
        1 for code in ("C03", "C05", "C06", "C07", "C09", "C11", "C12")
        if _claim(claims, code) == "SUPPORTED"
    ) / 7 * 100
    solo_score = round(
        specificity * 0.25
        + transition_points * 0.22
        + economic_points * 0.20
        + solo_points * 0.20
        + buyer_points * 0.08
        + evidence_points * 0.05,
        1,
    )
    if classification == "RESEARCH_THEME":
        solo_score = min(solo_score, 24.9)

    if problem_shape != "PROBLEM_ATOM":
        next_gate = "ATOMIZE_PROBLEM"
    elif not _known(buyer_context) or c05 != "SUPPORTED":
        next_gate = "EXACT_BUYER_AND_ECONOMIC_OWNER"
    elif transition_gap != "SUPPORTED":
        next_gate = "TRANSITION_ADOPTION_GAP"
    elif economic_necessity != "EVIDENCED":
        next_gate = "ECONOMIC_NECESSITY"
    elif solo_fit not in {"LIKELY_CAPTUREABLE", "POSSIBLE"} or c09 != "SUPPORTED":
        next_gate = "SOLO_CAPTUREABILITY"
    else:
        next_gate = "SOLO_OPPORTUNITY_READY"

    return {
        "engine_version": ENGINE_VERSION,
        "classification": classification,
        "founder_surface_eligible": classification in {"SOLO_INVESTIGATE", "SOLO_VALIDATE"},
        "problem_shape": problem_shape,
        "problem_specificity_score": specificity,
        "specificity_gaps": specificity_gaps,
        "change_signal": change_signal,
        "adoption_gap": adoption_gap,
        "transition_gap": transition_gap,
        "economic_necessity": economic_necessity,
        "solo_fit": solo_fit,
        "company_fit": company_fit,
        "solo_score": solo_score,
        "next_gate": next_gate,
        "disqualifiers": disqualifiers,
        "truth_boundary": (
            "This gate does not invent a product, buyer, payment intent, or transition. "
            "Missing evidence remains UNKNOWN."
        ),
        "attention_is_not_opportunity": int(att.get("attention_score", 0) or 0),
        "commercial_context_present": bool(commerce),
    }


def gate_existing_decision(verdict: str, reason: str, assessment: Mapping[str, Any]) -> tuple[str, str]:
    """Apply solo/transition gates after existing evidence decision logic."""
    cls = str(assessment.get("classification") or "SOLO_WATCH")
    if cls == "RESEARCH_THEME":
        return "PARK", "RESEARCH_THEME_NOT_SOLO_FOUNDER_OPPORTUNITY"
    if cls == "SOLO_WATCH":
        return "WATCH", "SOLO_TRANSITION_GATES_INCOMPLETE"
    if cls == "SOLO_VALIDATE":
        return "VALIDATE", "SOLO_TRANSITION_READY_FOR_CUSTOMER_VALIDATION"
    if cls == "SOLO_INVESTIGATE":
        return "INVESTIGATE", "SOLO_TRANSITION_GAP_SUPPORTED"
    return "WATCH", reason or "SOLO_TRANSITION_GATES_INCOMPLETE"

# === SIGNALFORGE V7.1 OPPORTUNITY PORTFOLIO GATE OVERLAY ===
import re
from typing import Any, Mapping

ENGINE_VERSION = "solo-opportunity-portfolio-gate-v7"

UNCLEAR_VALUES = {
    "", "unknown", "unclear", "none", "none mentioned", "n/a", "na",
    "specific user/group or unclear", "specific user or group or unclear",
}
FRONTIER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brocm\b|\bcuda\b|\bcudagraph\b|\baiter\b", "GPU_KERNEL_OR_RUNTIME_ENGINEERING"),
    (r"\bvllm\b|\bsglang\b|\btensor parallel\b|\bexpert parallel\b|\bdisaggregated serving\b", "DISTRIBUTED_LLM_SERVING"),
    (r"\bspeculative decoding\b|\bkv cache\b|\bkernel\b|\btriton\b", "LOW_LEVEL_INFERENCE_ENGINEERING"),
    (r"\btrain(?:ing)? (?:a |the )?(?:foundation )?model\b|\bpretrain", "FOUNDATION_MODEL_RESEARCH"),
    (r"\bmodel alignment\b|\bemergent misalignment\b|\bmechanistic interpret", "MODEL_RESEARCH"),
    (r"\bcausal genetics\b|\bmendelian randomization\b|\bcolocalization\b|\bpharmacovigilance\b", "SPECIALIZED_BIOMEDICAL_RESEARCH"),
)
BROAD_PROBLEM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^ai model(?:s)? (?:do(?:es)? not|doesn't) produce reliable outputs?$", "BROAD_AI_RELIABILITY"),
    (r"^ai model output(?:s)? (?:is|are) unreliable$", "BROAD_AI_RELIABILITY"),
    (r"^ai model assumptions? lead to incorrect outputs?$", "BROAD_MODEL_ASSUMPTIONS"),
    (r"^ai (?:is|isn't|is not) reliable$", "BROAD_AI_RELIABILITY"),
    (r"^llm hallucinations?$", "BROAD_HALLUCINATION"),
    (r"^model reliability$", "BROAD_MODEL_RELIABILITY"),
    (r"^incorrect outputs?$", "BROAD_OUTPUT_QUALITY"),
)
PHENOMENON_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"over[- ]reliance|too dependent|dependence on (?:ai|tools)|skill gap|getting dumber", "BEHAVIOR_OR_SKILL_PHENOMENON"),
    (r"people (?:are|become)|users (?:are|become).*(?:lazy|dependent)", "BEHAVIOR_OR_SKILL_PHENOMENON"),
)
REGULATED_PATTERNS = re.compile(r"\b(?:clinical diagnosis|medical device|banking core|securities trading|legal advice|critical infrastructure)\b", re.I)
PHYSICAL_PATTERNS = re.compile(r"\b(?:manufacturing line|warehouse robotics|hardware installation|physical installation|robotics hardware)\b", re.I)
MATERIAL_CONSEQUENCE_PATTERNS = re.compile(
    r"\b(?:hours?|days?|minutes?|cost|spend|waste|lost|loss|revenue|sales|churn|delay|blocked|downtime|failed deploy|manual|headcount|labor|labour|fine|penalt|refund|conversion|backlog|rework)\b",
    re.I,
)
FRICTION_PATTERNS = re.compile(r"\b(?:annoy|frustrat|tedious|cumbersome|inconvenien|hard to|difficult to|every time|constantly|repeatedly|easy to miss|gets? lost|too many steps?|workaround)\b", re.I)
GENERIC_ACTORS = {"users", "user", "people", "developers", "developer", "engineers", "engineer", "businesses", "business", "companies", "company", "teams", "team", "community user"}
GENERIC_TASKS = {"use ai", "use ai tools", "use software", "coding", "debugging code", "run ai models locally"}
GENERIC_FAILURES = {"unreliable", "incorrect outputs", "wrong outputs", "does not work", "doesn't work", "model assumptions", "poor performance", "bad quality", "skill gap"}
VALID_CLASSES = {
    "TRANSITION_GAP",
    "PROVEN_MARKET_WEDGE",
    "MICRO_FRICTION",
    "DISTRIBUTION_MODEL_GAP",
    "SECOND_ORDER_PAIN",
    "BORING_OPS",
}


def _field(candidate: Any, name: str, default: Any = "") -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _low(value: Any) -> str:
    return _clean(value).lower()


def _known(value: Any) -> bool:
    return _low(value) not in UNCLEAR_VALUES


def _claim(claims: Mapping[str, Any] | None, code: str) -> str:
    raw = (claims or {}).get(code, "UNKNOWN")
    if hasattr(raw, "state"):
        raw = getattr(raw, "state", "UNKNOWN")
    return str(raw or "UNKNOWN").upper()


def _fp(candidate: Any) -> dict[str, Any]:
    raw = _field(candidate, "fingerprint", {})
    return dict(raw or {}) if isinstance(raw, Mapping) else {}


def _all_text(candidate: Any) -> str:
    return " ".join(
        _clean(_field(candidate, key))
        for key in ("title", "problem_statement", "actor", "task", "object", "failure_mode", "consequence", "buyer_context", "workaround")
        if _clean(_field(candidate, key))
    )


def _first_pattern(text: str, patterns: tuple[tuple[str, str], ...]) -> str | None:
    for pattern, reason in patterns:
        if re.search(pattern, text, re.I):
            return reason
    return None


def _classes(fp: Mapping[str, Any]) -> list[str]:
    raw = fp.get("opportunity_classes") or []
    if isinstance(raw, str):
        raw = [raw]
    out = [str(x).upper() for x in raw if str(x).upper() in VALID_CLASSES]
    primary = str(fp.get("primary_opportunity_class") or "").upper()
    if primary in VALID_CLASSES and primary not in out:
        out.insert(0, primary)
    # Legacy candidates are judged under the old transition path unless explicitly quarantined.
    if not out and fp.get("transition_evidence_verified"):
        out = ["TRANSITION_GAP"]
    return out


def _problem_specificity(candidate: Any) -> tuple[int, list[str]]:
    actor = _low(_field(candidate, "actor")); task = _low(_field(candidate, "task")); obj = _low(_field(candidate, "object"))
    failure = _low(_field(candidate, "failure_mode")); consequence = _low(_field(candidate, "consequence")); buyer = _low(_field(candidate, "buyer_context"))
    workaround = _low(_field(candidate, "workaround")); canonical = _low(_field(candidate, "problem_statement") or _field(candidate, "title"))
    score = 0; gaps: list[str] = []
    if _known(actor) and actor not in GENERIC_ACTORS: score += 16
    elif _known(actor): score += 6; gaps.append("ACTOR_NOT_MARKET_SPECIFIC")
    else: gaps.append("ACTOR_UNKNOWN")
    if _known(task) and task not in GENERIC_TASKS: score += 22
    elif _known(task): score += 9; gaps.append("WORKFLOW_TOO_GENERIC")
    else: gaps.append("WORKFLOW_UNKNOWN")
    if _known(obj): score += 8
    else: gaps.append("WORK_OBJECT_UNKNOWN")
    if _known(failure) and failure not in GENERIC_FAILURES and len(failure.split()) >= 4: score += 26
    elif _known(failure): score += 8; gaps.append("FAILURE_TOO_GENERIC")
    else: gaps.append("FAILURE_UNKNOWN")
    if _known(consequence): score += 12
    else: gaps.append("CONSEQUENCE_UNKNOWN")
    if _known(workaround): score += 10
    else: gaps.append("WORKAROUND_UNKNOWN")
    if _known(buyer): score += 6
    else: gaps.append("BUYER_CONTEXT_UNKNOWN")
    broad = _first_pattern(canonical, BROAD_PROBLEM_PATTERNS)
    if broad: score -= 40; gaps.append(broad)
    if len(canonical.split()) <= 4: score -= 8
    return max(0, min(100, int(score))), list(dict.fromkeys(gaps))


def _structure_status(fp: Mapping[str, Any], classes: list[str]) -> tuple[str, list[str]]:
    ready = []
    if "TRANSITION_GAP" in classes and fp.get("transition_evidence_verified") and fp.get("workaround_evidence_verified") and fp.get("economic_evidence_explicit"):
        ready.append("TRANSITION_GAP")
    if "PROVEN_MARKET_WEDGE" in classes and fp.get("market_supply_evidence_verified") and fp.get("workaround_evidence_verified") and (fp.get("friction_evidence_explicit") or fp.get("economic_evidence_explicit")):
        ready.append("PROVEN_MARKET_WEDGE")
    if "MICRO_FRICTION" in classes and fp.get("friction_evidence_explicit") and fp.get("workaround_evidence_verified"):
        ready.append("MICRO_FRICTION")
    if "DISTRIBUTION_MODEL_GAP" in classes and fp.get("market_supply_evidence_verified") and fp.get("distribution_gap_evidence_explicit"):
        ready.append("DISTRIBUTION_MODEL_GAP")
    if "SECOND_ORDER_PAIN" in classes and fp.get("second_order_evidence_verified") and (fp.get("friction_evidence_explicit") or fp.get("economic_evidence_explicit")):
        ready.append("SECOND_ORDER_PAIN")
    if "BORING_OPS" in classes and fp.get("economic_evidence_explicit") and fp.get("workaround_evidence_verified"):
        ready.append("BORING_OPS")
    if ready: return "SUPPORTED", ready
    if classes: return "PARTIAL", []
    return "UNKNOWN", []


def fingerprint_is_founder_unit(fp: Mapping[str, Any] | None) -> bool:
    fp = dict(fp or {})
    if fp.get("quarantined") is True or fp.get("actionable_problem") is not True or fp.get("opinion_or_news_only") is True:
        return False
    if float(fp.get("confidence", 0) or 0) < 0.65:
        return False
    if fp.get("opportunity_unit_ready") is False:
        return False
    candidate = {
        "title": fp.get("canonical_problem"), "problem_statement": fp.get("canonical_problem"), "actor": fp.get("actor"),
        "task": fp.get("task"), "object": fp.get("object"), "failure_mode": fp.get("failure_mode"), "consequence": fp.get("consequence"),
        "buyer_context": fp.get("buyer_context"), "workaround": fp.get("workaround"),
    }
    specificity, _ = _problem_specificity(candidate); text = _low(_all_text(candidate))
    if _first_pattern(text, BROAD_PROBLEM_PATTERNS) or _first_pattern(text, FRONTIER_PATTERNS):
        return False
    classes = _classes(fp)
    if fp.get("evidence_locked") is True:
        structure, _ = _structure_status(fp, classes)
        if structure == "UNKNOWN": return False
        # Micro-friction may begin with an unidentified community actor, but it remains WATCH until recurrence/buyer evidence.
        return specificity >= (52 if "MICRO_FRICTION" in classes else 58)
    return specificity >= 62


def assess_solo_transition(
    candidate: Any,
    *,
    claim_states: Mapping[str, Any] | None = None,
    company_reality: Mapping[str, Any] | None = None,
    commercial_reality: Mapping[str, Any] | None = None,
    attention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    claims = dict(claim_states or {}); company = dict(company_reality or {}); commerce = dict(commercial_reality or {}); att = dict(attention or {})
    fp = _fp(candidate); classes = _classes(fp)
    text = _low(_all_text(candidate)); canonical = _low(_field(candidate, "problem_statement") or _field(candidate, "title"))
    buyer_context = _field(candidate, "buyer_context"); consequence = _field(candidate, "consequence")
    specificity, specificity_gaps = _problem_specificity(candidate)
    frontier = _first_pattern(text, FRONTIER_PATTERNS); broad = _first_pattern(canonical, BROAD_PROBLEM_PATTERNS); phenomenon = _first_pattern(text, PHENOMENON_PATTERNS)
    regulated = bool(REGULATED_PATTERNS.search(text)); physical = bool(PHYSICAL_PATTERNS.search(text))

    if fp.get("quarantined") is True:
        problem_shape = "QUARANTINED"
    elif frontier: problem_shape = "FRONTIER_TECH"
    elif broad or specificity < 40: problem_shape = "BROAD_THEME"
    elif phenomenon and not classes: problem_shape = "PHENOMENON"
    else: problem_shape = "PROBLEM_ATOM"

    c02 = _claim(claims, "C02"); c03 = _claim(claims, "C03"); c05 = _claim(claims, "C05"); c06 = _claim(claims, "C06"); c07 = _claim(claims, "C07")
    c09 = _claim(claims, "C09"); c11 = _claim(claims, "C11"); c12 = _claim(claims, "C12")
    structure, supported_classes = _structure_status(fp, classes)

    if "TRANSITION_GAP" in supported_classes or "SECOND_ORDER_PAIN" in supported_classes:
        transition_gap = "SUPPORTED"
    elif classes and not ({"TRANSITION_GAP", "SECOND_ORDER_PAIN"} & set(classes)):
        transition_gap = "NOT_REQUIRED"
    else:
        transition_gap = "UNKNOWN"

    buyer_known = _known(buyer_context); buyer_owned = c05 == "SUPPORTED" and buyer_known
    material_consequence = bool(MATERIAL_CONSEQUENCE_PATTERNS.search(_clean(consequence))) or bool(fp.get("economic_evidence_explicit"))
    friction_observed = bool(FRICTION_PATTERNS.search(_clean(consequence))) or bool(fp.get("friction_evidence_explicit"))
    if c11 == "SUPPORTED" and buyer_owned: economic_necessity = "EVIDENCED"
    elif c03 == "SUPPORTED" and buyer_owned and material_consequence: economic_necessity = "EVIDENCED"
    elif material_consequence: economic_necessity = "OBSERVED_COST"
    elif friction_observed: economic_necessity = "OBSERVED_FRICTION"
    else: economic_necessity = "UNKNOWN"

    company_fit = str(company.get("overall") or "UNKNOWN").upper(); hard: list[str] = []
    if frontier: hard.append(frontier)
    if regulated: hard.append("REGULATED_DOMAIN_BARRIER")
    if physical: hard.append("PHYSICAL_OPERATIONS_BARRIER")
    if broad: hard.append(broad)
    if fp.get("quarantined") is True: hard.append("QUARANTINED_DISCOVERY_TRUTH")
    if problem_shape == "PHENOMENON": hard.append("PHENOMENON_WITHOUT_ACTIONABLE_WORKFLOW")
    if hard: solo_fit = "NOT_FIT_NOW"
    elif problem_shape != "PROBLEM_ATOM" or specificity < 55: solo_fit = "UNKNOWN"
    elif c09 == "SUPPORTED" or company_fit == "CAN_DO": solo_fit = "LIKELY_CAPTUREABLE"
    elif company_fit == "CAN_ACQUIRE": solo_fit = "POSSIBLE"
    else: solo_fit = "UNKNOWN"

    common = problem_shape == "PROBLEM_ATOM" and specificity >= 55 and structure == "SUPPORTED" and solo_fit in {"LIKELY_CAPTUREABLE", "POSSIBLE"}
    class_set = set(supported_classes)
    micro_path = bool("MICRO_FRICTION" in class_set and c02 == "SUPPORTED" and common)
    boring_path = bool("BORING_OPS" in class_set and c03 == "SUPPORTED" and c05 == "SUPPORTED" and common)
    wedge_path = bool(({"PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"} & class_set) and c03 == "SUPPORTED" and c05 == "SUPPORTED" and c07 == "SUPPORTED" and common)
    transition_path = bool(({"TRANSITION_GAP", "SECOND_ORDER_PAIN"} & class_set) and c03 == "SUPPORTED" and c05 == "SUPPORTED" and c07 == "SUPPORTED" and common)
    investigate_ready = micro_path or boring_path or wedge_path or transition_path
    validate_ready = investigate_ready and c06 == "SUPPORTED" and c11 == "SUPPORTED" and c05 == "SUPPORTED"

    if problem_shape in {"QUARANTINED", "FRONTIER_TECH", "BROAD_THEME", "PHENOMENON"} or solo_fit == "NOT_FIT_NOW": classification = "RESEARCH_THEME"
    elif validate_ready: classification = "SOLO_VALIDATE"
    elif investigate_ready: classification = "SOLO_INVESTIGATE"
    else: classification = "SOLO_WATCH"

    structure_points = {"SUPPORTED": 100, "PARTIAL": 40, "UNKNOWN": 0}[structure]
    econ_points = {"EVIDENCED": 100, "OBSERVED_COST": 70, "OBSERVED_FRICTION": 45, "UNKNOWN": 0}[economic_necessity]
    solo_points = {"LIKELY_CAPTUREABLE": 100, "POSSIBLE": 70, "UNKNOWN": 20, "NOT_FIT_NOW": 0}[solo_fit]
    buyer_points = 100 if buyer_owned else 35 if buyer_known else 0
    evidence_codes = ("C02", "C03", "C05", "C06", "C07", "C09", "C11", "C12")
    evidence_points = sum(1 for code in evidence_codes if _claim(claims, code) == "SUPPORTED") / len(evidence_codes) * 100
    solo_score = round(specificity * .25 + structure_points * .22 + econ_points * .18 + solo_points * .20 + buyer_points * .08 + evidence_points * .07, 1)
    if classification == "RESEARCH_THEME": solo_score = min(solo_score, 24.9)

    if problem_shape != "PROBLEM_ATOM": next_gate = "ATOMIZE_PROBLEM"
    elif structure != "SUPPORTED": next_gate = "OPPORTUNITY_STRUCTURE"
    elif "MICRO_FRICTION" in class_set and c02 != "SUPPORTED": next_gate = "RECURRENCE"
    elif not buyer_known or c05 != "SUPPORTED": next_gate = "EXACT_BUYER_AND_ECONOMIC_OWNER"
    elif ({"TRANSITION_GAP", "SECOND_ORDER_PAIN", "PROVEN_MARKET_WEDGE", "DISTRIBUTION_MODEL_GAP"} & class_set) and c07 != "SUPPORTED": next_gate = "UNRESOLVED_GAP"
    elif economic_necessity not in {"EVIDENCED", "OBSERVED_COST", "OBSERVED_FRICTION"}: next_gate = "ECONOMIC_NECESSITY"
    elif solo_fit not in {"LIKELY_CAPTUREABLE", "POSSIBLE"} or c09 != "SUPPORTED": next_gate = "SOLO_CAPTUREABILITY"
    else: next_gate = "SOLO_OPPORTUNITY_READY"

    disqualifiers = list(dict.fromkeys(hard + ([] if specificity >= 55 else ["PROBLEM_NOT_ATOMIC_ENOUGH"])))
    if structure != "SUPPORTED": disqualifiers.append("OPPORTUNITY_STRUCTURE_NOT_SUPPORTED")
    if not buyer_known: disqualifiers.append("BUYER_CONTEXT_UNKNOWN")
    if c09 != "SUPPORTED": disqualifiers.append("SOLO_CAPTURE_PATH_NOT_SUPPORTED")

    return {
        "engine_version": ENGINE_VERSION,
        "classification": classification,
        "founder_surface_eligible": classification in {"SOLO_INVESTIGATE", "SOLO_VALIDATE"},
        "problem_shape": problem_shape,
        "problem_specificity_score": specificity,
        "specificity_gaps": specificity_gaps,
        "opportunity_classes": classes,
        "supported_opportunity_classes": supported_classes,
        "opportunity_structure": structure,
        "change_signal": "SUPPORTED" if fp.get("transition_evidence_verified") or fp.get("second_order_evidence_verified") else "UNKNOWN",
        "adoption_gap": "SUPPORTED" if fp.get("workaround_evidence_verified") else "UNKNOWN",
        "transition_gap": transition_gap,
        "economic_necessity": economic_necessity,
        "solo_fit": solo_fit,
        "company_fit": company_fit,
        "solo_score": solo_score,
        "next_gate": next_gate,
        "disqualifiers": list(dict.fromkeys(disqualifiers)),
        "truth_boundary": "Opportunity class is evidence-bound. Transition is required only for transition/second-order classes; no missing buyer, WTP, product, or market fact is invented.",
        "attention_is_not_opportunity": int(att.get("attention_score", 0) or 0),
        "commercial_context_present": bool(commerce),
    }


def gate_existing_decision(verdict: str, reason: str, assessment: Mapping[str, Any]) -> tuple[str, str]:
    cls = str(assessment.get("classification") or "SOLO_WATCH")
    if cls == "RESEARCH_THEME": return "PARK", "RESEARCH_THEME_NOT_SOLO_FOUNDER_OPPORTUNITY"
    if cls == "SOLO_WATCH": return "WATCH", "SOLO_OPPORTUNITY_GATES_INCOMPLETE"
    if cls == "SOLO_VALIDATE": return "VALIDATE", "SOLO_OPPORTUNITY_READY_FOR_CUSTOMER_VALIDATION"
    if cls == "SOLO_INVESTIGATE": return "INVESTIGATE", "SOLO_OPPORTUNITY_STRUCTURE_SUPPORTED"
    return "WATCH", reason or "SOLO_OPPORTUNITY_GATES_INCOMPLETE"

