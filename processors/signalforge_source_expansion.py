from __future__ import annotations

import concurrent.futures
import hashlib
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any, Mapping

from processors.signalforge_founder_query_contracts import SOURCE_PROFILE_REGISTRY, classify_source_profile
from processors.signalforge_source_adapters import SourceAdapterError, adapter_ids, run_adapter
from processors.signalforge_source_registry import SOURCE_REGISTRY, observation_families_for_source, registry_snapshot, source_runtime_state

ENGINE_VERSION = "signalforge-r8-idea-research-final-source-expansion-v1"

_LEGACY_FAST_IDS = {"HACKER_NEWS_ALGOLIA", "STACK_OVERFLOW_API", "GITHUB_ISSUES", "GITHUB_REPOSITORIES"}


_TRACKING_QUERY_KEYS = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid","mc_cid","mc_eid","ref","source"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{2,}")

_RECURRENCE_AUTHORITY_ALLOWED = {
    "SOURCE_NATIVE_THREAD_ID",
    "EXPLICIT_SOURCE_INDEPENDENCE_VALIDATED",
    "FOUNDER_VALIDATED_INDEPENDENT",
    "NONE_UNTIL_EXPLICIT_SOURCE_INDEPENDENCE_VALIDATION",
}


def _canonical_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return raw
    host = parts.hostname.lower() if parts.hostname else ""
    port = parts.port
    netloc = host
    if port and not ((parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    query = urlencode([(k,v) for k,v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _TRACKING_QUERY_KEYS])
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), netloc, path.rstrip("/") or "/", query, ""))


def _text_tokens(trace: Mapping[str, Any]) -> set[str]:
    text = f"{trace.get('title') or ''} {trace.get('excerpt') or ''}".lower()
    return {x for x in _TOKEN_RE.findall(text) if len(x) >= 3}


def _content_fingerprint(trace: Mapping[str, Any]) -> str:
    toks = sorted(_text_tokens(trace))[:80]
    seed = " ".join(toks)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20] if seed else ""


