from __future__ import annotations

import asyncio
import concurrent.futures
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "signalforge-trust-falsification-part3-v1"
TRUTH_BOUNDARY = (
    "FALSIFICATION_SEARCH_RETURNS_UNVALIDATED_COUNTEREVIDENCE_CANDIDATES_ONLY;_"
    "EVIDENCE_REPLAY_READS_VALIDATED_PUBLISHED_LEDGER_ONLY;_"
    "NO_FRESH_TRACE_CAN_WRITE_OR_CHANGE_C01_C14_OR_MARKET_TRUTH"
)

_COUNTER_THEMES: tuple[tuple[str, str], ...] = (
    (
        "CURRENT_SOLUTION_GOOD_ENOUGH",
        "works fine good enough already solved native built in no need",
    ),
    (
        "NO_BUDGET_OR_LOW_VALUE",
        "not worth paying would not pay no budget free enough low priority rare problem",
    ),
    (
        "SWITCHING_TRUST_OR_MARKET_FAILURE",
        "switching cost migration too hard trust security procurement discontinued failed product no traction",
    ),
)

_COUNTER_CUES: dict[str, tuple[str, ...]] = {
    "CURRENT_SOLUTION_GOOD_ENOUGH": (
        "works fine", "good enough", "already solved", "solved by", "built in", "built-in",
        "native support", "native feature", "already handles", "no need", "does everything i need",
    ),
    "NO_BUDGET_OR_LOW_VALUE": (
        "not worth", "wouldn't pay", "would not pay", "won't pay", "will not pay", "no budget",
        "free is enough", "free tier", "too expensive", "low priority", "rare problem", "edge case",
        "not a problem", "doesn't matter", "does not matter",
    ),
    "DIY_SUFFICIENT": (
        "simple script", "small script", "workaround is enough", "manual is fine", "spreadsheet is enough",
        "just use a script", "do it manually", "we just manually", "custom script",
    ),
    "SWITCHING_OR_TRUST_BARRIER": (
        "switching cost", "migration cost", "vendor lock", "lock-in", "procurement", "security review",
        "privacy concern", "trust issue", "too risky", "can't switch", "cannot switch",
    ),
    "FAILED_OR_SHRINKING_ATTEMPT": (
        "shut down", "shutdown", "discontinued", "sunset", "no traction", "couldn't monetize",
        "could not monetize", "failed to monetize", "market shrinking", "abandoned product",
    ),
}


def run_fresh_fast_probe(query: str, description: str = "", *, preserve_query: bool = False) -> dict[str, Any]:
    # Lazy import keeps pure Part-3 trust functions testable without requiring a DB driver.
    from processors.signalforge_founder_idea_loop import run_fresh_fast_probe as _run
    if preserve_query:
        return _run(query, description, search_query_override=query)
    return _run(query, description)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _upper(value: Any) -> str:
    return _clean(value).upper()


def build_falsification_queries(title: str, description: str = "") -> list[dict[str, str]]:
    base = _clean(f"{title} {description}")
    if len(base) < 2:
        return []
    return [
        {"theme": theme, "query": f"{base} {suffix}"}
        for theme, suffix in _COUNTER_THEMES
    ]


def _trace_key(trace: Mapping[str, Any]) -> tuple[str, str]:
    return (_clean(trace.get("url")), _clean(trace.get("title")).lower())


def _phrase_present(text: str, phrase: str) -> bool:
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(phrase.lower()) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, text.lower()) is not None


