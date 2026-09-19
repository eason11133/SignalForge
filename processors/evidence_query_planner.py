"""SignalForge quality-first evidence query planner V1.

Builds deterministic, claim-specific research queries from the actual case text.
It does NOT decide truth and does NOT create SUPPORT. Its job is to reduce
research waste while carrying forward the exact precision constraints that
must survive retrieval.

The planner is deliberately conservative:
- one query packet can serve several claims when the evidence need overlaps;
- every packet contains rejection rules and a stop condition;
- market-test-only claims are never converted into desk-research proof.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

ENGINE_VERSION = "evidence-query-planner-v1"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
    "is", "are", "be", "been", "being", "does", "do", "not", "due", "from",
    "among", "under", "over", "into", "by", "as", "at", "it", "its", "this",
    "that", "these", "those", "ai", "model", "models", "system", "systems",
    "software", "user", "users",
}

GATE_CLAIMS = {
    "PAIN_MATERIALITY": ("C03",),
    "BUYER_REALITY": ("C05",),
    "BUYER_REALITY_RECHECK": ("C05",),
    "CURRENT_SOLUTION": ("C06",),
    "CURRENT_SOLUTION_RECHECK": ("C06",),
    "UNRESOLVED_GAP": ("C07",),
    "UNRESOLVED_GAP_RECHECK": ("C07",),
    "DIFFERENTIATION": ("C08", "C13"),
    "DISTRIBUTION": ("C10",),
    "ECONOMICS": ("C11",),
    "OPPORTUNITY_WINDOW": ("C12",),
    "COMPETITION": ("C08", "C13"),
    "SWITCHING": ("C14",),
}

GROUP_FOR_GATE = {
    "PAIN_MATERIALITY": "problem",
    "BUYER_REALITY": "buyer",
    "BUYER_REALITY_RECHECK": "buyer",
    "CURRENT_SOLUTION": "problem",
    "CURRENT_SOLUTION_RECHECK": "problem",
    "UNRESOLVED_GAP": "problem",
    "UNRESOLVED_GAP_RECHECK": "problem",
    "DIFFERENTIATION": "market",
    "DISTRIBUTION": "buyer",
    "ECONOMICS": "buyer",
    "OPPORTUNITY_WINDOW": "timing",
    "COMPETITION": "market",
    "SWITCHING": "market",
}

QUALITY_CONTRACT = {
    "C03": [
        "Evidence must show a material consequence of the same problem, not generic dissatisfaction.",
        "Prefer direct blocking, time loss, cost, operational failure, safety, privacy, or revenue consequence evidence.",
        "A complaint or negative sentiment without a concrete consequence is INSUFFICIENT.",
        "Counterevidence that the issue is low-impact, easily avoided, or non-blocking must be searched explicitly.",
    ],
    "C05": [
        "Named organization and concrete budget/ownership are required.",
        "Generic AI/software hiring is INSUFFICIENT.",
        "A job must directly own the same operational problem/capability.",
    ],
    "C06": [
        "Evidence must describe the same problem, not merely the same technology.",
        "Direction must match: slow cannot be supported by fast/ultrafast evidence.",
        "Mechanism must match: under-load requires load/concurrency/capacity evidence.",
        "At least two independent SAME_PROBLEM source families are required for support.",
    ],
    "C07": [
        "Evidence must show the same problem persists despite a current solution/workaround.",
        "A different bug in the same product is INSUFFICIENT.",
        "Source-set exhaustion is not REFUTE.",
    ],
    "C08": [
        "Name the incumbent/substitute and compare the proposed wedge directly.",
        "Search for evidence that the wedge is already baseline or easily bundled.",
        "Context cannot become SUPPORT without surviving falsification.",
    ],
    "C10": [
        "A visible channel is not acquisition proof.",
        "Desk research may prepare routes; a qualified buyer engagement is market proof.",
    ],
    "C11": [
        "Job compensation is not willingness-to-pay.",
        "Public pricing is context only; a price-bearing buyer action is WTP evidence.",
    ],
    "C12": [
        "Separate technology enablement from model erosion/platform absorption.",
        "Scenario evidence is not a forecast.",
        "Do not use information published after the replay cutoff.",
    ],
    "C13": [
        "Research the strongest incumbent/platform response, not an average competitor.",
        "Competitor presence alone does not prove survivability.",
    ],
    "C14": [
        "A workaround is not switch intent.",
        "Real workflow migration is required for switching proof.",
    ],
}


def _safe(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(*values: Any, limit: int = 8) -> list[str]:
    text = " ".join(_safe(v).lower() for v in values if _safe(v))
    parts = re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", text)
    out = []
    seen = set()
    for token in parts:
        if token in STOPWORDS or token.isdigit():
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _quoted_core(row: dict[str, Any]) -> str:
    failure = _safe(row.get("failure_mode"))
    problem = _safe(row.get("problem_statement"))
    title = _safe(row.get("title"))

    base = failure or problem or title
    if not base:
        return ""
    words = base.split()
    if len(words) > 12:
        words = words[:12]
    return '"' + " ".join(words) + '"'


def _query_fingerprint(group: str, claims: list[str], query: str) -> str:
    raw = "|".join([group, ",".join(sorted(claims)), query.lower().strip()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_query_packets(row: dict[str, Any]) -> list[dict[str, Any]]:
    gate = _safe(row.get("current_gate")).upper()
    claims = list(GATE_CLAIMS.get(gate, ()))
    group = GROUP_FOR_GATE.get(gate)

    # A query packet without an atomic claim scope cannot carry a meaningful
    # quality contract. Do not let Floor60 source hints manufacture an
    # unscoped packet; a missing mapping must remain visible as a planner gap.
    if not claims:
        return []

    # Also allow the Floor60 packet to contribute a source need without
    # manufacturing a new proof path.
    if not group:
        floor = row.get("floor60_reality") or {}
        source_needs = list(floor.get("source_needs") or [])
        if source_needs:
            group = str(source_needs[0])

    if not group:
        return []

    core = _quoted_core(row)
    keywords = _tokens(
        row.get("actor"),
        row.get("task"),
        row.get("object"),
        row.get("failure_mode"),
        row.get("problem_statement"),
        row.get("title"),
    )
    tail = " ".join(keywords[:5]).strip()
    seed = (core + " " + tail).strip() or _safe(row.get("title"))

    queries: list[tuple[str, str]] = []

    if gate == "PAIN_MATERIALITY":
        queries = [
            ("pain_consequence", f"{seed} blocked unusable hours days cost revenue operational impact"),
            ("pain_direct_failure", f"{seed} cannot unable failure downtime manual workaround consequence"),
            ("pain_counter", f"{seed} minor low impact easy workaround resolved non blocking"),
        ]
    elif gate in {"BUYER_REALITY", "BUYER_REALITY_RECHECK"}:
        queries = [
            ("buyer_budget", f"{seed} budget owner hiring responsibility"),
            ("buyer_procurement", f"{seed} procurement buyer team responsibility"),
            ("buyer_negative", f"{seed} generic hiring unrelated responsibility"),
        ]
    elif gate in {"CURRENT_SOLUTION", "CURRENT_SOLUTION_RECHECK"}:
        queries = [
            ("solution_failure", f"{seed} bug issue failure workaround alternative"),
            ("solution_complaint", f"{seed} complaint regression unresolved"),
            ("solution_counter", f"{seed} fixed resolved fast reliable improvement"),
        ]
    elif gate in {"UNRESOLVED_GAP", "UNRESOLVED_GAP_RECHECK"}:
        queries = [
            ("gap_persistence", f"{seed} still broken persists workaround recurring"),
            ("gap_current_solution", f"{seed} workaround limitation existing solution"),
            ("gap_counter", f"{seed} resolved fixed no longer issue"),
        ]
    elif gate in {"DIFFERENTIATION", "COMPETITION"}:
        queries = [
            ("competitor_map", f"{seed} competitor alternative vs incumbent"),
            ("wedge_falsify", f"{seed} built-in native feature bundled free"),
            ("copy_risk", f"{seed} platform integration replacement migration"),
        ]
    elif gate == "DISTRIBUTION":
        queries = [
            ("acquisition_route", f"{seed} customer acquisition channel qualified leads"),
            ("acquisition_counter", f"{seed} failed outreach no qualified buyers"),
        ]
    elif gate == "ECONOMICS":
        queries = [
            ("price_context", f"{seed} pricing paid pilot subscription contract"),
            ("wtp_counter", f"{seed} free alternative price objection budget"),
        ]
    elif gate == "OPPORTUNITY_WINDOW":
        queries = [
            ("tech_enablement", f"{seed} model release api capability cheaper faster"),
            ("erosion", f"{seed} built-in native platform feature price cut"),
            ("absorption", f"{seed} OpenAI Google Microsoft Anthropic integration"),
        ]
    elif gate == "SWITCHING":
        queries = [
            ("switch_behavior", f"{seed} switched from migrated from replaced with"),
            ("switch_friction", f"{seed} lock-in migration integration retraining contract"),
        ]
    else:
        queries = [("generic", seed)]

    packets = []
    for purpose, query in queries:
        q = re.sub(r"\s+", " ", query).strip()
        if not q:
            continue
        packets.append({
            "fingerprint": _query_fingerprint(group, claims, q),
            "source_group": group,
            "purpose": purpose,
            "claims": claims,
            "query": q[:360],
            "quality_contract": [
                rule
                for code in claims
                for rule in QUALITY_CONTRACT.get(code, [])
            ],
            "support_not_inferred": True,
        })

    return packets


def attach_query_packets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["evidence_query_packets"] = build_query_packets(row)
    return rows
