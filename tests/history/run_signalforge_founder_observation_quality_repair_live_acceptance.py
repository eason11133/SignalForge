from __future__ import annotations

import json
import sys
from typing import Any, Mapping

from processors.signalforge_founder_idea_loop import probe_founder_observation_only

TITLE = "AI coding agents finish work but founders cannot efficiently verify whether the work is actually correct and complete"
DESCRIPTION = "Founders using Claude Code, Codex or similar coding agents need to verify requirements, tests and actual completion without manually reviewing everything"

FOUNDER_REVIEW_BEFORE_METRICS = {
    "raw_trace_count": 126,
    "relevant_trace_count": 35,
    "independent_discussion_count": 8,
    "unique_author_count": 12,
}
IMPLEMENTATION_OBJECTS = {"SOFTWARE_IMPLEMENTATION", "CODE_CHANGE", "REFACTOR", "FEATURE", "BUG_FIX"}



def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def emit(payload: Mapping[str, Any]) -> None:
    # Machine-readable live receipts must survive Windows legacy console encodings (for example cp950).
    # Escaping non-ASCII here preserves exact Unicode semantics after json.loads while keeping stdout ASCII-safe.
    print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))
    print("SIGNALFORGE_LIVE_RESULT_JSON=" + json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str))


def fail(message: str, *, result: Mapping[str, Any] | None = None) -> int:
    print(f"LIVE QUALITY FAILURE: {message}", file=sys.stderr)
    if result is not None:
        print(json.dumps(result, ensure_ascii=True, indent=2, default=str), file=sys.stderr)
    return 1


