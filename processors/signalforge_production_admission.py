"""SignalForge R2 production workload admission.

This module decides *where compute/research attention is allowed to go*.
It never changes C01-C14, never promotes an opportunity, and never deletes
observations. Candidate remains a provenance/discovery object; Radar/Brain truth
remain the truth owners described by their respective contracts.

R2 exists because the live funnel could continuously turn low-value transient
bugs into RadarCases and then spend recurrence/materiality/reality compute on
all of them. Admission moves a cheap, deterministic scheduling decision ahead
of expensive research while preserving 0-active-work as a legal result.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "signalforge-production-admission-r2-thesis-controlled-funnel"
ACTIVE_STATES = {"THESIS_ACTIVE", "RESEARCH_ACTIVE"}
FINAL_C02 = {"SUPPORTED", "REFUTED"}
NO_NEW_INFO_RESEARCH_STATES = {"SEARCH_EXHAUSTED", "INSUFFICIENT", "COMPLETED"}

_UNKNOWN = {"", "unknown", "unclear", "none", "none mentioned", "n/a", "null"}


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _text(obj: Any) -> str:
    parts = [
        str(_field(obj, key, "") or "").strip()
        for key in (
            "title", "problem_statement", "actor", "task", "object",
            "failure_mode", "consequence", "buyer_context", "workaround",
        )
    ]
    fp = _field(obj, "fingerprint", {})
    if isinstance(fp, Mapping):
        parts.extend(
            str(fp.get(key) or "").strip()
            for key in (
                "canonical_problem", "actor", "task", "object",
                "failure_mode", "consequence", "buyer_context", "workaround",
            )
        )
    return " ".join(x for x in parts if x).lower()


def _known(value: Any) -> bool:
    return str(value or "").strip().lower() not in _UNKNOWN


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_rel(rel: Mapping[str, Any], key: str) -> int:
    try:
        return max(0, int(rel.get(key, 0) or 0))
    except Exception:
        return 0


def _ephemeral_flags(candidate: Any) -> list[str]:
    text = _text(candidate)
    flags: list[str] = []
    patterns = (
        (
            r"\b(?:driver|firmware|bios|version|release|upgrade|downgrade|rollback)\b.{0,80}\b(?:bug|issue|broken|crash|fail|regression|performance)\b|"
            r"\b(?:bug|issue|broken|crash|fail|regression|performance)\b.{0,80}\b(?:driver|firmware|bios|version|release|upgrade|downgrade|rollback)\b",
            "TRANSIENT_VERSION_OR_DRIVER_FAILURE",
        ),
        (
            r"\b(?:gpu|graphics card|pc case|chassis|slot|clearance)\b.{0,80}\b(?:fit|space|install|clearance|slot)\b|"
            r"\b(?:fit|space constraints?|clearance)\b.{0,80}\b(?:gpu|graphics card|pc case|chassis|slot)\b",
            "ONE_OFF_HARDWARE_CONFIGURATION",
        ),
        (
            r"\bunable to complete tasks? with\b.{0,60}\b(?:model|qwen|llama|gemma|mistral)\b.{0,80}\b(?:bug|bugs|broken|issue)\b",
            "MODEL_SPECIFIC_BUG_REPORT",
        ),
    )
    for pattern, reason in patterns:
        if re.search(pattern, text, re.I):
            flags.append(reason)
    return flags


def _structural_signal(fp: Mapping[str, Any], rel: Mapping[str, Any]) -> bool:
    classes = fp.get("opportunity_classes") or []
    if isinstance(classes, str):
        classes = [classes]
    classes = {str(x).upper() for x in classes}
    primary = str(fp.get("primary_opportunity_class") or "").upper()
    if primary:
        classes.add(primary)
    return bool(
        fp.get("transition_evidence_verified")
        or fp.get("second_order_evidence_verified")
        or fp.get("workaround_evidence_verified")
        or fp.get("economic_evidence_explicit")
        or classes & {"TRANSITION_GAP", "SECOND_ORDER_PAIN", "BORING_OPS", "PROVEN_MARKET_WEDGE"}
        or _int_rel(rel, "why_now") > 0
    )




def assess_pre_enrichment_discovery(discussion: Any) -> dict[str, Any]:
    """Cheap gate before external retrieval / verifier spend for *new* observations.

    Existing ProblemCandidates are never hidden by this gate; if a known
    candidate receives new community evidence it can re-enter enrichment so
    recurrence can strengthen it. For brand-new observations, only very clear
    transient/version/hardware reports are deferred when they lack a buyer,
    workaround, structural-change signal, or multi-post recurrence. Raw Posts
    and fingerprint provenance remain persisted upstream.
    """
    fp = _dict(_field(discussion, "fingerprint", {}))
    posts = list(_field(discussion, "posts", []) or [])
    is_new = bool(_field(discussion, "_incremental_new", False))
    ephemeral = _ephemeral_flags(discussion)
    structural = _structural_signal(fp, {})
    buyer_known = _known(fp.get("buyer_context"))
    workaround_known = _known(fp.get("workaround"))

    actor_keys: set[str] = set()
    for post in posts:
        if not isinstance(post, Mapping):
            continue
        for key in ("author", "username", "user", "user_id", "actor"):
            raw = str(post.get(key) or "").strip().lower()
            if raw:
                actor_keys.add(f"{key}:{raw}")
                break

    recurrence_signal = len(posts) >= 2 or len(actor_keys) >= 2
    defer = bool(
        is_new
        and ephemeral
        and not recurrence_signal
        and not structural
        and not buyer_known
        and not workaround_known
    )
    return {
        "engine_version": ENGINE_VERSION,
        "state": "DEFER_PRE_ENRICHMENT_TRANSIENT" if defer else "ADMIT_PRE_ENRICHMENT",
        "admit_external_enrichment": not defer,
        "is_new_candidate": is_new,
        "ephemeral_flags": ephemeral,
        "post_count": len(posts),
        "distinct_actor_keys": len(actor_keys),
        "recurrence_signal": recurrence_signal,
        "structural_signal": structural,
        "buyer_known": buyer_known,
        "workaround_known": workaround_known,
        "truth_boundary": "DISCOVERY_COMPUTE_ADMISSION_ONLY_NO_C01_C14_OR_BRAIN_AUTHORITY",
    }

def assess_candidate_admission(
    candidate: Any,
    *,
    claim_states: Mapping[str, Any] | None = None,
    brain_candidate_ids: Iterable[int] | None = None,
    c02_research_status: str | None = None,
    corpus_changed: bool = False,
    decision_verdict: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic scheduling/admission decision.

    The decision is deliberately asymmetric:
    * Strong/Brain-linked objects are allowed into expensive research.
    * Weak transient bug/configuration observations remain stored but do not
      automatically become new RadarCase workload.
    * SEARCH_EXHAUSTED/INSUFFICIENT recurrence work does not repeat on an
      unchanged corpus. A new source refresh re-opens eligibility.
    """
    cid = int(_field(candidate, "id", _field(candidate, "candidate_id", 0)) or 0)
    brain_ids = {int(x) for x in (brain_candidate_ids or []) if str(x).isdigit()}
    thesis_member = cid > 0 and cid in brain_ids

    stage = str(_field(candidate, "stage", "candidate") or "candidate").lower()
    verdict = str(decision_verdict or _field(candidate, "decision_verdict", "WATCH") or "WATCH").upper()
    rel = _dict(_field(candidate, "relation_support", {}))
    fp = _dict(_field(candidate, "fingerprint", {}))
    claims = {str(k): str(v or "UNKNOWN").upper() for k, v in dict(claim_states or {}).items()}

    specificity = _num(rel.get("problem_specificity_score"), 0.0)
    direct_problem = _int_rel(rel, "direct_problem_corroboration")
    market_context = sum(
        _int_rel(rel, key)
        for key in ("buyer_demand", "solution_supply", "competitor", "ecosystem_activity", "why_now", "research_enabler")
    )
    users = int(_field(candidate, "community_user_count", 0) or 0)
    evidence_count = int(_field(candidate, "community_evidence_count", 0) or 0)
    corroboration = _num(_field(candidate, "corroboration_score", 0.0))
    buyer_score = _num(_field(candidate, "buyer_demand_score", 0.0))
    consequence_known = _known(_field(candidate, "consequence"))
    buyer_known = _known(_field(candidate, "buyer_context")) or buyer_score >= 40
    workaround_known = _known(_field(candidate, "workaround"))
    structural = _structural_signal(fp, rel)
    ephemeral = _ephemeral_flags(candidate)

    truth_advanced = any(claims.get(code) == "SUPPORTED" for code in ("C02", "C03", "C05", "C06", "C07"))
    strong_observation = bool(
        direct_problem >= 1
        or corroboration >= 50
        or stage in {"corroborated", "opportunity"}
        or (users >= 2 and specificity >= 62)
    )
    high_specificity_firsthand = bool(
        evidence_count >= 1
        and specificity >= 72
        and consequence_known
        and not ephemeral
    )

    reasons: list[str] = []
    if thesis_member:
        state = "THESIS_ACTIVE"
        reasons.append("BRAIN_THESIS_OR_RESEARCH_QUEUE_MEMBER")
    elif verdict in {"VALIDATE", "INVESTIGATE"}:
        state = "RESEARCH_ACTIVE"
        reasons.append(f"VERDICT_{verdict}")
    elif truth_advanced:
        state = "RESEARCH_ACTIVE"
        reasons.append("ATOMIC_TRUTH_ALREADY_ADVANCED")
    elif ephemeral and not (
        structural
        or (buyer_known and corroboration >= 70 and users >= 2)
    ):
        # A specific/first-hand bug can be perfectly real and still be a poor
        # use of Opportunity Intelligence compute. Transient vendor/version or
        # one-off hardware issues must first earn recurrence/buyer/structural
        # evidence before they enter expensive research. Brain membership and
        # already-advanced atomic truth remain explicit override authorities.
        state = "DEFER_EPHEMERAL"
        reasons.extend(ephemeral)
    elif strong_observation or structural or high_specificity_firsthand:
        state = "RESEARCH_ACTIVE"
        if strong_observation:
            reasons.append("STRONG_PROBLEM_OBSERVATION")
        if structural:
            reasons.append("STRUCTURAL_OR_WORKAROUND_SIGNAL")
        if high_specificity_firsthand:
            reasons.append("HIGH_SPECIFICITY_FIRSTHAND_WITH_CONSEQUENCE")
    else:
        state = "MONITOR_CONTEXT"
        reasons.append("INSUFFICIENT_FOR_EXPENSIVE_RESEARCH")

    machine_eligible = state in ACTIVE_STATES
    # New-case admission is intentionally stricter than "worth monitoring /
    # researching". A single direct technical match is not enough to explode
    # one observation into 14 Radar claims. Deferred observations remain fully
    # persisted and can be reconsidered when recurrence, buyer, workaround or
    # structural evidence strengthens.
    earned_new_case = bool(
        thesis_member
        or verdict in {"VALIDATE", "INVESTIGATE"}
        or truth_advanced
        or structural
        or (
            machine_eligible
            and consequence_known
            and (
                users >= 2
                or direct_problem >= 2
                or corroboration >= 60
                or (high_specificity_firsthand and (buyer_known or workaround_known))
            )
        )
    )
    ledger_admit_new = bool(machine_eligible and earned_new_case)

    c02_state = claims.get("C02", "UNKNOWN")
    rs = str(c02_research_status or _field(candidate, "c02_research_status", "") or "").upper()
    if c02_state in FINAL_C02:
        recurrence_eligible = False
        recurrence_route = "C02_ALREADY_RESOLVED"
    elif not machine_eligible:
        recurrence_eligible = False
        recurrence_route = "NOT_IN_ACTIVE_WORKLOAD"
    elif rs in NO_NEW_INFO_RESEARCH_STATES and not corpus_changed:
        recurrence_eligible = False
        recurrence_route = "WAIT_FOR_NEW_PROBLEM_CORPUS_OR_NEW_METHOD"
    else:
        recurrence_eligible = True
        recurrence_route = "RUN_BOUNDED_RECURRENCE"

    if rs == "SEARCH_EXHAUSTED" and not corpus_changed:
        next_route = "CHANGE_SOURCE_MARKET_ACTION_OR_PARK"
    elif rs == "INSUFFICIENT" and not corpus_changed:
        next_route = "WAIT_FOR_NEW_SOURCE_COVERAGE"
    elif state == "DEFER_EPHEMERAL":
        next_route = "MONITOR_ONLY_UNLESS_RECURRENCE_OR_BUYER_SIGNAL_APPEARS"
    elif state == "MONITOR_CONTEXT":
        next_route = "CHEAP_OBSERVATION_ONLY"
    else:
        next_route = "DECISION_CRITICAL_RESEARCH"

    priority_tier = {
        "THESIS_ACTIVE": 0,
        "RESEARCH_ACTIVE": 1,
        "MONITOR_CONTEXT": 5,
        "DEFER_EPHEMERAL": 8,
    }.get(state, 9)

    return {
        "engine_version": ENGINE_VERSION,
        "candidate_id": cid,
        "state": state,
        "machine_research_eligible": machine_eligible,
        "ledger_admit_new": ledger_admit_new,
        "recurrence_eligible": recurrence_eligible,
        "recurrence_route": recurrence_route,
        "next_route": next_route,
        "priority_tier": priority_tier,
        "brain_member": thesis_member,
        "reason_codes": list(dict.fromkeys(reasons)),
        "ephemeral_flags": ephemeral,
        "signals": {
            "stage": stage,
            "decision_verdict": verdict,
            "specificity": round(specificity, 1),
            "direct_problem": direct_problem,
            "community_users": users,
            "community_evidence": evidence_count,
            "corroboration_score": round(corroboration, 1),
            "market_context_relations": market_context,
            "buyer_known": buyer_known,
            "workaround_known": workaround_known,
            "structural_signal": structural,
            "c02_state": c02_state,
            "c02_research_status": rs or "NOT_REGISTERED",
            "corpus_changed": bool(corpus_changed),
            "earned_new_case": earned_new_case,
        },
        "truth_boundary": "WORKLOAD_SCHEDULING_ONLY_NO_C01_C14_WRITE_NO_OPPORTUNITY_PROMOTION",
    }


