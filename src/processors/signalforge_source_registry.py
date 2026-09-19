from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "signalforge-source-registry-wave4-v1"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_family: str
    platform: str
    access_mode: str
    auth_type: str
    commercial_status: str
    enabled_by_default: bool
    content_units: tuple[str, ...]
    observation_families: tuple[str, ...]
    supports_search: bool = True
    supports_comments: bool = False
    supports_replies: bool = False
    supports_history: bool = False
    credential_env: str | None = None
    config_env: str | None = None
    notes: str = ""
    persistence_policy: str = "DURABLE_TRACE_METADATA_ALLOWED"
    cost_policy: str = "NO_METERED_COST_DECLARED"
    discovery_scope: str = "STRUCTURED_SEARCH"
    absence_adequacy: str = "FULL"


SOURCE_REGISTRY: dict[str, SourceSpec] = {
    "HACKER_NEWS_ALGOLIA": SourceSpec(
        "HACKER_NEWS_ALGOLIA", "HACKER_NEWS", "Hacker News", "PUBLIC_API", "NONE", "PUBLIC_API_TERMS", True,
        ("POST", "COMMENT"), ("HACKER_NEWS", "DEVELOPER_COMMUNITIES"), supports_comments=True, supports_history=True,
    ),
    "STACK_OVERFLOW_API": SourceSpec(
        "STACK_OVERFLOW_API", "STACK_OVERFLOW", "Stack Overflow", "PUBLIC_API", "NONE", "PUBLIC_API_TERMS", True,
        ("QUESTION", "ANSWER", "COMMENT"), ("STACK_OVERFLOW", "DEVELOPER_COMMUNITIES"), supports_comments=True, supports_replies=True, supports_history=True,
    ),
    "GITHUB_ISSUES": SourceSpec(
        "GITHUB_ISSUES", "GITHUB_ISSUES", "GitHub", "OFFICIAL_API", "OPTIONAL_TOKEN", "TERMS_GOVERNED", True,
        ("ISSUE", "ISSUE_COMMENT"), ("GITHUB_ISSUES", "DEVELOPER_COMMUNITIES", "SOFTWARE_WORKFLOW_DISCUSSIONS"), supports_comments=True, supports_history=True,
        credential_env="GITHUB_TOKEN",
    ),
    "GITHUB_REPOSITORIES": SourceSpec(
        "GITHUB_REPOSITORIES", "GITHUB_REPOSITORIES", "GitHub", "OFFICIAL_API", "OPTIONAL_TOKEN", "TERMS_GOVERNED", True,
        ("REPOSITORY", "README_METADATA"), ("GITHUB_REPOSITORIES", "DEVELOPER_TOOL_CATALOG"), supports_history=True,
        credential_env="GITHUB_TOKEN",
    ),
    "GITHUB_DISCUSSIONS": SourceSpec(
        "GITHUB_DISCUSSIONS", "GITHUB_DISCUSSIONS", "GitHub Discussions", "OFFICIAL_GRAPHQL_API", "BEARER_TOKEN", "TERMS_GOVERNED", False,
        ("DISCUSSION", "DISCUSSION_COMMENT", "DISCUSSION_REPLY"),
        ("DEVELOPER_COMMUNITIES", "SOFTWARE_WORKFLOW_DISCUSSIONS", "DOMAIN_FORUMS"),
        supports_comments=True, supports_replies=True, supports_history=True,
        credential_env="GITHUB_TOKEN", config_env="SIGNALFORGE_GITHUB_DISCUSSION_REPOS",
        notes="Requires explicit owner/repo allowlist plus server-side GitHub token; GraphQL read only.",
    ),
    "BRAVE_WEB": SourceSpec(
        "BRAVE_WEB", "BRAVE_WEB", "Brave Search", "OFFICIAL_API", "API_KEY", "COMMERCIAL_API_ALLOWED", False,
        ("WEB_PAGE", "NEWS_RESULT", "VIDEO_RESULT"),
        (
            "GENERAL_WEB", "AGENCY_SERVICE_PAGES", "AGENCY_REVIEWS", "PRODUCT_DISCOVERY_STRATEGY_PAGES",
            "RESEARCH_TOOL_REVIEWS", "NONPROFIT_SERVICE_PAGES", "ASSOCIATION_SOFTWARE_REVIEWS",
            "EDTECH_REVIEWS", "ECOMMERCE_APP_REVIEWS", "COMPANY_SERVICE_PAGES",
        ),
        supports_history=False, credential_env="BRAVE_SEARCH_API_KEY",
        notes="Server-side key only. Never expose X-Subscription-Token to frontend.",
    ),
    "GDELT_DOC": SourceSpec(
        "GDELT_DOC", "GDELT_NEWS", "GDELT", "PUBLIC_SEARCH_API", "NONE", "PUBLIC_INDEX_LINKS_ONLY", False,
        ("NEWS_ARTICLE_INDEX",), ("NEWS", "MARKET_NEWS", "COMPANY_NEWS", "INDUSTRY_NEWS"), supports_history=True,
        config_env="SIGNALFORGE_GDELT_ENABLED",
        notes="Store metadata/snippets/source URLs, not republished article bodies.",
    ),
    "YOUTUBE_DATA_API": SourceSpec(
        "YOUTUBE_DATA_API", "YOUTUBE", "YouTube", "OFFICIAL_API", "API_KEY", "TERMS_GOVERNED", False,
        ("VIDEO", "TOP_LEVEL_COMMENT", "COMMENT_REPLY"),
        (
            "VIDEO_DISCUSSIONS", "FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES",
            "NONPROFIT_COMMUNITIES", "ECOMMERCE_OPERATOR_DISCUSSIONS", "PRODUCT_REVIEWS_VIDEO",
        ),
        supports_comments=True, supports_replies=True, supports_history=True, credential_env="YOUTUBE_API_KEY",
    ),
    "THREADS_API": SourceSpec(
        "THREADS_API", "THREADS", "Threads", "OFFICIAL_API", "OAUTH_USER_OR_APP_TOKEN", "TERMS_GOVERNED", False,
        ("POST", "REPLY"),
        ("FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "CREATOR_COMMUNITIES"),
        supports_comments=True, supports_replies=True, supports_history=True, credential_env="THREADS_ACCESS_TOKEN",
        notes="Requires threads_keyword_search; replies additionally require threads_read_replies.",
    ),
    "GREENHOUSE_PUBLIC_JOBS": SourceSpec(
        "GREENHOUSE_PUBLIC_JOBS", "GREENHOUSE_JOBS", "Greenhouse", "PUBLIC_API", "NONE", "PUBLIC_JOB_METADATA", False,
        ("JOB_POST",), ("CONSULTING_JOB_POSTS", "COMPANY_JOB_POSTS", "HIRING_SPEND_SIGNAL"), supports_history=False,
        config_env="SIGNALFORGE_GREENHOUSE_BOARDS",
    ),
    "LEVER_PUBLIC_JOBS": SourceSpec(
        "LEVER_PUBLIC_JOBS", "LEVER_JOBS", "Lever", "PUBLIC_API", "NONE", "PUBLIC_JOB_METADATA", False,
        ("JOB_POST",), ("CONSULTING_JOB_POSTS", "COMPANY_JOB_POSTS", "HIRING_SPEND_SIGNAL"), supports_history=False,
        config_env="SIGNALFORGE_LEVER_SITES",
    ),
    "RSS_ATOM": SourceSpec(
        "RSS_ATOM", "PUBLIC_FEEDS", "RSS/Atom", "PUBLIC_FEED", "NONE", "SOURCE_TERMS_GOVERNED", False,
        ("FEED_ITEM",), ("BLOGS", "FOUNDER_COMMUNITIES", "COMPANY_BLOGS", "INDUSTRY_FEEDS"), supports_history=True,
        config_env="SIGNALFORGE_PUBLIC_FEEDS",
        notes="Only explicitly configured public http(s) feeds; SSRF-hardened fetch required.",
    ),

    "BLUESKY_PUBLIC_SEARCH": SourceSpec(
        "BLUESKY_PUBLIC_SEARCH", "BLUESKY", "Bluesky", "PUBLIC_API", "NONE", "PUBLIC_READ_API", True,
        ("POST", "REPLY"),
        ("FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "MERCHANT_COMMUNITIES", "DEVELOPER_COMMUNITIES"),
        supports_comments=True, supports_replies=True, supports_history=True,
        notes="Public app.bsky.* GET reads via public.api.bsky.app; no user session required.",
    ),
    "X_RECENT_SEARCH": SourceSpec(
        "X_RECENT_SEARCH", "X", "X", "OFFICIAL_API", "BEARER_TOKEN", "PAY_PER_USE_TERMS_GOVERNED", False,
        ("POST", "REPLY"),
        ("FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "MERCHANT_COMMUNITIES", "DEVELOPER_COMMUNITIES", "PUBLIC_MARKET_CONVERSATIONS"),
        supports_comments=True, supports_replies=True, supports_history=False, credential_env="X_BEARER_TOKEN",
        notes="Recent Search covers the last 7 days. Metered reads; hard per-probe result/cost budget required.",
        cost_policy="PAY_PER_RESOURCE_BOUNDED_BY_PROBE_BUDGET",
    ),
    "DISCOURSE_PUBLIC": SourceSpec(
        "DISCOURSE_PUBLIC", "DISCOURSE", "Discourse", "PUBLIC_SITE_API", "NONE", "SOURCE_TERMS_GOVERNED", False,
        ("TOPIC", "POST"),
        ("FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "MERCHANT_COMMUNITIES", "DEVELOPER_COMMUNITIES", "DOMAIN_FORUMS"),
        supports_comments=True, supports_replies=True, supports_history=True, config_env="SIGNALFORGE_DISCOURSE_SITES",
        notes="Only explicitly configured public Discourse sites; SSRF-hardened and no login/session reuse.",
    ),
    "MASTODON_SEARCH": SourceSpec(
        "MASTODON_SEARCH", "MASTODON", "Mastodon", "OFFICIAL_INSTANCE_API", "NONE_OR_INSTANCE_TOKEN", "INSTANCE_DEPENDENT_PUBLIC_READ", False,
        ("STATUS", "REPLY"),
        ("PUBLIC_MARKET_CONVERSATIONS", "FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "MERCHANT_COMMUNITIES"),
        supports_comments=True, supports_replies=True, supports_history=False, config_env="SIGNALFORGE_MASTODON_INSTANCES",
        notes="Wave 4 uses explicit public Mastodon instances and hashtag timelines only. Public preview may be disabled per instance; no browser/session auth is used.",
        discovery_scope="HASHTAG_TIMELINE_ONLY", absence_adequacy="PARTIAL",
    ),
    "LEMMY_PUBLIC": SourceSpec(
        "LEMMY_PUBLIC", "LEMMY", "Lemmy", "PUBLIC_INSTANCE_API", "NONE", "PUBLIC_API_INSTANCE_TERMS", False,
        ("POST", "COMMENT"),
        ("FOUNDER_COMMUNITIES", "AGENCY_COMMUNITIES", "STUDENT_COMMUNITIES", "NONPROFIT_COMMUNITIES", "MERCHANT_COMMUNITIES", "PUBLIC_MARKET_CONVERSATIONS", "DOMAIN_FORUMS"),
        supports_comments=True, supports_replies=True, supports_history=True, config_env="SIGNALFORGE_LEMMY_INSTANCES",
        notes="Explicit public Lemmy instances only; uses public search/comment APIs without account cookies or tokens.",
    ),
    "STACK_EXCHANGE_NETWORK": SourceSpec(
        "STACK_EXCHANGE_NETWORK", "STACK_EXCHANGE_NETWORK", "Stack Exchange Network", "PUBLIC_API", "NONE", "PUBLIC_API_TERMS", False,
        ("QUESTION", "ANSWER", "COMMENT"),
        ("PROFESSIONAL_COMMUNITIES", "WORKPLACE_COMMUNITIES", "STUDENT_COMMUNITIES", "DOMAIN_QA", "DEVELOPER_COMMUNITIES"),
        supports_comments=True, supports_replies=True, supports_history=True, config_env="SIGNALFORGE_STACKEXCHANGE_SITES",
        notes="Explicit api_site_parameter allowlist; public read endpoints only.",
    ),
    "ASHBY_PUBLIC_JOBS": SourceSpec(
        "ASHBY_PUBLIC_JOBS", "ASHBY_JOBS", "Ashby", "PUBLIC_JOB_POSTING_API", "NONE", "PUBLIC_JOB_METADATA", False,
        ("JOB_POST",), ("CONSULTING_JOB_POSTS", "COMPANY_JOB_POSTS", "HIRING_SPEND_SIGNAL"), supports_history=False,
        config_env="SIGNALFORGE_ASHBY_BOARDS", notes="Public Ashby job-board posting API; can include published compensation metadata when exposed by the board.",
    ),
    "GOOGLE_PLACES_REVIEWS": SourceSpec(
        "GOOGLE_PLACES_REVIEWS", "GOOGLE_PLACES", "Google Places", "OFFICIAL_API", "API_KEY", "PERSISTENCE_PATH_INCOMPATIBLE", False,
        ("PLACE", "REVIEW"), ("LOCAL_BUSINESS_REVIEWS", "SERVICE_REVIEWS"), supports_comments=False, supports_history=False,
        credential_env="GOOGLE_PLACES_API_KEY",
        notes="Registry-only until SignalForge has an ephemeral/non-persistent attribution-compliant review path; Places content storage/caching is restricted.",
        persistence_policy="EPHEMERAL_DISPLAY_ONLY_REQUIRED", cost_policy="METERED_API",
    ),
    "YELP_REVIEWS": SourceSpec(
        "YELP_REVIEWS", "YELP", "Yelp", "OFFICIAL_API", "API_KEY", "PLAN_AND_LICENSE_REVIEW_REQUIRED", False,
        ("BUSINESS", "REVIEW_EXCERPT"), ("LOCAL_BUSINESS_REVIEWS", "SERVICE_REVIEWS"), supports_history=False,
        credential_env="YELP_API_KEY",
        notes="Registry-only: reviews endpoint requires Enhanced/Premium plan and only returns limited excerpts; do not count as durable coverage before license review.",
        persistence_policy="LICENSE_REVIEW_BEFORE_DURABLE_USE", cost_policy="PLAN_GATED_API",
    ),

    "PRODUCT_HUNT_API": SourceSpec(
        "PRODUCT_HUNT_API", "PRODUCT_HUNT", "Product Hunt", "OFFICIAL_API", "ACCESS_TOKEN", "COMMERCIAL_AGREEMENT_REQUIRED", False,
        ("PRODUCT", "COMMENT"), ("PRODUCT_LAUNCHES", "FOUNDER_COMMUNITIES", "PRODUCT_DISCOVERY"), supports_comments=True, supports_history=True,
        credential_env="PRODUCT_HUNT_TOKEN", notes="Official docs state API must not be used commercially without contacting Product Hunt.",
    ),
    "REDDIT_API": SourceSpec(
        "REDDIT_API", "REDDIT", "Reddit", "OFFICIAL_API", "OAUTH", "COMMERCIAL_AGREEMENT_REQUIRED", False,
        ("POST", "COMMENT", "REPLY"), ("COMMUNITIES", "REVIEWS", "FIRSTHAND_PAIN"), supports_comments=True, supports_replies=True, supports_history=True,
        notes="Disabled by default for commercial SignalForge until commercial data agreement is confirmed.",
    ),
    "TIKTOK_RESEARCH": SourceSpec(
        "TIKTOK_RESEARCH", "TIKTOK", "TikTok", "RESEARCH_API", "RESEARCH_AUTH", "NON_COMMERCIAL_RESEARCH_ONLY", False,
        ("VIDEO", "COMMENT", "REPLY"), ("CONSUMER_DISCUSSIONS",), supports_comments=True, supports_replies=True, supports_history=True,
        notes="Not eligible as a commercial SignalForge source under current Research API eligibility.",
    ),
}


_BLOCKED_COMMERCIAL_STATUSES = {
    "COMMERCIAL_AGREEMENT_REQUIRED",
    "NON_COMMERCIAL_RESEARCH_ONLY",
    "PERSISTENCE_PATH_INCOMPATIBLE",
    "PLAN_AND_LICENSE_REVIEW_REQUIRED",
}


def _split_csv(value: str) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _configured_value(spec: SourceSpec) -> bool:
    if spec.source_id == "RSS_ATOM":
        return bool(os.getenv("SIGNALFORGE_PUBLIC_FEEDS", "").strip() or os.getenv("SIGNALFORGE_PUBLIC_FEEDS_JSON", "").strip())
    if spec.source_id == "DISCOURSE_PUBLIC":
        return bool(os.getenv("SIGNALFORGE_DISCOURSE_SITES", "").strip() or os.getenv("SIGNALFORGE_DISCOURSE_SITES_JSON", "").strip())
    if spec.source_id == "MASTODON_SEARCH":
        return bool(os.getenv("SIGNALFORGE_MASTODON_INSTANCES", "").strip() or os.getenv("SIGNALFORGE_MASTODON_INSTANCES_JSON", "").strip())
    if spec.source_id == "LEMMY_PUBLIC":
        return bool(os.getenv("SIGNALFORGE_LEMMY_INSTANCES", "").strip() or os.getenv("SIGNALFORGE_LEMMY_INSTANCES_JSON", "").strip())
    if spec.source_id == "STACK_EXCHANGE_NETWORK":
        return bool(os.getenv("SIGNALFORGE_STACKEXCHANGE_SITES", "").strip() or os.getenv("SIGNALFORGE_STACKEXCHANGE_SITES_JSON", "").strip())
    if spec.source_id == "GDELT_DOC":
        raw = os.getenv("SIGNALFORGE_GDELT_ENABLED", "").strip().lower()
        return raw in {"1", "true", "yes", "on"}
    if spec.credential_env and spec.config_env:
        return bool(os.getenv(spec.credential_env, "").strip()) and bool(os.getenv(spec.config_env, "").strip())
    if spec.credential_env:
        return bool(os.getenv(spec.credential_env, "").strip())
    if spec.config_env:
        return bool(os.getenv(spec.config_env, "").strip())
    return spec.enabled_by_default


def source_runtime_state(source_id: str) -> dict[str, Any]:
    spec = SOURCE_REGISTRY[source_id]
    blocked = spec.commercial_status in _BLOCKED_COMMERCIAL_STATUSES
    credential_present = bool(spec.credential_env and os.getenv(spec.credential_env, "").strip())
    config_present = bool(spec.config_env and os.getenv(spec.config_env, "").strip())
    configured = _configured_value(spec)
    enabled = spec.enabled_by_default or configured
    if blocked:
        state = "RESTRICTED"
        enabled = False
    elif spec.credential_env and spec.config_env:
        if credential_present and config_present:
            state = "READY"
            enabled = True
        elif not credential_present:
            state = "PENDING_CREDENTIAL"
            enabled = False
        else:
            state = "PENDING_CONFIGURATION"
            enabled = False
    elif enabled and configured:
        state = "READY"
    elif enabled and not spec.credential_env and not spec.config_env:
        state = "READY"
    elif spec.credential_env:
        state = "PENDING_CREDENTIAL"
    elif spec.config_env:
        state = "PENDING_CONFIGURATION"
    else:
        state = "DISABLED"
    row = asdict(spec)
    # Never reveal actual secret/config values.
    row.update({
        "runtime_state": state,
        "configured": configured,
        "enabled": enabled,
        "credential_present": credential_present,
        "config_present": config_present,
    })
    return row

def registry_snapshot() -> dict[str, Any]:
    rows = [source_runtime_state(source_id) for source_id in SOURCE_REGISTRY]
    return {
        "engine_version": ENGINE_VERSION,
        "sources": rows,
        "ready_source_ids": [x["source_id"] for x in rows if x["runtime_state"] == "READY"],
        "restricted_source_ids": [x["source_id"] for x in rows if x["runtime_state"] == "RESTRICTED"],
        "security_boundary": (
            "PUBLIC_OR_OFFICIAL_OR_EXPLICITLY_AUTHORIZED_ONLY;_NO_BROWSER_COOKIES,_PASSWORDS,_VPN_CREDENTIALS,_"
            "SESSION_REUSE,_CAPTCHA_BYPASS,_ANTI_BOT_BYPASS,_OR_FRONTEND_SECRET_EXPOSURE"
        ),
    }


def ready_source_ids(*, include_default_legacy: bool = True) -> list[str]:
    ready: list[str] = []
    for source_id, spec in SOURCE_REGISTRY.items():
        state = source_runtime_state(source_id)
        if state["runtime_state"] != "READY":
            continue
        if not include_default_legacy and spec.enabled_by_default:
            continue
        ready.append(source_id)
    return ready


def observation_families_for_source(source_id: str) -> list[str]:
    spec = SOURCE_REGISTRY.get(source_id)
    if not spec:
        return []
    families = list(spec.observation_families)
    configs: list[dict[str, Any]] = []
    if source_id == "DISCOURSE_PUBLIC":
        configs = discourse_site_configs()
    elif source_id == "MASTODON_SEARCH":
        configs = mastodon_instance_configs()
    elif source_id == "LEMMY_PUBLIC":
        configs = lemmy_instance_configs()
    elif source_id == "STACK_EXCHANGE_NETWORK":
        configs = stackexchange_site_configs()
    for cfg in configs:
        families.extend(str(x).upper() for x in (cfg.get("observation_families") or []) if str(x).strip())
    return list(dict.fromkeys(families))


def configured_list(env_name: str) -> list[str]:
    return _split_csv(os.getenv(env_name, ""))


def discourse_site_configs() -> list[dict[str, Any]]:
    """Parse explicitly configured public Discourse sites.

    SIGNALFORGE_DISCOURSE_SITES=https://forum.example.com,https://community.example.org
    SIGNALFORGE_DISCOURSE_SITES_JSON='[{"base_url":"https://forum.example.com","observation_families":["AGENCY_COMMUNITIES"]}]'
    """
    rows: list[dict[str, Any]] = []
    raw_json = os.getenv("SIGNALFORGE_DISCOURSE_SITES_JSON", "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, Mapping):
                    continue
                base = str(item.get("base_url") or item.get("url") or "").strip().rstrip("/")
                if not base:
                    continue
                fam = [str(x).upper() for x in (item.get("observation_families") or []) if str(x).strip()]
                rows.append({"base_url": base, "observation_families": fam})
    for base in _split_csv(os.getenv("SIGNALFORGE_DISCOURSE_SITES", "")):
        base = base.rstrip("/")
        if base and not any(x.get("base_url") == base for x in rows):
            rows.append({"base_url": base, "observation_families": ["DOMAIN_FORUMS"]})
    return rows[:20]



def _public_instance_configs(*, csv_env: str, json_env: str, default_families: list[str], max_items: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_json = os.getenv(json_env, "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, Mapping):
                    continue
                base = str(item.get("base_url") or item.get("url") or item.get("instance") or "").strip().rstrip("/")
                if not base:
                    continue
                fam = [str(x).upper() for x in (item.get("observation_families") or default_families) if str(x).strip()]
                row = {"base_url": base, "observation_families": fam}
                tags = [str(x).lstrip("#").strip() for x in (item.get("hashtags") or []) if str(x).strip()]
                if tags:
                    row["hashtags"] = tags[:8]
                rows.append(row)
    for base in _split_csv(os.getenv(csv_env, "")):
        base = base.rstrip("/")
        if base and not any(x.get("base_url") == base for x in rows):
            rows.append({"base_url": base, "observation_families": list(default_families)})
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        dedup[str(row.get("base_url") or "").lower()] = row
    return list(dedup.values())[:max_items]


def mastodon_instance_configs() -> list[dict[str, Any]]:
    return _public_instance_configs(
        csv_env="SIGNALFORGE_MASTODON_INSTANCES", json_env="SIGNALFORGE_MASTODON_INSTANCES_JSON",
        default_families=["PUBLIC_MARKET_CONVERSATIONS", "FOUNDER_COMMUNITIES"], max_items=12,
    )


def lemmy_instance_configs() -> list[dict[str, Any]]:
    return _public_instance_configs(
        csv_env="SIGNALFORGE_LEMMY_INSTANCES", json_env="SIGNALFORGE_LEMMY_INSTANCES_JSON",
        default_families=["PUBLIC_MARKET_CONVERSATIONS", "DOMAIN_FORUMS"], max_items=12,
    )


def stackexchange_site_configs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_json = os.getenv("SIGNALFORGE_STACKEXCHANGE_SITES_JSON", "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, Mapping):
                    continue
                site = str(item.get("site") or item.get("api_site_parameter") or "").strip()
                if not site or not all(ch.isalnum() or ch in "-_." for ch in site):
                    continue
                fam = [str(x).upper() for x in (item.get("observation_families") or ["DOMAIN_QA", "PROFESSIONAL_COMMUNITIES"]) if str(x).strip()]
                rows.append({"site": site, "observation_families": fam})
    for site in _split_csv(os.getenv("SIGNALFORGE_STACKEXCHANGE_SITES", "")):
        if site and all(ch.isalnum() or ch in "-_." for ch in site) and not any(x.get("site") == site for x in rows):
            rows.append({"site": site, "observation_families": ["DOMAIN_QA", "PROFESSIONAL_COMMUNITIES"]})
    dedup = {str(x["site"]).lower(): x for x in rows}
    return list(dedup.values())[:20]


def ashby_board_names() -> list[str]:
    out: list[str] = []
    for name in configured_list("SIGNALFORGE_ASHBY_BOARDS"):
        clean = name.strip().strip("/")
        if clean and all(ch.isalnum() or ch in "-_." for ch in clean):
            out.append(clean)
    return list(dict.fromkeys(out))[:50]


def github_discussion_repos() -> list[dict[str, str]]:
    """Explicit public repositories whose Discussions may be read.

    SIGNALFORGE_GITHUB_DISCUSSION_REPOS=owner/repo,owner2/repo2
    No repository discovery, private-repo inference, or browser/session reuse is performed.
    """
    rows: list[dict[str, str]] = []
    for value in configured_list("SIGNALFORGE_GITHUB_DISCUSSION_REPOS"):
        parts = [x.strip() for x in value.split("/", 1)]
        if len(parts) != 2 or not all(parts):
            continue
        owner, repo = parts
        if not all(ch.isalnum() or ch in "-_." for ch in owner + repo):
            continue
        rows.append({"owner": owner, "repo": repo})
    dedup = {(x["owner"].lower(), x["repo"].lower()): x for x in rows}
    return list(dedup.values())[:30]


def public_feed_configs() -> list[dict[str, Any]]:
    """Parse explicitly configured public feeds without ever accepting credentials in URLs.

    Accepted forms:
      SIGNALFORGE_PUBLIC_FEEDS=https://example.com/feed.xml,https://example.org/rss
      SIGNALFORGE_PUBLIC_FEEDS_JSON='[{"url":"...","observation_families":["AGENCY_COMMUNITIES"]}]'
    """
    rows: list[dict[str, Any]] = []
    for url in configured_list("SIGNALFORGE_PUBLIC_FEEDS"):
        rows.append({"url": url, "observation_families": ["BLOGS", "INDUSTRY_FEEDS"]})
    raw = os.getenv("SIGNALFORGE_PUBLIC_FEEDS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, Mapping) or not str(item.get("url") or "").strip():
                    continue
                rows.append({
                    "url": str(item.get("url") or "").strip(),
                    "observation_families": [str(x).upper() for x in (item.get("observation_families") or ["BLOGS", "INDUSTRY_FEEDS"]) if str(x).strip()],
                    "name": str(item.get("name") or "").strip() or None,
                })
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        dedup[row["url"]] = row
    return list(dedup.values())[:30]