def main() -> int:
    try:
        result = probe_founder_observation_only(title=TITLE, description=DESCRIPTION)
    except Exception as exc:
        payload = {
            "engineering": "PASS_FROM_DETERMINISTIC_GATE",
            "semantic": "PASS_FROM_DETERMINISTIC_GATE",
            "live": "PARTIAL",
            "founder": "PENDING_HUMAN_REVIEW",
            "reason": f"live probe raised {type(exc).__name__}: {exc}",
            "market_truth_writes": 0,
        }
        emit(payload)
        return 10

    fast = result.get("fast_probe") if isinstance(result.get("fast_probe"), Mapping) else {}
    health = [x for x in (fast.get("source_health") or []) if isinstance(x, Mapping)]
    primary = [x for x in (fast.get("top_traces") or []) if isinstance(x, Mapping)]
    source_contrib = [x for x in (fast.get("source_contribution") or []) if isinstance(x, Mapping)]

    raw = int(fast.get("raw_trace_count") or 0)
    relevant = int(fast.get("relevant_trace_count") or 0)
    independent = int(fast.get("independent_discussion_count") or 0)
    unique_authors = int(fast.get("unique_author_count") or 0)
    problem_trace_count = int(fast.get("problem_discussion_trace_count") or fast.get("problem_discussions") or 0)

    violations: list[str] = []
    if result.get("market_truth_writes") != 0:
        violations.append("market_truth_writes must remain 0")
    if result.get("historical_published_evidence_used") is not False or result.get("published_money_trail_used") is not False:
        violations.append("fresh benchmark loaded historical Published/Money-Trail evidence")
    if not isinstance(fast.get("source_contribution"), list):
        violations.append("source_contribution missing")
    if not isinstance(fast.get("source_health"), list):
        violations.append("source_health missing")
    if independent > problem_trace_count:
        violations.append("independent discussion count exceeds relevant discussion trace count")
    if relevant > raw and raw > 0:
        violations.append("relevant trace count exceeds raw source trace count")

    primary_group_keys: list[str] = []
    for index, trace in enumerate(primary):
        rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
        comp = rel.get("compatibility") if isinstance(rel.get("compatibility"), Mapping) else {}
        if rel.get("countable") is not True:
            violations.append(f"primary trace bypassed relevance gate: {clean(trace.get('title'))}")
        if comp.get("workflow_identity_compatible") is not True:
            violations.append(f"primary trace lacks AI-coding implementation workflow identity: {clean(trace.get('title'))}")
        if comp.get("trace_documentation_dominant") is True or comp.get("trace_dominant_object") == "DOCUMENTATION":
            violations.append(f"documentation-dominant trace leaked into Founder primary evidence: {clean(trace.get('title'))}")
        if comp.get("trace_automated_operational_output") is True:
            violations.append(f"agent/bot-generated operational artifact leaked into Founder primary evidence: {clean(trace.get('title'))}")
        trace_roles = set(comp.get("trace_agent_roles") or [])
        trace_objects = set(comp.get("trace_objects") or [])
        # R6 defense-in-depth: R5's deterministic fixture passed while the real
        # multilingual GitHub trace still leaked. Even if dominance inference
        # regresses again, documentation-agent review without direct
        # implementation evidence must make the live installer fail and rollback.
        if (
            "DOCUMENTATION_AGENT_REVIEW" in trace_roles
            and "DOCUMENTATION" in trace_objects
            and comp.get("trace_explicit_implementation_evidence") is not True
        ):
            violations.append(
                f"documentation review lacks direct implementation evidence: {clean(trace.get('title'))}"
            )
        if "AI_CODING_AGENT" not in trace_roles or not (trace_objects & IMPLEMENTATION_OBJECTS):
            violations.append(f"primary trace lacks required actor/object relationship: {clean(trace.get('title'))}")
        raw_excerpt = str(trace.get("excerpt") or "").strip().lower()
        if "generated by [claude code]" in raw_excerpt or raw_excerpt.endswith("generated by claude code"):
            violations.append(f"explicit Claude Code generated footer leaked into Founder primary evidence: {clean(trace.get('title'))}")
        md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
        group = clean((md or {}).get("independence_group_key")) or clean(trace.get("url")) or f"unresolved:{index}"
        primary_group_keys.append(group)

    if len(set(primary_group_keys)) != len(primary_group_keys):
        violations.append("Founder primary traces repeat an independence group; depth evidence leaked into primary selection")

    # Observation metrics must be attributable to explicit source rows.
    contrib_ids = {clean(x.get("source")) for x in source_contrib if clean(x.get("source"))}
    health_ids = {clean(x.get("source")) for x in health if clean(x.get("source"))}
    if health_ids and not health_ids.issubset(contrib_ids):
        violations.append(f"source contribution missing health source(s): {sorted(health_ids - contrib_ids)}")

    if violations:
        payload = {
            "engineering": "PASS_FROM_DETERMINISTIC_GATE",
            "semantic": "FAIL_LIVE",
            "live": "FAIL",
            "founder": "FAIL",
            "violations": violations,
            "before_metrics": FOUNDER_REVIEW_BEFORE_METRICS,
            "metrics": {
                "raw_trace_count": raw,
                "relevant_trace_count": relevant,
                "independent_discussion_count": independent,
                "unique_author_count": unique_authors,
            },
            "primary_traces": primary,
            "source_health": health,
            "market_truth_writes": result.get("market_truth_writes"),
        }
        emit(payload)
        return 1

    success_sources = [x for x in health if str(x.get("status") or "").upper() == "SUCCESS"]
    failed_sources = [x for x in health if str(x.get("status") or "").upper() != "SUCCESS"]
    live_status = "PASS" if success_sources and relevant > 0 and primary else "PARTIAL"
    payload = {
        "engineering": "PASS_FROM_DETERMINISTIC_GATE",
        "semantic": "PASS",
        "live": live_status,
        # Final usefulness is intentionally a human Founder acceptance, not a numeric score.
        "founder": "PENDING_HUMAN_REVIEW",
        "founder_retest_ready": True,
        "hypothesis": {"title": TITLE, "description": DESCRIPTION},
        "before_metrics": FOUNDER_REVIEW_BEFORE_METRICS,
        "metrics": {
            "raw_trace_count": raw,
            "relevant_trace_count": relevant,
            "independent_discussion_count": independent,
            "unique_author_count": unique_authors,
        },
        "source_contribution": source_contrib,
        "source_health": health,
        "failed_sources": failed_sources,
        "primary_traces": [
            {
                "source": x.get("source"),
                "title": x.get("title"),
                "excerpt": x.get("excerpt"),
                "url": x.get("url"),
                "relevance": x.get("thesis_relevance"),
            }
            for x in primary
        ],
        "historical_published_evidence_used": result.get("historical_published_evidence_used"),
        "published_money_trail_used": result.get("published_money_trail_used"),
        "market_truth_writes": result.get("market_truth_writes"),
    }
    emit(payload)
    return 0 if live_status == "PASS" else 10


if __name__ == "__main__":
    raise SystemExit(main())