def _category_direction_supported(category: str, text: str) -> bool:
    """Bounded direction/negation guards for high-impact counterevidence cues."""
    low = text.lower()
    if category == "CURRENT_SOLUTION_GOOD_ENOUGH":
        if re.search(r"\b(?:not|isn't|is not|wasn't|was not)\s+(?:actually\s+)?good enough\b", low):
            return False
        if re.search(r"\b(?:still need|still have to|doesn't solve|does not solve|cannot solve|can't solve)\b", low):
            return False
    elif category == "DIY_SUFFICIENT":
        if re.search(r"\b(?:workaround|manual|spreadsheet|script)\b.{0,24}\b(?:not enough|isn't enough|is not enough|not fine|fails|unreliable)\b", low):
            return False
    elif category == "SWITCHING_OR_TRUST_BARRIER":
        if re.search(r"\b(?:switching|migration) cost\s+(?:is|was|seems|looks)?\s*(?:very\s+)?(?:low|small|minimal|negligible|trivial|cheap)\b", low):
            return False
        if re.search(r"\b(?:migration|switching)\s+(?:is|was)?\s*(?:easy|simple|trivial)\b", low):
            return False
        if re.search(r"\b(?:no|without)\s+(?:security review|procurement|privacy concern|trust issue)\b", low):
            return False
        if re.search(r"\b(?:does not|doesn't|did not|didn't)\s+require\s+(?:a\s+)?(?:security review|procurement)\b", low):
            return False
    elif category == "FAILED_OR_SHRINKING_ATTEMPT":
        if re.search(r"\b(?:did not|didn't|has not|hasn't|was not|wasn't|not)\s+(?:shut down|shutdown|fail(?:ed)?|discontinue(?:d)?|sunset)\b", low):
            return False
        if re.search(r"\b(?:still alive|gaining traction|growing|not abandoned)\b", low):
            return False
    return True


def classify_counterevidence_candidate(trace: Mapping[str, Any]) -> list[str]:
    text = _clean(f"{trace.get('title')} {trace.get('excerpt')}").lower()
    out: list[str] = []
    for category, cues in _COUNTER_CUES.items():
        if any(_phrase_present(text, cue) for cue in cues) and _category_direction_supported(category, text):
            out.append(category)
    return out


def summarize_falsification_runs(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    source_runs: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str, str]] = set()
    trace_map: dict[tuple[str, str], dict[str, Any]] = {}

    for run in runs:
        theme = _clean(run.get("falsification_theme")) or "UNKNOWN"
        query = _clean(run.get("falsification_query"))
        for source in run.get("sources") or []:
            if not isinstance(source, Mapping):
                continue
            key = (theme, query, _clean(source.get("source")))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            source_runs.append({
                "theme": theme,
                "query": query,
                "source": source.get("source"),
                "status": source.get("status"),
                "count": int(source.get("count") or 0),
                "error": source.get("error"),
                "transport": dict(source.get("transport") or {}),
            })
        for trace in run.get("traces") or []:
            if not isinstance(trace, Mapping):
                continue
            key = _trace_key(trace)
            if key == ("", ""):
                continue
            categories = classify_counterevidence_candidate(trace)
            if not categories:
                continue
            current = trace_map.get(key)
            if current is None:
                current = dict(trace)
                current["counterevidence_categories"] = []
                current["falsification_themes"] = []
                current["truth_status"] = "UNVALIDATED_COUNTEREVIDENCE_CANDIDATE"
                trace_map[key] = current
            current["counterevidence_categories"] = sorted(set([*(current.get("counterevidence_categories") or []), *categories]))
            current["falsification_themes"] = sorted(set([*(current.get("falsification_themes") or []), theme]))

    success = sum(1 for x in source_runs if _upper(x.get("status")) == "SUCCESS")
    total = len(source_runs)
    failed = total - success
    if total == 0 or success == 0:
        coverage = "FAILED"
    elif failed == 0:
        coverage = "COMPLETE_FOR_CONFIGURED_FALSIFICATION_SEARCHES"
    else:
        coverage = "PARTIAL"

    candidates = list(trace_map.values())
    category_counts: dict[str, int] = defaultdict(int)
    for row in candidates:
        for category in row.get("counterevidence_categories") or []:
            category_counts[str(category)] += 1

    if coverage == "FAILED":
        interpretation = "SEARCH_FAILED_NO_MARKET_CONCLUSION"
        message = "反證搜尋沒有可靠覆蓋。這不是『沒有反證』；先修 coverage。"
    elif candidates:
        interpretation = "COUNTEREVIDENCE_CANDIDATES_FOUND_REQUIRES_VALIDATION"
        message = "找到可能推翻 thesis 的新線索，但它們仍是未驗證 search traces，不能直接改 Market Truth。"
    else:
        interpretation = "NO_COUNTEREVIDENCE_FOUND_IN_SUCCESSFUL_CONFIGURED_SEARCHES"
        message = "在成功完成的這組反證搜尋裡沒有找到反證候選；這不等於市場上不存在反證。"

    return {
        "coverage": coverage,
        "source_runs": source_runs,
        "successful_source_runs": success,
        "failed_source_runs": failed,
        "candidate_count": len(candidates),
        "category_counts": dict(sorted(category_counts.items())),
        "candidates": candidates[:30],
        "interpretation": interpretation,
        "message": message,
        "truth_boundary": "FRESH_RESULTS_ARE_UNVALIDATED_COUNTEREVIDENCE_CANDIDATES_NOT_PUBLISHED_CONTRADICTIONS",
    }