def annotate_rows(
    rows: list[dict[str, Any]],
    *,
    brain_candidate_ids: Iterable[int] | None = None,
    corpus_changed: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    recurrence_route_counts: Counter[str] = Counter()
    active = 0
    recurrence = 0
    out: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        decision = assess_candidate_admission(
            copy,
            claim_states=copy.get("claims") or {},
            brain_candidate_ids=brain_candidate_ids,
            c02_research_status=copy.get("c02_research_status"),
            corpus_changed=corpus_changed,
            decision_verdict=copy.get("decision_verdict"),
        )
        copy["production_admission"] = decision
        counts[decision["state"]] += 1
        route_counts[str(decision.get("next_route") or "UNKNOWN")] += 1
        recurrence_route_counts[str(decision.get("recurrence_route") or "UNKNOWN")] += 1
        active += int(bool(decision["machine_research_eligible"]))
        recurrence += int(bool(decision["recurrence_eligible"]))
        out.append(copy)
    summary = {
        "engine_version": ENGINE_VERSION,
        "total_rows": len(out),
        "active_machine_research": active,
        "recurrence_eligible": recurrence,
        "states": dict(counts),
        "next_routes": dict(route_counts),
        "recurrence_routes": dict(recurrence_route_counts),
        "zero_active_is_legal": True,
        "truth_boundary": "ADMISSION_COUNTS_ARE_SCHEDULING_TELEMETRY_NOT_MARKET_TRUTH",
    }
    return out, summary


def active_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if bool(((row.get("production_admission") or {}).get("machine_research_eligible")))
    ]