def _exact_text_fingerprint(trace: Mapping[str, Any]) -> str:
    text = re.sub(r"\s+", " ", f"{trace.get('title') or ''} {trace.get('excerpt') or ''}".strip().lower())
    if len(text) < 80:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _independence_group_key(trace: Mapping[str, Any], canonical_url: str) -> str:
    md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
    explicit = str((md or {}).get("independence_group_key") or "").strip()
    if explicit:
        return explicit
    source = str(trace.get("source_family") or trace.get("source") or "UNKNOWN").upper()
    # URL fallback is an observation grouping hint only; it never establishes source independence.
    if canonical_url:
        return f"{source}:{canonical_url}"
    fp = _exact_text_fingerprint(trace) or _content_fingerprint(trace)
    return f"{source}:trace:{fp}" if fp else f"{source}:unkeyed"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def dedupe_and_cluster_traces(traces: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate mirrors and cluster related observations without creating recurrence.

    Wave 3 adds two guardrails:
      * exact textual mirrors dedupe even when discovered through different URLs/sources;
      * every trace gets an observation independence-group hint so comments/replies from one
        conversation cannot later masquerade as independent market recurrence.
    """
    deduped: list[dict[str, Any]] = []
    exact_url_seen: set[tuple[str, str]] = set()
    exact_text_seen: set[str] = set()
    for raw in traces:
        trace = dict(raw)
        curl = _canonical_url(trace.get("url"))
        fp = _content_fingerprint(trace)
        exact_fp = _exact_text_fingerprint(trace)
        url_key = (curl, fp) if curl else ("", fp)
        if fp and url_key in exact_url_seen:
            continue
        # Long exact text mirrored by a search index, feed, social repost or canonical page
        # is one observation, not multiple recurrence. Short generic snippets are not collapsed.
        if exact_fp and exact_fp in exact_text_seen:
            continue
        if fp:
            exact_url_seen.add(url_key)
        if exact_fp:
            exact_text_seen.add(exact_fp)
        md = dict(trace.get("metadata") or {})
        md["canonical_url"] = curl or None
        md["content_fingerprint"] = fp or None
        md["exact_text_fingerprint"] = exact_fp or None
        md["independence_group_key"] = _independence_group_key(trace, curl)
        supplied_authority = str(md.get("recurrence_authority") or "").upper()
        md["recurrence_authority"] = (
            supplied_authority
            if supplied_authority in _RECURRENCE_AUTHORITY_ALLOWED
            else "NONE_UNTIL_EXPLICIT_SOURCE_INDEPENDENCE_VALIDATION"
        )
        trace["metadata"] = md
        deduped.append(trace)

    clusters: list[dict[str, Any]] = []
    assigned: set[int] = set()
    token_sets = [_text_tokens(x) for x in deduped]
    for i, trace in enumerate(deduped):
        if i in assigned:
            continue
        members = [i]
        assigned.add(i)
        for j in range(i + 1, len(deduped)):
            if j in assigned:
                continue
            left = trace.get("metadata") or {}
            right = deduped[j].get("metadata") or {}
            same_url = bool(left.get("canonical_url")) and left.get("canonical_url") == right.get("canonical_url")
            sim = _jaccard(token_sets[i], token_sets[j])
            if same_url or sim >= 0.72:
                members.append(j)
                assigned.add(j)
        member_rows = [deduped[k] for k in members]
        cid = hashlib.sha256("|".join(str((x.get("metadata") or {}).get("content_fingerprint") or x.get("url") or k) for k, x in zip(members, member_rows)).encode("utf-8")).hexdigest()[:16]
        group_keys = sorted({str((x.get("metadata") or {}).get("independence_group_key") or "") for x in member_rows if (x.get("metadata") or {}).get("independence_group_key")})
        cluster_id = f"obs-{cid}"
        for k in members:
            md = dict(deduped[k].get("metadata") or {})
            md["observation_cluster_id"] = cluster_id
            md["cluster_recurrence_authority"] = "DO_NOT_MULTIPLY_RECURRENCE_WITHIN_CLUSTER"
            deduped[k]["metadata"] = md
        clusters.append({
            "cluster_id": cluster_id,
            "member_count": len(member_rows),
            "source_ids": sorted({str(x.get("source") or "") for x in member_rows if x.get("source")}),
            "source_families": sorted({str(x.get("source_family") or "") for x in member_rows if x.get("source_family")}),
            "content_units": sorted({str(x.get("content_unit") or "") for x in member_rows if x.get("content_unit")}),
            "independence_group_keys": group_keys,
            "distinct_independence_group_count": len(group_keys),
            "member_indexes": members,
            "independence_status": "UNVALIDATED_DO_NOT_COUNT_AS_MARKET_RECURRENCE",
        })
    return deduped, clusters

def _truthy_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _required_observation_families(hypothesis_text: str) -> set[str]:
    profile = classify_source_profile(hypothesis_text).get("source_profile") or "UNCLASSIFIED"
    row = SOURCE_PROFILE_REGISTRY.get(profile) or {}
    return {str(x).upper() for x in (row.get("observation_source_families") or [])}


def plan_source_expansion(hypothesis_text: str, *, explicit_source_ids: list[str] | None = None) -> dict[str, Any]:
    classification = classify_source_profile(hypothesis_text)
    required = _required_observation_families(hypothesis_text)
    master_enabled = _truthy_env("SIGNALFORGE_SOURCE_EXPANSION_ENABLED", True)
    selected: list[str] = []
    skipped: list[dict[str, Any]] = []

    candidates = explicit_source_ids if explicit_source_ids is not None else adapter_ids()
    for source_id in candidates:
        if source_id in _LEGACY_FAST_IDS or source_id not in SOURCE_REGISTRY:
            continue
        spec = SOURCE_REGISTRY[source_id]
        state = source_runtime_state(source_id)
        if not master_enabled and explicit_source_ids is None:
            skipped.append({"source_id": source_id, "reason": "SOURCE_EXPANSION_DISABLED"})
            continue
        if state.get("runtime_state") != "READY":
            skipped.append({"source_id": source_id, "reason": state.get("runtime_state")})
            continue
        obs = {str(x).upper() for x in observation_families_for_source(source_id)}
        # Broad web, RSS and news are useful fallbacks. Domain-specific social/video/jobs
        # only execute when they can cover at least one required observation family.
        broad = source_id in {"BRAVE_WEB", "GDELT_DOC", "RSS_ATOM"}
        # System Reset fail-closed routing: if no source-profile contract exists,
        # do not spray an unknown business problem across every READY community.
        # Keep only broad discovery surfaces and report SOURCE_FIT_UNKNOWN later.
        if not required and not broad:
            skipped.append({"source_id": source_id, "reason": "SOURCE_PROFILE_UNDEFINED_FAIL_CLOSED"})
            continue
        if required and not broad and not (obs & required):
            skipped.append({"source_id": source_id, "reason": "NOT_RELEVANT_TO_SOURCE_PROFILE"})
            continue
        selected.append(source_id)

    full_absence_sources = [sid for sid in selected if str(SOURCE_REGISTRY[sid].absence_adequacy).upper() == "FULL"]
    partial_absence_sources = [sid for sid in selected if str(SOURCE_REGISTRY[sid].absence_adequacy).upper() != "FULL"]
    return {
        "engine_version": ENGINE_VERSION,
        "source_profile": classification.get("source_profile"),
        "problem_domain": classification.get("problem_domain"),
        "buyer_type": classification.get("buyer_type"),
        "workflow_type": classification.get("workflow_type"),
        "required_observation_families": sorted(required),
        "selected_source_ids": selected,
        "full_absence_adequacy_source_ids": full_absence_sources,
        "partial_absence_adequacy_source_ids": partial_absence_sources,
        "skipped": skipped,
        "registry": registry_snapshot(),
        "market_truth_writes": 0,
        "truth_boundary": "SOURCE_PLANNING_IS_ROUTING_METADATA_ONLY_AND_CANNOT_CREATE_MARKET_TRUTH;_PARTIAL_DISCOVERY_SOURCES_MAY_FIND_EVIDENCE_BUT_CANNOT_BY_THEMSELVES_JUSTIFY_ZERO_TRACE_MARKET_ABSENCE",
    }


def _run_one(source_id: str, query: str) -> dict[str, Any]:
    try:
        return run_adapter(source_id, query)
    except SourceAdapterError as exc:
        return {
            "source": source_id,
            "source_family": SOURCE_REGISTRY[source_id].source_family if source_id in SOURCE_REGISTRY else source_id,
            "observation_source_families": list(SOURCE_REGISTRY[source_id].observation_families) if source_id in SOURCE_REGISTRY else [],
            "status": "FAILED",
            "query": query,
            "count": 0,
            "traces": [],
            "error": str(exc),
            "transport": {"status_code": exc.status_code, "category": exc.category},
            "truth_boundary": "FAILED_SOURCE_ADAPTER_CANNOT_BE_INTERPRETED_AS_MARKET_ABSENCE",
        }
    except Exception as exc:
        return {
            "source": source_id,
            "source_family": SOURCE_REGISTRY[source_id].source_family if source_id in SOURCE_REGISTRY else source_id,
            "observation_source_families": list(SOURCE_REGISTRY[source_id].observation_families) if source_id in SOURCE_REGISTRY else [],
            "status": "FAILED",
            "query": query,
            "count": 0,
            "traces": [],
            "error": f"{type(exc).__name__}: {exc}",
            "transport": {"category": "UNEXPECTED"},
            "truth_boundary": "FAILED_SOURCE_ADAPTER_CANNOT_BE_INTERPRETED_AS_MARKET_ABSENCE",
        }


def run_source_expansion(hypothesis_text: str, query: str, *, explicit_source_ids: list[str] | None = None) -> dict[str, Any]:
    plan = plan_source_expansion(hypothesis_text, explicit_source_ids=explicit_source_ids)
    source_ids = list(plan.get("selected_source_ids") or [])
    started = time.perf_counter()
    if not source_ids:
        return {
            "engine_version": ENGINE_VERSION,
            "status": "NO_EXPANSION_SOURCES_READY",
            "plan": plan,
            "sources": [],
            "traces": [],
            "elapsed_ms": 0,
            "market_truth_writes": 0,
        }
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(source_ids))) as pool:
        futures = [pool.submit(_run_one, source_id, query) for source_id in source_ids]
        sources = [f.result() for f in futures]
    raw_traces: list[dict[str, Any]] = []
    for source in sources:
        for trace in source.get("traces") or []:
            if isinstance(trace, Mapping):
                raw_traces.append(dict(trace))
    traces, clusters = dedupe_and_cluster_traces(raw_traces)
    successful = [x for x in sources if x.get("status") == "SUCCESS"]
    failed = [x for x in sources if x.get("status") != "SUCCESS"]
    status = "PASS" if successful and not failed else ("PARTIAL" if successful else "FAILED")
    return {
        "engine_version": ENGINE_VERSION,
        "status": status,
        "plan": plan,
        "sources": sources,
        "traces": traces[:160],
        "clusters": clusters[:160],
        "raw_trace_count": len(raw_traces),
        "deduped_trace_count": len(traces),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "market_truth_writes": 0,
        "truth_boundary": "EXPANDED_SOURCE_OUTPUT_IS_UNVALIDATED_SEARCH_TRACE_ONLY;_RECURRENCE_AUTHORITY_MUST_BE_EXPLICIT_AND_ALLOWED;_MIRROR_CLUSTERS_COLLAPSE_RECURRENCE_INSTEAD_OF_MULTIPLYING_IT",
    }


def _followup_query_allowed(cost_policy: Any) -> bool:
    """Return whether a source may run bounded query variants.

    Free sources commonly declare ``NO_METERED_COST_DECLARED``.  A substring
    test for ``METERED`` therefore inverts the meaning and silently disables
    follow-up research lenses.  Only explicitly metered / pay-per-resource /
    plan-gated policies are suppressed here.
    """
    policy = str(cost_policy or "").strip().upper()
    if policy.startswith("NO_METERED"):
        return True
    if "PAY_PER_RESOURCE" in policy:
        return False
    if policy.startswith("METERED"):
        return False
    if "PLAN_GATED" in policy:
        return False
    return True


def run_source_expansion_queries(
    hypothesis_text: str,
    queries: list[str] | tuple[str, ...],
    *,
    explicit_source_ids: list[str] | None = None,
    max_queries: int = 2,
) -> dict[str, Any]:
    """Run a bounded multi-query expansion and dedupe across query variants.

    Query diversity improves recall without increasing source authority. Every
    returned trace remains UNVALIDATED_SEARCH_TRACE and recurrence authority stays
    NONE until explicit independence validation.
    """
    cleaned: list[str] = []
    for q in queries:
        q = re.sub(r"\s+", " ", str(q or "")).strip()
        if q and q not in cleaned:
            cleaned.append(q)
        if len(cleaned) >= max(1, int(max_queries)):
            break
    if not cleaned:
        cleaned = [str(hypothesis_text or "").strip()]

    started = time.perf_counter()
    runs: list[dict[str, Any]] = []
    first = run_source_expansion(hypothesis_text, cleaned[0], explicit_source_ids=explicit_source_ids)
    runs.append(first)
    first_selected = list((first.get("plan") or {}).get("selected_source_ids") or [])
    first_successful = {
        str(row.get("source") or "")
        for row in (first.get("sources") or [])
        if isinstance(row, Mapping) and str(row.get("status") or "").upper() == "SUCCESS"
    }
    for q in cleaned[1:]:
        if explicit_source_ids is not None:
            # Explicit callers may intentionally probe a different query after a
            # query-specific failure; keep their requested set unchanged.
            followup_ids = list(explicit_source_ids)
        else:
            # Normal Idea Research should not wait on the same transport failure
            # for every query lens. Only sources that actually completed the first
            # query are eligible for follow-up variants. The first failure remains
            # visible in source health/diagnostics.
            followup_ids = [
                sid for sid in first_selected
                if sid in first_successful
                and sid in SOURCE_REGISTRY
                and _followup_query_allowed(SOURCE_REGISTRY[sid].cost_policy)
            ]
        if not followup_ids:
            continue
        runs.append(run_source_expansion(hypothesis_text, q, explicit_source_ids=followup_ids))
    raw_sources: list[dict[str, Any]] = []
    raw_traces: list[dict[str, Any]] = []
    for run in runs:
        raw_sources.extend([dict(x) for x in (run.get("sources") or []) if isinstance(x, Mapping)])
        raw_traces.extend([dict(x) for x in (run.get("traces") or []) if isinstance(x, Mapping)])

    traces, clusters = dedupe_and_cluster_traces(raw_traces)

    # Aggregate source health by source id. Success on any query keeps the source
    # visible as SUCCESS_WITH_QUERY_VARIANTS; failures remain inspectable.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in raw_sources:
        grouped.setdefault(str(row.get("source") or "UNKNOWN"), []).append(row)
    sources: list[dict[str, Any]] = []
    for sid, rows in grouped.items():
        statuses = [str(r.get("status") or "FAILED") for r in rows]
        success_rows = [r for r in rows if r.get("status") == "SUCCESS"]
        representative = dict(success_rows[0] if success_rows else rows[0])
        representative["status"] = "SUCCESS" if success_rows else statuses[0]
        representative["count"] = sum(int(r.get("count") or 0) for r in rows)
        representative["query_variants"] = [
            str(r.get("final_search_query_used") or r.get("query") or "") for r in rows
            if str(r.get("final_search_query_used") or r.get("query") or "").strip()
        ]
        representative["query_run_statuses"] = statuses
        representative["traces"] = []
        sources.append(representative)

    successes = [r for r in sources if r.get("status") == "SUCCESS"]
    failures = [r for r in sources if r.get("status") != "SUCCESS"]
    if successes and not failures:
        status = "PASS"
    elif successes:
        status = "PARTIAL"
    else:
        status = "FAILED" if sources else "NO_EXPANSION_SOURCES_READY"

    return {
        "engine_version": ENGINE_VERSION,
        "status": status,
        "plan": runs[0].get("plan") if runs else plan_source_expansion(hypothesis_text, explicit_source_ids=explicit_source_ids),
        "queries_used": cleaned,
        "query_runs": [
            {
                "query": q,
                "status": run.get("status"),
                "raw_trace_count": run.get("raw_trace_count"),
                "deduped_trace_count": run.get("deduped_trace_count"),
            }
            for q, run in zip(cleaned, runs)
        ],
        "sources": sources,
        "traces": traces[:160],
        "clusters": clusters[:160],
        "raw_trace_count": len(raw_traces),
        "deduped_trace_count": len(traces),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "market_truth_writes": 0,
        "truth_boundary": "MULTI_QUERY_EXPANSION_IMPROVES_RECALL_ONLY;_ALL_OUTPUT_REMAINS_UNVALIDATED_AND_CANNOT_CREATE_MARKET_TRUTH",
    }