def _critical_claim_states(trail: Mapping[str, Any]) -> dict[str, str]:
    states = trail.get("claim_states") if isinstance(trail.get("claim_states"), Mapping) else {}
    return {code: _upper(states.get(code)) or "UNKNOWN" for code in ("C03", "C05", "C07", "C09", "C11", "C13")}


def evaluate_kill_advance_park(trail: Mapping[str, Any]) -> dict[str, Any]:
    wedge = trail.get("revenue_wedge") if isinstance(trail.get("revenue_wedge"), Mapping) else {}
    states = _critical_claim_states(trail)
    wedge_decision = _upper(wedge.get("decision")) or "NOT_NOW"
    spend = _upper(wedge.get("existing_spend")) or "UNKNOWN"
    paid_dissat = int((trail.get("paid_dissatisfaction") or {}).get("count") or 0) if isinstance(trail.get("paid_dissatisfaction"), Mapping) else 0
    evidence_count = int(trail.get("published_evidence_count") or 0)

    refuted = [code for code, state in states.items() if state == "REFUTED" and code in {"C03", "C05", "C07", "C09"}]
    supported_core = [code for code in ("C03", "C05", "C07") if states.get(code) in {"SUPPORTED", "PARTIAL"}]

    if wedge_decision == "KILL" or refuted:
        disposition = "KILL"
        why = "Published truth contains a hard commercial/buildability refutation or the existing Revenue Wedge is KILL."
    elif wedge_decision == "TRY_NOW" and spend in {"STRONG", "PARTIAL"} and len(supported_core) >= 3:
        disposition = "ADVANCE"
        why = "Published truth supports pain, buyer, unresolved gap and an existing-spend path strongly enough to move to the registered real-market test."
    elif wedge_decision == "NOT_NOW" and evidence_count >= 3 and spend == "UNKNOWN" and paid_dissat == 0 and states.get("C05") in {"UNKNOWN", "INSUFFICIENT"} and states.get("C07") in {"UNKNOWN", "INSUFFICIENT"}:
        disposition = "PARK"
        why = "Published research exists, but it still has no defensible spend, paid dissatisfaction, buyer reality or unresolved-gap basis. Park rather than deepen by default."
    else:
        disposition = "CONTINUE"
        why = "No Published hard-kill, advance, or park condition is currently triggered."

    return {
        "current_disposition": disposition,
        "basis": why,
        "critical_claim_states": states,
        "conditions": {
            "ADVANCE": "Published pain + buyer + unresolved gap are supported/partial, existing spend is STRONG/PARTIAL, and the Revenue Wedge reaches TRY_NOW.",
            "KILL": "A critical Published claim (pain, buyer, unresolved gap, buildability) is REFUTED, or the Revenue Wedge is KILL.",
            "PARK": "Meaningful Published research exists but still yields no spend / paid dissatisfaction / buyer / gap basis; more generic research is not the default next action.",
        },
        "fresh_search_can_trigger_disposition": False,
        "truth_boundary": "DISPOSITION_IS_DERIVED_FROM_PUBLISHED_TRUTH_ONLY;_UNVALIDATED_FALSIFICATION_TRACES_NEVER_TRIGGER_KILL_ADVANCE_OR_PARK",
    }