def static_acceptance() -> dict[str, bool]:
    weak_bug = {
        "id": 1,
        "title": "Consumer facing AMD GPU software issue resolves by downgrading driver",
        "problem_statement": "GPU software issue resolved by downgrading driver version",
        "failure_mode": "driver bug",
        "consequence": "software fails",
        "community_evidence_count": 1,
        "community_user_count": 1,
        "stage": "candidate",
        "relation_support": {"problem_specificity_score": 78},
    }
    strong = {
        "id": 2,
        "title": "Warehouse coordination causes payment delays and linear headcount growth",
        "problem_statement": "manual coordination slows customer payment and inventory activation",
        "actor": "warehouse operator",
        "task": "inventory intake coordination",
        "failure_mode": "manual coordination bottleneck",
        "consequence": "payment delays and linear headcount growth",
        "community_evidence_count": 1,
        "community_user_count": 2,
        "stage": "corroborated",
        "relation_support": {"problem_specificity_score": 84, "direct_problem_corroboration": 1},
    }
    a = assess_candidate_admission(weak_bug)
    b = assess_candidate_admission(strong)
    c = assess_candidate_admission(weak_bug, brain_candidate_ids=[1])
    exhausted = assess_candidate_admission(
        strong,
        claim_states={"C02": "INSUFFICIENT"},
        c02_research_status="SEARCH_EXHAUSTED",
        corpus_changed=False,
    )
    reopened = assess_candidate_admission(
        strong,
        claim_states={"C02": "INSUFFICIENT"},
        c02_research_status="SEARCH_EXHAUSTED",
        corpus_changed=True,
    )
    return {
        "ephemeral_one_off_is_deferred": a["state"] == "DEFER_EPHEMERAL" and not a["ledger_admit_new"],
        "corroborated_problem_is_active": b["state"] == "RESEARCH_ACTIVE" and b["machine_research_eligible"] and b["ledger_admit_new"],
        "brain_thesis_membership_can_activate_workload_not_truth": c["state"] == "THESIS_ACTIVE" and "NO_C01_C14_WRITE" in c["truth_boundary"],
        "search_exhausted_does_not_repeat_on_unchanged_corpus": exhausted["recurrence_eligible"] is False,
        "new_problem_corpus_reopens_exhausted_recurrence": reopened["recurrence_eligible"] is True,
    }
