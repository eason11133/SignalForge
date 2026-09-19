"""SignalForge R5 discovery portfolio scheduler.

This module decides which *already observed* changed problem discussions deserve
bounded external enrichment first.  It has zero Candidate/Radar/Brain truth
authority and never deletes raw observations.

The live R3/R4 corpus was heavily developer-troubleshooting shaped.  A pure
recency queue therefore spent scarce enrichment budget on version/driver/build
bugs before buyer/workaround/structural workflow signals.  R5 keeps all raw
observations, but balances the enrichment portfolio by opportunity-bearing
source role.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "signalforge-discovery-portfolio-r5-opportunity-bearing-balance"

OPPORTUNITY_ROLES = {
    "FIRSTHAND_PAIN",
    "WORKAROUND",
    "BUYER",
    "TRANSITION",
    "SOLUTION",
    "TIMING",
}

TECH_TERMS = {
    "driver", "version", "cuda", "rocm", "dependency", "dependencies",
    "install", "installation", "build", "compile", "compiler", "import",
    "package", "checkpoint", "gpu", "vram", "kernel", "segfault", "crash",
    "error", "bug", "exception", "downgrade", "upgrade", "compatibility",
    "compatible", "windows", "linux", "pip", "npm", "docker",
}
WORKAROUND_TERMS = {
    "manual", "manually", "spreadsheet", "excel", "copy paste", "copy-paste",
    "workaround", "hack", "script", "internal tool", "custom tool", "homegrown",
    "in-house", "in house", "hand built", "hand-built", "temporary fix",
}
BUYER_TERMS = {
    "budget", "buyer", "procurement", "customer", "client", "team", "company",
    "enterprise", "agency", "department", "manager", "operations", "sales",
    "support", "compliance", "finance", "hr", "recruiting",
}
TRANSITION_TERMS = {
    "migration", "migrate", "transition", "shift", "adoption", "replacing",
    "replace", "legacy", "new regulation", "regulation", "policy change",
    "workflow change", "ai agent", "autonomous", "api change", "platform change",
}
SOLUTION_TERMS = {
    "alternative", "competitor", "tool", "solution", "vendor", "saas", "service",
    "platform", "product", "switching from", "switched from", "replaced with",
}
TIMING_TERMS = {
    "recent", "now", "this year", "newly", "launch", "released", "sunset",
    "deprecated", "deadline", "mandate", "requirement", "pricing change",
}
PAIN_TERMS = {
    "hours", "days", "delay", "blocked", "blocking", "expensive", "cost",
    "waste", "wasting", "repetitive", "repeat", "manual", "slow", "pain",
    "frustrating", "unreliable", "cannot", "can't", "fails", "failure",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(f"{k} {_text(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(v) for v in value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _haystack(discussion: Mapping[str, Any]) -> str:
    fp = discussion.get("fingerprint") if isinstance(discussion.get("fingerprint"), Mapping) else {}
    parts = [
        _text(fp.get("canonical_problem")), _text(fp.get("actor")), _text(fp.get("actor_category")),
        _text(fp.get("task")), _text(fp.get("object")), _text(fp.get("failure_mode")),
        _text(fp.get("consequence")), _text(fp.get("buyer_context")), _text(fp.get("workaround")),
        _text(discussion.get("title")), _text(discussion.get("discussion_key")),
    ]
    for post in discussion.get("posts") or []:
        if isinstance(post, Mapping):
            parts.extend([_text(post.get("title")), _text(post.get("problem_text")), _text(post.get("body"))])
    return " ".join(parts).lower()


def _hits(text: str, terms: set[str]) -> list[str]:
    return sorted({term for term in terms if term in text})


def classify_discussion_role(discussion: Mapping[str, Any]) -> dict[str, Any]:
    """Classify scheduling role only.  This result cannot establish evidence."""
    text = _haystack(discussion)
    fp = discussion.get("fingerprint") if isinstance(discussion.get("fingerprint"), Mapping) else {}

    workaround = _hits(text, WORKAROUND_TERMS)
    buyer = _hits(text, BUYER_TERMS)
    transition = _hits(text, TRANSITION_TERMS)
    solution = _hits(text, SOLUTION_TERMS)
    timing = _hits(text, TIMING_TERMS)
    pain = _hits(text, PAIN_TERMS)
    tech = _hits(text, TECH_TERMS)

    meaningful_workaround = _text(fp.get("workaround")).lower() not in {"", "none", "unknown", "unclear", "none mentioned"}
    meaningful_buyer = _text(fp.get("buyer_context")).lower() not in {"", "none", "unknown", "unclear", "none mentioned"}
    actor = _text(fp.get("actor_category") or fp.get("actor")).lower()
    consequence = _text(fp.get("consequence")).lower()

    scores = {
        "WORKAROUND": 4 * int(meaningful_workaround) + min(3, len(workaround)),
        "BUYER": 4 * int(meaningful_buyer) + min(3, len(buyer)),
        "TRANSITION": min(5, len(transition) * 2),
        "SOLUTION": min(4, len(solution)),
        "TIMING": min(3, len(timing)),
        "FIRSTHAND_PAIN": min(5, len(pain)) + int(bool(consequence)),
        "TECH_TROUBLESHOOTING": min(6, len(tech)) + int(any(x in actor for x in ("developer", "engineer", "programmer"))),
        "OTHER": 1,
    }

    # A narrow technology failure should not outrank evidence of a repeated
    # workaround/buyer/workflow merely because the text has many technical nouns.
    opportunity_strength = max(scores[r] for r in OPPORTUNITY_ROLES)
    if scores["TECH_TROUBLESHOOTING"] >= 3 and opportunity_strength < 4:
        primary = "TECH_TROUBLESHOOTING"
    else:
        order = ["WORKAROUND", "BUYER", "TRANSITION", "FIRSTHAND_PAIN", "SOLUTION", "TIMING", "OTHER"]
        primary = max(order, key=lambda r: (scores[r], -order.index(r)))
        if scores[primary] <= 1 and scores["TECH_TROUBLESHOOTING"] > 1:
            primary = "TECH_TROUBLESHOOTING"

    return {
        "engine_version": ENGINE_VERSION,
        "primary_role": primary,
        "opportunity_bearing": primary in OPPORTUNITY_ROLES,
        "scores": scores,
        "signals": {
            "workaround": workaround[:6], "buyer": buyer[:6], "transition": transition[:6],
            "solution": solution[:6], "timing": timing[:6], "pain": pain[:6], "tech": tech[:6],
        },
        "truth_boundary": "DISCOVERY_ROLE_IS_ENRICHMENT_SCHEDULING_ONLY_NOT_EVIDENCE_OR_CANDIDATE_TRUTH",
    }


def select_enrichment_portfolio(
    discussions: Iterable[Mapping[str, Any]],
    *,
    limit: int = 16,
    max_troubleshooting_fraction: float = 0.35,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, discussion in enumerate(discussions):
        copy = dict(discussion)
        role = classify_discussion_role(copy)
        copy["_discovery_portfolio_role"] = role
        copy["_discovery_original_rank"] = rank
        rows.append(copy)

    limit = max(0, int(limit))
    if limit == 0 or not rows:
        return [], {
            "engine_version": ENGINE_VERSION, "candidate_pool": len(rows), "selected": 0,
            "role_counts_pool": dict(Counter((r.get("_discovery_portfolio_role") or {}).get("primary_role", "OTHER") for r in rows)),
            "role_counts_selected": {}, "truth_boundary": "SCHEDULING_ONLY",
        }

    by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        role = str((row.get("_discovery_portfolio_role") or {}).get("primary_role") or "OTHER")
        by_role[role].append(row)

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    tech_cap = max(1, int(limit * max(0.0, min(1.0, float(max_troubleshooting_fraction)))))

    # Round-robin among opportunity-bearing roles first so one source shape does
    # not consume the whole batch.  Original rank remains the tie-breaker.
    role_order = ["WORKAROUND", "BUYER", "TRANSITION", "FIRSTHAND_PAIN", "SOLUTION", "TIMING", "OTHER"]
    while len(selected) < limit:
        made = False
        for role in role_order:
            bucket = by_role.get(role) or []
            if not bucket:
                continue
            row = bucket.pop(0)
            key = str(row.get("canonical_key") or row.get("discussion_key") or id(row))
            if key in selected_keys:
                continue
            selected.append(row); selected_keys.add(key); made = True
            if len(selected) >= limit:
                break
        if not made:
            break

    # Troubleshooting is context, not forbidden. It receives a bounded share
    # while opportunity-bearing changed observations exist.
    opportunity_available = any(
        (r.get("_discovery_portfolio_role") or {}).get("opportunity_bearing") for r in rows
    )
    tech_allowance = tech_cap if opportunity_available else limit
    tech_added = 0
    for row in by_role.get("TECH_TROUBLESHOOTING", []):
        if len(selected) >= limit or tech_added >= tech_allowance:
            break
        key = str(row.get("canonical_key") or row.get("discussion_key") or id(row))
        if key in selected_keys:
            continue
        selected.append(row); selected_keys.add(key); tech_added += 1

    # Do not spend scarce enrichment calls merely to fill the batch. When any
    # opportunity-bearing observation exists, the troubleshooting share remains
    # a real cap; an underfilled batch is preferable to turning narrow driver /
    # dependency noise into the dominant enrichment workload. If the corpus is
    # *entirely* troubleshooting-shaped, using those rows remains legal context.
    if len(selected) < limit:
        for row in rows:
            role = str((row.get("_discovery_portfolio_role") or {}).get("primary_role") or "OTHER")
            if opportunity_available and role == "TECH_TROUBLESHOOTING":
                continue
            key = str(row.get("canonical_key") or row.get("discussion_key") or id(row))
            if key in selected_keys:
                continue
            selected.append(row); selected_keys.add(key)
            if len(selected) >= limit:
                break

    pool_counts = Counter(str((r.get("_discovery_portfolio_role") or {}).get("primary_role") or "OTHER") for r in rows)
    selected_counts = Counter(str((r.get("_discovery_portfolio_role") or {}).get("primary_role") or "OTHER") for r in selected)
    return selected, {
        "engine_version": ENGINE_VERSION,
        "candidate_pool": len(rows),
        "selected": len(selected),
        "deferred_for_later_enrichment": max(0, len(rows) - len(selected)),
        "role_counts_pool": dict(pool_counts),
        "role_counts_selected": dict(selected_counts),
        "troubleshooting_selected": int(selected_counts.get("TECH_TROUBLESHOOTING", 0)),
        "troubleshooting_cap_when_opportunity_bearing": tech_cap,
        "opportunity_bearing_available": bool(opportunity_available),
        "underfilled_for_quality": bool(opportunity_available and len(selected) < limit),
        "unused_enrichment_slots": max(0, limit - len(selected)),
        "raw_observations_deleted": 0,
        "truth_boundary": "PORTFOLIO_BALANCES_ENRICHMENT_ORDER_ONLY_NO_CANDIDATE_OR_MARKET_TRUTH_AUTHORITY",
    }


def static_acceptance() -> dict[str, bool]:
    pain = {"fingerprint": {"canonical_problem": "Operations teams manually copy customer data between systems for hours", "workaround": "manual spreadsheet", "buyer_context": "operations manager budget"}, "posts": []}
    bug = {"fingerprint": {"canonical_problem": "CUDA driver 555 crashes model import", "actor_category": "developer", "failure_mode": "driver version compatibility error"}, "posts": []}
    rows = [dict(bug, canonical_key=f"b{i}") for i in range(10)] + [dict(pain, canonical_key=f"p{i}") for i in range(6)]
    selected, report = select_enrichment_portfolio(rows, limit=8, max_troubleshooting_fraction=0.25)
    roles = [(r.get("_discovery_portfolio_role") or {}).get("primary_role") for r in selected]
    sparse_rows = [dict(pain, canonical_key="p-only")] + [dict(bug, canonical_key=f"sb{i}") for i in range(10)]
    sparse_selected, sparse_report = select_enrichment_portfolio(sparse_rows, limit=8, max_troubleshooting_fraction=0.25)
    sparse_roles = [(r.get("_discovery_portfolio_role") or {}).get("primary_role") for r in sparse_selected]
    return {
        "workaround_buyer_problem_is_opportunity_bearing": bool(classify_discussion_role(pain)["opportunity_bearing"]),
        "narrow_driver_bug_is_troubleshooting": classify_discussion_role(bug)["primary_role"] == "TECH_TROUBLESHOOTING",
        "troubleshooting_cannot_dominate_when_opportunity_rows_exist": roles.count("TECH_TROUBLESHOOTING") <= 2,
        "sparse_opportunity_pool_may_underfill_instead_of_spending_on_noise": sparse_roles.count("TECH_TROUBLESHOOTING") <= 2 and bool(sparse_report.get("underfilled_for_quality")),
        "selection_never_claims_truth_authority": report["raw_observations_deleted"] == 0 and "NO_CANDIDATE_OR_MARKET_TRUTH_AUTHORITY" in report["truth_boundary"],
    }