def _stance_bucket(value: Any) -> str:
    v = _upper(value)
    if any(token in v for token in ("CONTRADICT", "REFUT", "OPPOSE", "NEGATIVE")):
        return "CONTRADICTING"
    if any(token in v for token in ("SUPPORT", "CONFIRM", "POSITIVE")):
        return "SUPPORTING"
    return "INSUFFICIENT"


def build_evidence_replay_from_rows(*, thesis: Mapping[str, Any], evidence_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    claim_states = thesis.get("claim_states") if isinstance(thesis.get("claim_states"), Mapping) else {}
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        if not bool(row.get("validated")):
            continue
        groups[_clean(row.get("claim_code")) or "UNKNOWN"].append(row)

    all_codes = sorted(set(groups) | {str(x) for x in claim_states.keys()})
    claims: list[dict[str, Any]] = []
    total_support = total_contradict = total_insufficient = 0
    for code in all_codes:
        rows = groups.get(code, [])
        support = [x for x in rows if _stance_bucket(x.get("stance")) == "SUPPORTING"]
        contradict = [x for x in rows if _stance_bucket(x.get("stance")) == "CONTRADICTING"]
        insufficient = [x for x in rows if _stance_bucket(x.get("stance")) == "INSUFFICIENT"]
        total_support += len(support)
        total_contradict += len(contradict)
        total_insufficient += len(insufficient)
        # Independence is a strong claim. Fail closed when the ledger did not
        # provide an explicit source-family identity; different URLs/titles from
        # the same organization are not automatically independent.
        families = {_clean(x.get("source_family_key")) for x in rows if _clean(x.get("source_family_key"))}
        unknown_family_links = sum(1 for x in rows if not _clean(x.get("source_family_key")))
        statement = next((_clean(x.get("claim_statement")) for x in rows if _clean(x.get("claim_statement"))), "")
        evidence = []
        for row in rows:
            evidence.append({
                "stance": _stance_bucket(row.get("stance")),
                "source_type": row.get("source_type"),
                "source_title": row.get("source_title"),
                "source_url": row.get("source_url"),
                "source_family_key": row.get("source_family_key"),
                "excerpt": row.get("excerpt"),
                "directness": row.get("directness"),
                "authority_class": row.get("authority_class"),
                "rationale": row.get("rationale"),
                "validated": True,
            })
        claims.append({
            "claim_code": code,
            "state": _upper(claim_states.get(code)) or (_upper(rows[0].get("claim_state")) if rows else "UNKNOWN") or "UNKNOWN",
            "statement": statement,
            "supporting": len(support),
            "contradicting": len(contradict),
            "insufficient": len(insufficient),
            "independent_source_families": len(families),
            "unknown_source_family_links": unknown_family_links,
            "source_independence_boundary": "ONLY_EXPLICIT_SOURCE_FAMILY_KEYS_COUNT_AS_INDEPENDENT;_URL_OR_TITLE_DIFFERENCE_ALONE_IS_NOT_INDEPENDENCE",
            "evidence": evidence,
        })

    unknown = [x for x in claims if x.get("state") in {"UNKNOWN", "INSUFFICIENT", "PARTIAL", ""}]
    contradicted = [x for x in claims if x.get("state") == "REFUTED" or int(x.get("contradicting") or 0) > 0]
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "thesis_id": thesis.get("thesis_id"),
        "title": thesis.get("representative_title") or thesis.get("title"),
        "summary": {
            "validated_evidence_links": sum(len(x.get("evidence") or []) for x in claims),
            "supporting": total_support,
            "contradicting": total_contradict,
            "insufficient": total_insufficient,
            "unknown_claims": len(unknown),
            "claims_with_contradiction": len(contradicted),
        },
        "claims": claims,
        "search_coverage": {
            "status": "LEDGER_REPLAY_ONLY",
            "message": "Evidence Replay shows what Published ledger supports/contradicts. It does not claim the entire web/source universe was searched successfully.",
        },
        "market_truth_writes": 0,
        "truth_boundary": "EVIDENCE_REPLAY_READS_VALIDATED_PUBLISHED_LEDGER_LINKS_ONLY_AND_CREATES_NO_NEW_CLAIM_OR_EVIDENCE",
    }


