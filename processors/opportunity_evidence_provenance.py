"""Evidence provenance and dependence handling for SignalForge U5.

Research basis: truth-discovery/data-fusion work treats source dependence and copying as
first-class evidence problems.  Distinct URLs, tables, or platforms do not automatically
create independent evidence.  U5 therefore normalizes HTML/entity variants and detects
exact, contained, and bounded near-copy content across *all* source families before a
recurrence count is allowed to increase.

This module never decides whether a claim is true.  It only answers whether two supplied
evidence records are sufficiently independent to be counted separately.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from typing import Any

ENGINE_VERSION = "opportunity-evidence-provenance-u5-cross-platform-copy-dependence"
_WORD = re.compile(r"[a-z0-9]{2,}", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
HIGH_COPY_RISK_FAMILIES = {"jobs", "news", "community_raw", "hackernews", "reddit", "reddit_rss"}


def _clean(v: Any) -> str:
    s = html.unescape(str(v or ""))
    s = _TAG.sub(" ", s)
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", s).strip()


def canonical_url(o: dict[str, Any]) -> str:
    raw = o.get("raw_doc") or {}
    url = _clean(o.get("url") or raw.get("url"))
    if not url:
        return ""
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or "").lower()
        path = re.sub(r"/+", "/", p.path or "/").rstrip("/") or "/"
        return urllib.parse.urlunsplit((p.scheme.lower() or "https", host, path, "", ""))
    except Exception:
        return url.lower()


def source_origin(o: dict[str, Any]) -> str:
    raw = o.get("raw_doc") or {}
    source_name = _clean(raw.get("source_name") or o.get("source_name"))
    url = canonical_url(o)
    host = ""
    if url:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
    return source_name.lower() or host or _clean(o.get("source_family") or o.get("source")).lower() or "unknown"


def normalized_content(o: dict[str, Any]) -> str:
    text = _clean(o.get("problem_span") or o.get("reported_problem_span") or o.get("text")).lower()
    # Remove common transport/quote prefixes that create artificial differences between
    # cross-posts.  Semantic nouns and verbs remain; this is only copy detection.
    text = re.sub(r"^(?:quote|quoted|repost|cross[- ]?post)\s*[:\-]?\s*", "", text)
    return " ".join(_WORD.findall(text))


def content_fingerprint(o: dict[str, Any]) -> str:
    text = normalized_content(o)
    return hashlib.sha1(text.encode()).hexdigest()[:20] if text else ""


def _tokens(o: dict[str, Any]) -> list[str]:
    return _WORD.findall(normalized_content(o))


def shingles(o: dict[str, Any], n: int = 3) -> set[str]:
    toks = _tokens(o)
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i+n]) for i in range(len(toks)-n+1)}


def near_duplicate_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    # For very short evidence spans, token containment is more stable than shingles.
    if min(len(ta), len(tb)) < 6:
        sa, sb = set(ta), set(tb)
    else:
        sa, sb = shingles(a, 3), shingles(b, 3)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def _contained_copy(a: dict[str, Any], b: dict[str, Any]) -> bool:
    na, nb = normalized_content(a), normalized_content(b)
    if not na or not nb:
        return False
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter.split()) < 7:
        return False
    ratio = len(shorter) / max(1, len(longer))
    return ratio >= 0.78 and shorter in longer


def provenance_record(o: dict[str, Any]) -> dict[str, Any]:
    fam = _clean(o.get("source_family") or o.get("source")).lower()
    ref = _clean(o.get("source_ref"))
    product = _clean(o.get("product_id"))
    origin = source_origin(o)
    fp = content_fingerprint(o)
    curl = canonical_url(o)
    if fam == "app_store_reviews" and product and ref:
        independence_unit = f"review:{product}:{ref}"
    elif fam in {"stackexchange", "reddit_rss", "reddit", "hackernews", "community_raw"} and ref:
        independence_unit = f"thread:{fam}:{ref}"
    else:
        independence_unit = f"doc:{fam}:{ref or fp}"
    return {
        "source_origin": origin,
        "content_fingerprint": fp,
        "canonical_url": curl,
        "independence_unit": independence_unit,
        "source_family": fam,
        "source_ref": ref,
        "product_id": product or None,
        "copying_risk": "ELEVATED" if fam in HIGH_COPY_RISK_FAMILIES else "NORMAL",
    }


def dependence_reason(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    pa, pb = provenance_record(a), provenance_record(b)
    if pa["independence_unit"] == pb["independence_unit"]:
        return "SAME_INDEPENDENCE_UNIT"
    if pa["canonical_url"] and pa["canonical_url"] == pb["canonical_url"]:
        return "SAME_CANONICAL_URL"
    if pa["content_fingerprint"] and pa["content_fingerprint"] == pb["content_fingerprint"]:
        return "EXACT_CONTENT_COPY"
    if _contained_copy(a, b):
        return "CONTAINED_OR_CROSSPOST_COPY"
    score = near_duplicate_score(a, b)
    threshold = 0.93 if ({pa["source_family"], pb["source_family"]} & HIGH_COPY_RISK_FAMILIES) else 0.96
    if score >= threshold:
        return "NEAR_DUPLICATE_OR_CROSSPOST_CONTENT"
    return None


def content_independent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return dependence_reason(a, b) is None


def independence_summary(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Bounded dependence-aware dedupe.

    Exact units/fingerprints/URLs are indexed O(n).  Near-copy checks are bounded to the
    most recent 32 accepted records in the already-small problem family, so source-copy
    protection cannot recreate the old corpus-wide O(n²) failure mode.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_units: dict[str,dict[str,Any]] = {}
    seen_fp: dict[str,dict[str,Any]] = {}
    seen_url: dict[str,dict[str,Any]] = {}
    near_checks = 0
    for o in group:
        pr = provenance_record(o); unit=pr["independence_unit"]; fp=pr["content_fingerprint"]; curl=pr["canonical_url"]
        dep=None; dep_on=None
        if unit in seen_units:
            dep="SAME_INDEPENDENCE_UNIT"; dep_on=seen_units[unit]
        elif curl and curl in seen_url:
            dep="SAME_CANONICAL_URL"; dep_on=seen_url[curl]
        elif fp and fp in seen_fp:
            dep="EXACT_CONTENT_COPY"; dep_on=seen_fp[fp]
        else:
            # Cross-platform reposts are common in UGC too; do not restrict this to jobs/news.
            for k in kept[-32:]:
                near_checks += 1
                reason = dependence_reason(o, k)
                if reason:
                    dep=reason; dep_on=k; break
        if dep:
            rejected.append({"source_ref":o.get("source_ref"),"source_family":o.get("source_family"),"reason":dep,"depends_on":(dep_on or {}).get("source_ref")})
            continue
        kept.append(o); seen_units[unit]=o
        if fp: seen_fp[fp]=o
        if curl: seen_url[curl]=o
    origins={source_origin(x) for x in kept}
    return {
        "independent_count":len(kept),
        "independent_source_origins":len(origins),
        "source_origins":sorted(origins),
        "kept":kept,
        "rejected_dependencies":rejected,
        "dependency_rejected_count":len(rejected),
        "near_duplicate_checks":near_checks,
        "bounded_cross_platform_copy_detection":True,
        "scalable_exact_index":True,
    }


def static_acceptance() -> dict[str, bool]:
    a={"source_family":"jobs","source_ref":"1","text":"Company X seeks an engineer to automate invoice processing workflows.","url":"https://a.example/jobs/1"}
    b={"source_family":"news","source_ref":"2","text":"Company X seeks an engineer to automate invoice processing workflows.","url":"https://b.example/copy/2"}
    c={"source_family":"app_store_reviews","source_ref":"r1","product_id":"p","problem_span":"The app crashes every time I open a trip."}
    d={"source_family":"app_store_reviews","source_ref":"r2","product_id":"p","problem_span":"Trips crash when I open long itineraries."}
    # Real U4 regressions: HTML entity variants and a one-token suffix must not become
    # independent recurrence merely because they came through different platforms/rows.
    x={"source_family":"community_raw","source_ref":"3423","problem_span":"(Broadcast flag, Macrovision, deliberately miswritten floppy sectors, port dongles, physical manual challenge-response...)"}
    y={"source_family":"community_raw","source_ref":"3424","problem_span":"(Broadcast flag, Macrovision, deliberately miswritten floppy sectors, port dongles, physical manual challenge-response...) Yes?"}
    h1={"source_family":"community_raw","source_ref":"4384","problem_span":"They&#x27;re claiming it&#x27;s possible, but the onboarding is thoroughly broken."}
    h2={"source_family":"hackernews","source_ref":"49353339","problem_span":"They're claiming it's possible, but the onboarding is thoroughly broken."}
    return {
        "distinct_urls_not_automatically_independent": not content_independent(a,b),
        "exact_copy_detected": dependence_reason(a,b)=="EXACT_CONTENT_COPY",
        "independent_firsthand_reviews_retained": content_independent(c,d),
        "provenance_origin_visible": bool(source_origin(a)),
        "u4_minor_suffix_crosspost_blocked": not content_independent(x,y),
        "u4_html_entity_crossplatform_copy_blocked": not content_independent(h1,h2),
        "independence_summary_dedupes_crossplatform": independence_summary([h1,h2])["independent_count"]==1,
    }
