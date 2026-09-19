"""RADAR V4.4a — auditable source-coverage truth + controller.

This module does NOT decide whether a problem recurs.
It answers a narrower question:

    "For this case, which relevant independent source families have actually
     received an auditable targeted search?"

Rules:
- successful targeted searches count as coverage, including zero results;
- rate limits/errors do not count as successful coverage;
- legacy matched records are preserved as observations but are NOT upgraded
  into proof that a complete search occurred;
- source relevance is deterministic and case-specific;
- multiple Stack Exchange sites collapse to one independent source family.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.connection import (
    async_session,
    ExternalProblemItem,
    GithubIssue,
    Post,
    RadarSourceCoverage,
    SOQuestion,
)

SUCCESS_STATUSES = {"COMPLETED", "SUCCESS_HITS", "SUCCESS_ZERO"}
LEGACY_STATUS = "LEGACY_HIT_OBSERVED"

# Broad deterministic case domains. They only route searches; they never
# promote evidence or influence opportunity verdicts.
DOMAIN_PATTERNS = {
    "TECHNICAL": [
        r"\bapi\b", r"\bcode\b", r"\bcoding\b", r"\bdebug", r"\bruntime\b",
        r"\bserver\b", r"\bdeploy", r"\bsetup\b", r"\binstall", r"\bconfig",
        r"\bbuild\b", r"\bframework\b", r"\bintegration\b", r"\bgpu\b",
        r"\bvram\b", r"\btest", r"\bbug\b", r"\bsoftware\b", r"\btool\b",
        r"\blibrary\b", r"\bpackage\b", r"\bheadscale\b", r"\btailscale\b",
        r"\bsalesforce\b", r"\bgyp\b", r"\bcheckpoint", r"\bworkflow\b",
    ],
    "AI_DATA": [
        r"\bai\b", r"\bllm\b", r"\bmodel\b", r"\bmodels\b", r"\bprompt\b",
        r"\bagent\b", r"\binference\b", r"\bmultimodal", r"\bembedding",
        r"\bbenchmark\b", r"\bevaluation\b", r"\boutput\b", r"\bwatermark",
        r"\bcerebras\b", r"\bglm\b", r"\bdgx\b", r"\bllama\.?cpp\b",
    ],
    "SECURITY_PRIVACY": [
        r"\bsecurity\b", r"\bprivacy\b", r"\bpersonal data\b",
        r"\bthird[- ]party analytics\b", r"\btracking\b", r"\bpermission\b",
        r"\bauth", r"\baccess\b", r"\bcredential", r"\bsign[- ]?up\b",
    ],
    "CONSUMER_PRODUCT": [
        r"\banti[- ]consumer\b", r"\bonboarding\b", r"\bsign[- ]?up\b",
        r"\bproduct design\b", r"\busability\b", r"\bsubscription\b",
        r"\bsupport\b", r"\buser behavior\b", r"\bconsumer\b",
        r"\bworkaround\b", r"\binterface\b", r"\bexperience\b",
    ],
    "WORKFLOW_COLLAB": [
        r"\bworkflow\b", r"\bcollaborat", r"\bcommunication\b",
        r"\bcoordination\b", r"\bengineer", r"\bteam\b", r"\bregression test",
        r"\bharness\b", r"\bprocess\b", r"\bintegration\b",
    ],
    "CREATIVE": [
        r"\bcreative\b", r"\bsong", r"\bmusic\b", r"\bwriting\b",
        r"\bimage\b", r"\bdesign\b",
    ],
}

INFRA_PATTERNS = [
    r"\bserver\b", r"\blinux\b", r"\bubuntu\b", r"\bnetwork\b",
    r"\bdeployment\b", r"\bcontainer\b", r"\bdocker\b", r"\bkernel\b",
    r"\bruntime\b", r"\bgpu\b", r"\bdriver\b", r"\bfilesystem\b",
]

# Search families that can contribute auditable C02 search coverage.
FAMILY_SOURCE_TYPES = {
    "stackexchange": [
        "stackoverflow",
        "stackexchange:ai",
        "stackexchange:datascience",
        "stackexchange:security",
        "stackexchange:softwareengineering",
        "stackexchange:serverfault",
        "stackexchange:askubuntu",
        "stackexchange:unix",
        "stackexchange:superuser",
        "stackexchange:stats",
        "stackexchange:webapps",
    ],
    "github": ["github_issues"],
    "reddit": ["reddit"],
    "gitlab": ["gitlab"],
    "discourse": ["discourse"],
}


def _case_text(candidate) -> str:
    fields = [
        "title", "problem_statement", "actor", "task", "object",
        "failure_mode", "consequence", "workaround", "buyer_context",
    ]
    return " ".join(str(getattr(candidate, f, "") or "") for f in fields).lower()


def classify_candidate(candidate) -> set[str]:
    text = _case_text(candidate)
    domains = set()
    for domain, patterns in DOMAIN_PATTERNS.items():
        if any(re.search(p, text, re.I) for p in patterns):
            domains.add(domain)
    if not domains:
        domains.add("CONSUMER_PRODUCT")
    return domains


def source_family(source_type: str) -> str:
    source = str(source_type or "").lower()
    if source == "stackoverflow" or source.startswith("stackexchange:"):
        return "stackexchange"
    if source == "github_issues":
        return "github"
    if source == "reddit":
        return "reddit"
    if source == "gitlab":
        return "gitlab"
    if source == "discourse" or source.startswith("discourse:"):
        return "discourse"
    return source


def source_relevance(candidate, source_type: str) -> int:
    """Return 0..3. A score >=2 is considered a relevant targeted source."""
    domains = classify_candidate(candidate)
    source = str(source_type or "").lower()
    text = _case_text(candidate)
    infra = any(re.search(p, text, re.I) for p in INFRA_PATTERNS)

    if source == "stackoverflow":
        if "TECHNICAL" in domains:
            return 3
        if "AI_DATA" in domains or "WORKFLOW_COLLAB" in domains:
            return 2
        return 0

    if source == "github_issues":
        if "TECHNICAL" in domains:
            return 3
        if "AI_DATA" in domains or "WORKFLOW_COLLAB" in domains:
            return 2
        return 1

    if source == "reddit":
        if domains & {"CONSUMER_PRODUCT", "SECURITY_PRIVACY", "CREATIVE", "AI_DATA"}:
            return 3
        if domains & {"TECHNICAL", "WORKFLOW_COLLAB"}:
            return 2
        return 1

    if source == "gitlab":
        if "TECHNICAL" in domains:
            return 3
        if domains & {"AI_DATA", "WORKFLOW_COLLAB"}:
            return 2
        return 0

    if source == "discourse":
        # Candidate-targeted searches run only against discovered communities.
        # It is broad enough to be useful but never gets a relevance 3 merely
        # because it is Discourse.
        return 2

    if source.startswith("stackexchange:"):
        site = source.split(":", 1)[1]
        if site == "ai":
            return 3 if "AI_DATA" in domains else 0
        if site == "datascience":
            return 3 if "AI_DATA" in domains else 0
        if site == "stats":
            return 2 if "AI_DATA" in domains else 0
        if site == "security":
            return 3 if "SECURITY_PRIVACY" in domains else 0
        if site == "softwareengineering":
            return 3 if domains & {"TECHNICAL", "WORKFLOW_COLLAB"} else 0
        if site in {"serverfault", "askubuntu", "unix"}:
            return 3 if "TECHNICAL" in domains and infra else 0
        if site == "superuser":
            return 2 if "TECHNICAL" in domains else 0
        if site == "webapps":
            return 2 if domains & {"CONSUMER_PRODUCT", "WORKFLOW_COLLAB"} else 0
        return 1 if "TECHNICAL" in domains else 0

    return 0


def relevant_families(candidate) -> set[str]:
    families = set()
    for family, sources in FAMILY_SOURCE_TYPES.items():
        if any(source_relevance(candidate, source) >= 2 for source in sources):
            families.add(family)
    return families


def coverage_state(row) -> str:
    if row is None:
        return "NOT_SEARCHED"
    status = str(row.last_status or "").upper()
    if status in SUCCESS_STATUSES and int(row.successful_attempts or 0) > 0:
        return "SUCCESS"
    if status == LEGACY_STATUS and int(row.successful_attempts or 0) == 0:
        return "LEGACY_OBSERVATION_ONLY"
    if status == "RATE_LIMITED":
        return "RATE_LIMITED"
    if status == "ERROR":
        return "ERROR"
    if int(row.successful_attempts or 0) > 0:
        return "SUCCESS"
    return "NOT_SEARCHED"


async def choose_cases_for_source(
    cases: Iterable,
    source_type: str,
    limit: int,
    *,
    min_relevance: int = 2,
    retry_after_hours: int = 8,
):
    """Pick the highest-value cases that still lack successful coverage.

    Priority:
      NOT_SEARCHED / legacy-only -> retryable error/rate-limit -> stale success.

    Successful coverage is not repeated while any relevant case remains
    uncovered.
    """
    cases = list(cases)
    if not cases or limit <= 0:
        return []

    case_ids = [case.id for case, _ in cases]
    async with async_session() as session:
        rows = list((await session.execute(
            select(RadarSourceCoverage).where(
                RadarSourceCoverage.case_id.in_(case_ids),
                RadarSourceCoverage.source_type == source_type,
            )
        )).scalars().all())

    by_case = {row.case_id: row for row in rows}
    now = datetime.utcnow()
    ranked = []

    for case, candidate in cases:
        relevance = source_relevance(candidate, source_type)
        if relevance < min_relevance:
            continue

        row = by_case.get(case.id)
        state = coverage_state(row)
        last = getattr(row, "last_attempt_at", None) if row else None
        age_hours = 10**9 if last is None else max(
            0.0, (now - last).total_seconds() / 3600.0
        )

        if state in {"NOT_SEARCHED", "LEGACY_OBSERVATION_ONLY"}:
            bucket = 0
        elif state in {"ERROR", "RATE_LIMITED"}:
            if age_hours < retry_after_hours:
                continue
            bucket = 1
        else:
            # Re-search successful coverage only after all still-uncovered
            # relevant cases are exhausted; it is intentionally low priority.
            bucket = 9

        ranked.append((
            bucket,
            -relevance,
            last or datetime.min,
            case.id,
            (case, candidate),
        ))

    ranked.sort(key=lambda x: x[:4])

    uncovered = [r for r in ranked if r[0] < 9]
    pool = uncovered if uncovered else ranked
    return [r[-1] for r in pool[:limit]]


async def _legacy_insert(case_id: int, source_type: str, count: int, metadata: dict):
    """Record legacy evidence without pretending a full search was audited."""
    if not case_id or count <= 0:
        return
    table = RadarSourceCoverage.__table__
    meta_col = table.c["metadata"]

    async with async_session() as session:
        stmt = pg_insert(table).values({
            table.c.case_id: case_id,
            table.c.source_type: source_type,
            table.c.attempt_count: 0,
            table.c.successful_attempts: 0,
            table.c.zero_result_attempts: 0,
            table.c.hits_seen: count,
            table.c.direct_problem_hits: 0,
            table.c.last_status: LEGACY_STATUS,
            table.c.last_query: None,
            table.c.last_attempt_at: None,
            table.c.last_error: None,
            meta_col: metadata,
        }).on_conflict_do_nothing(
            constraint="uq_radar_source_coverage"
        )
        await session.execute(stmt)
        await session.commit()


async def backfill_legacy_observations() -> Counter:
    """Backfill only what can be proven from stored rows.

    Important: zero-result searches cannot be reconstructed from old item
    tables, so this never infers them from cursors.
    """
    stats = Counter()

    async with async_session() as session:
        so_rows = list((await session.execute(
            select(SOQuestion.raw_metadata)
        )).scalars().all())
        gh_rows = list((await session.execute(
            select(GithubIssue.raw_metadata)
        )).scalars().all())
        reddit_rows = list((await session.execute(
            select(Post.raw_metadata).where(Post.raw_metadata.is_not(None))
        )).scalars().all())
        ext_rows = list((await session.execute(
            select(
                ExternalProblemItem.source_type,
                ExternalProblemItem.source_key,
                ExternalProblemItem.matched_candidate_id,
            ).where(ExternalProblemItem.matched_candidate_id.is_not(None))
        )).all())

    # candidate_id != case_id, so use a candidate->case map.
    from database.connection import RadarCase
    async with async_session() as session:
        case_map = dict((await session.execute(
            select(RadarCase.candidate_id, RadarCase.id)
        )).all())

    grouped = Counter()

    for meta in so_rows:
        if isinstance(meta, dict) and meta.get("matched_candidate_id"):
            cid = int(meta["matched_candidate_id"])
            if cid in case_map:
                grouped[(case_map[cid], "stackoverflow")] += 1

    for meta in gh_rows:
        if isinstance(meta, dict) and meta.get("matched_candidate_id"):
            cid = int(meta["matched_candidate_id"])
            if cid in case_map:
                grouped[(case_map[cid], "github_issues")] += 1

    for meta in reddit_rows:
        if (
            isinstance(meta, dict)
            and meta.get("source_expansion")
            and meta.get("matched_candidate_id")
        ):
            cid = int(meta["matched_candidate_id"])
            if cid in case_map:
                grouped[(case_map[cid], "reddit")] += 1

    for source_type, source_key, candidate_id in ext_rows:
        try:
            cid = int(candidate_id)
        except Exception:
            continue
        if cid not in case_map:
            continue
        if source_type == "stackexchange":
            target = f"stackexchange:{source_key}"
        elif source_type == "gitlab_issue":
            target = "gitlab"
        elif source_type == "discourse_search":
            target = "discourse"
        else:
            continue
        grouped[(case_map[cid], target)] += 1

    for (case_id, source_type), count in grouped.items():
        await _legacy_insert(
            case_id,
            source_type,
            count,
            {
                "coverage_truth": "legacy_observation_only",
                "observed_records": count,
                "note": (
                    "Stored matched rows prove that evidence was observed, "
                    "but do not prove that a complete targeted search occurred."
                ),
            },
        )
        stats["legacy_rows_seen"] += count
        stats["legacy_case_source_pairs"] += 1

    return stats


async def coverage_snapshot(cases: Iterable):
    """Return case-level auditable saturation based on relevant families."""
    cases = list(cases)
    if not cases:
        return {
            "levels": Counter(),
            "cases": [],
            "family_success": Counter(),
            "family_relevant": Counter(),
        }

    case_ids = [case.id for case, _ in cases]
    async with async_session() as session:
        rows = list((await session.execute(
            select(RadarSourceCoverage).where(
                RadarSourceCoverage.case_id.in_(case_ids)
            )
        )).scalars().all())

    rows_by_case = defaultdict(list)
    for row in rows:
        rows_by_case[row.case_id].append(row)

    levels = Counter()
    family_success = Counter()
    family_relevant = Counter()
    details = []

    for case, candidate in cases:
        planned = relevant_families(candidate)
        successful = set()
        legacy = set()
        errorish = set()

        for family in planned:
            family_relevant[family] += 1

        for row in rows_by_case.get(case.id, []):
            if source_relevance(candidate, row.source_type) < 2:
                continue
            family = source_family(row.source_type)
            if family not in planned:
                continue
            state = coverage_state(row)
            if state == "SUCCESS":
                successful.add(family)
            elif state == "LEGACY_OBSERVATION_ONLY":
                legacy.add(family)
            elif state in {"ERROR", "RATE_LIMITED"}:
                errorish.add(family)

        for family in successful:
            family_success[family] += 1

        planned_count = len(planned)
        success_count = len(successful)
        ratio = success_count / max(1, planned_count)
        required = min(3, planned_count)

        if planned_count > 0 and success_count >= required and ratio >= 0.60:
            level = "SATURATED"
        elif success_count > 0:
            level = "PARTIAL"
        elif legacy:
            level = "LEGACY_ONLY"
        else:
            level = "GAP"

        levels[level] += 1

        missing = sorted(
            planned - successful,
            key=lambda family: (
                -max(
                    source_relevance(candidate, source)
                    for source in FAMILY_SOURCE_TYPES.get(family, [family])
                ),
                family,
            ),
        )

        details.append({
            "case_id": case.id,
            "candidate_id": candidate.id,
            "title": candidate.title,
            "domains": sorted(classify_candidate(candidate)),
            "level": level,
            "relevant_families": sorted(planned),
            "successful_families": sorted(successful),
            "legacy_only_families": sorted(legacy - successful),
            "error_or_rate_limited_families": sorted(errorish - successful),
            "missing_families": missing,
            "coverage_ratio": round(ratio, 3),
        })

    details.sort(key=lambda x: (
        {"GAP": 0, "LEGACY_ONLY": 1, "PARTIAL": 2, "SATURATED": 3}[x["level"]],
        x["coverage_ratio"],
        x["title"],
    ))

    return {
        "levels": levels,
        "cases": details,
        "family_success": family_success,
        "family_relevant": family_relevant,
    }