def _find_published_thesis(thesis_id: str) -> Mapping[str, Any] | None:
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    portfolio = get_brain_v2_portfolio()
    for thesis in portfolio.get("portfolio") or []:
        if isinstance(thesis, Mapping) and str(thesis.get("thesis_id")) == str(thesis_id):
            return thesis
    return None


async def evidence_replay(thesis_id: str) -> dict[str, Any]:
    thesis = _find_published_thesis(thesis_id)
    if not thesis:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "THESIS_NOT_FOUND",
            "thesis_id": thesis_id,
            "claims": [],
            "market_truth_writes": 0,
            "truth_boundary": "NO_FOUNDER_OR_FRESH_SEARCH_TEXT_IS_SUBSTITUTED_FOR_MISSING_PUBLISHED_THESIS",
        }
    from processors.signalforge_money_trail import _load_candidate_and_evidence
    _, evidence_rows = await _load_candidate_and_evidence(thesis.get("member_candidate_ids") or [])
    return build_evidence_replay_from_rows(thesis=thesis, evidence_rows=evidence_rows)


async def _published_trail(*, thesis_id: str | None, title: str, description: str) -> dict[str, Any]:
    from processors.signalforge_money_trail import build_money_trail_for_thesis, probe_money_trail_direction
    if thesis_id and not str(thesis_id).startswith("probe:"):
        thesis = _find_published_thesis(str(thesis_id))
        if thesis:
            return await build_money_trail_for_thesis(thesis)
    return await probe_money_trail_direction(title=title, description=description)


def _run_falsification_query(item: Mapping[str, str]) -> dict[str, Any]:
    query = item.get("query") or ""
    try:
        # Part 3 owns the counter-hypothesis lens. Do not let Part 1's compact
        # Founder-query selector strip the good-enough / no-budget / switching lens.
        run = run_fresh_fast_probe(query, preserve_query=True)
    except TypeError:
        # Compatibility with acceptance fixtures that monkeypatch the legacy
        # two-argument function shape.
        run = run_fresh_fast_probe(query)
    run["falsification_theme"] = item.get("theme")
    run["falsification_query"] = query
    run["search_query_used"] = run.get("search_query_used") or query
    return run


async def falsify_direction(*, title: str, description: str = "", thesis_id: str | None = None) -> dict[str, Any]:
    title = _clean(title)
    description = _clean(description)
    queries = build_falsification_queries(title, description)
    if not queries:
        return {"engine_version": ENGINE_VERSION, "status": "INVALID_QUERY", "truth_boundary": TRUTH_BOUNDARY}

    published_task = asyncio.create_task(_published_trail(thesis_id=thesis_id, title=title, description=description))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(_run_falsification_query, item) for item in queries]
        runs = [f.result() for f in futures]
    published = await published_task
    summary = summarize_falsification_runs(runs)
    disposition = evaluate_kill_advance_park(published)

    replay = None
    if thesis_id and not str(thesis_id).startswith("probe:"):
        replay = await evidence_replay(str(thesis_id))

    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS" if summary.get("coverage") != "FAILED" else "PARTIAL",
        "target": {"thesis_id": thesis_id, "title": title, "description": description},
        "falsification_queries": queries,
        "fresh_counterevidence_search": summary,
        "published_disposition": disposition,
        "evidence_replay": replay,
        "market_truth_writes": 0,
        "ai_api_calls": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }
