"""Adaptive Multi-site Source Network v2.2 / RADAR V4.4a coverage controller.

The network now separates:
1. source discovery;
2. targeted search;
3. auditable coverage truth.

No LLM calls.
"""
from __future__ import annotations

import os
from collections import Counter

import httpx
from sqlalchemy import func, select

from database.connection import (
    async_session,
    ExternalProblemItem,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarSourceCoverage,
    SourceRegistry,
)
from scrapers.base_scraper import BaseScraper
from scrapers.coverage_controller import (
    backfill_legacy_observations,
    coverage_snapshot,
)
from scrapers.source_adapters.stackexchange_network import StackExchangeNetworkAdapter
from scrapers.source_adapters.gitlab import GitLabIssuesAdapter
from scrapers.source_adapters.discourse_discover import DiscourseDiscoverAdapter
from scrapers.source_adapters.discourse_targeted import DiscourseTargetedAdapter
from scrapers.source_adapters.feed_network import FeedNetworkAdapter


class SourceNetworkScraper(BaseScraper):
    def __init__(self):
        super().__init__("source_network", request_delay=1.0)
        self.stats = Counter()

    async def scrape(self, **kwargs):
        cases = await self._open_cases()
        if not cases:
            self.log.info("source_network_no_open_cases")
            return

        # Preserve what old collectors can prove, without pretending a legacy
        # matched row proves a complete search.
        legacy = await backfill_legacy_observations()
        for key, value in legacy.items():
            self.stats[f"coverage_truth_{key}"] += value

        adapters = [
            StackExchangeNetworkAdapter(),
            GitLabIssuesAdapter(),
            DiscourseDiscoverAdapter(),
            DiscourseTargetedAdapter(),
            FeedNetworkAdapter(),
        ]

        before = await coverage_snapshot(cases)
        self.log.info(
            "source_network_start",
            version="v2.2-v4.4a-coverage-controller",
            cases=len(cases),
            adapters=[a.adapter_name for a in adapters],
            coverage_before=dict(before["levels"]),
            gitlab_mode="authenticated" if os.getenv("GITLAB_TOKEN") else "public",
            stackexchange_mode="keyed" if os.getenv("SO_API_KEY") else "anonymous",
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(35.0),
            follow_redirects=True,
        ) as client:
            for adapter in adapters:
                try:
                    stats = await adapter.run(client, cases)
                    for key, value in stats.items():
                        self.stats[f"{adapter.adapter_name}_{key}"] += value
                    self.records_fetched += int(stats.get("items", 0) or 0)
                except Exception as exc:
                    self.log.error(
                        "source_adapter_failed",
                        adapter=adapter.adapter_name,
                        error=str(exc),
                    )
                    self.stats[f"{adapter.adapter_name}_errors"] += 1

        after = await coverage_snapshot(cases)
        await self._print_health(cases, after)
        self.log.info(
            "source_network_complete",
            coverage_after=dict(after["levels"]),
            **dict(self.stats),
        )

    async def _open_cases(self):
        async with async_session() as session:
            return list((await session.execute(
                select(RadarCase, ProblemCandidate)
                .join(
                    ProblemCandidate,
                    ProblemCandidate.id == RadarCase.candidate_id,
                )
                .join(
                    RadarClaim,
                    (RadarClaim.case_id == RadarCase.id)
                    & (RadarClaim.claim_code == "C02"),
                )
                .where(
                    RadarClaim.state.in_(
                        ["UNKNOWN", "INSUFFICIENT", "CONFLICTED"]
                    )
                )
                .order_by(RadarCase.id)
            )).all())

    async def _print_health(self, cases, snapshot):
        async with async_session() as session:
            external_total = (await session.execute(
                select(func.count(ExternalProblemItem.id))
            )).scalar_one()
            external_direct = (await session.execute(
                select(func.count(ExternalProblemItem.id)).where(
                    ExternalProblemItem.is_direct_problem.is_(True)
                )
            )).scalar_one()
            source_total = (await session.execute(
                select(func.count(SourceRegistry.id))
            )).scalar_one()
            source_active = (await session.execute(
                select(func.count(SourceRegistry.id)).where(
                    SourceRegistry.status == "ACTIVE"
                )
            )).scalar_one()
            coverage_rows = list((await session.execute(
                select(
                    RadarSourceCoverage.source_type,
                    func.count(func.distinct(RadarSourceCoverage.case_id)),
                    func.sum(RadarSourceCoverage.attempt_count),
                    func.sum(RadarSourceCoverage.successful_attempts),
                    func.sum(RadarSourceCoverage.zero_result_attempts),
                    func.sum(RadarSourceCoverage.hits_seen),
                    func.sum(RadarSourceCoverage.direct_problem_hits),
                )
                .group_by(RadarSourceCoverage.source_type)
                .order_by(RadarSourceCoverage.source_type)
            )).all())

        levels = snapshot["levels"]

        print()
        print("=" * 116)
        print("SOURCE NETWORK V2.2 — V4.4a COVERAGE TRUTH / CONTROLLER")
        print("=" * 116)
        print(f"Open C02 cases:             {len(cases)}")
        print(f"External items:             {external_total}")
        print(f"External direct problems:   {external_direct}")
        print(f"Source registry:            {source_total}")
        print(f"ACTIVE sources:             {source_active}")
        print()
        print("Auditable case coverage:")
        print(f"  SATURATED:                {levels['SATURATED']:2d}/{len(cases)}")
        print(f"  PARTIAL:                  {levels['PARTIAL']:2d}/{len(cases)}")
        print(f"  LEGACY_ONLY:              {levels['LEGACY_ONLY']:2d}/{len(cases)}")
        print(f"  GAP:                      {levels['GAP']:2d}/{len(cases)}")

        print()
        print("Independent family coverage:")
        for family in sorted(snapshot["family_relevant"]):
            relevant = int(snapshot["family_relevant"][family] or 0)
            success = int(snapshot["family_success"][family] or 0)
            print(
                f"  {family:18s} "
                f"successful={success:2d}/{relevant:2d} relevant cases"
            )

        print()
        print("Targeted coverage ledger:")
        if not coverage_rows:
            print("  no coverage rows yet")
        for (
            source_type,
            distinct_cases,
            attempts,
            successes,
            zeroes,
            hits,
            direct_hits,
        ) in coverage_rows:
            print(
                f"  {source_type:34s} "
                f"cases={int(distinct_cases or 0):2d}/{len(cases):2d} "
                f"attempts={int(attempts or 0):3d} "
                f"ok={int(successes or 0):3d} "
                f"zero={int(zeroes or 0):3d} "
                f"hits={int(hits or 0):4d} "
                f"direct={int(direct_hits or 0):4d}"
            )

        incomplete = [
            row for row in snapshot["cases"]
            if row["level"] != "SATURATED"
        ]
        print()
        print("Next coverage gaps (first 12):")
        for row in incomplete[:12]:
            print(
                f"  [{row['level']:11s}] "
                f"{row['title'][:70]}"
            )
            print(
                "      relevant="
                + ",".join(row["relevant_families"])
                + " | done="
                + (",".join(row["successful_families"]) or "-")
                + " | next="
                + (",".join(row["missing_families"][:3]) or "-")
            )

        print()
        print("Coverage truth rules:")
        print("  SUCCESS_ZERO counts as searched coverage.")
        print("  ERROR / RATE_LIMITED do NOT count as negative evidence.")
        print("  LEGACY_HIT_OBSERVED proves only that an item was seen, not search completeness.")
        print("  Multiple Stack Exchange sites collapse to ONE independent source family.")
        print()
        print("LLM calls: 0")
        print("LLM cost: NT$0.00")
        print("=" * 116)
