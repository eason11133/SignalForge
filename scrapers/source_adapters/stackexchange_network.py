from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from database.connection import async_session, SourceCheckpoint, SourceRegistry
from scrapers.source_adapters.base import SourceAdapter
from scrapers.source_network_common import (
    clean_text,
    compact_query,
    mark_coverage,
    observe_source,
    upsert_external_problem,
)
from scrapers.coverage_controller import choose_cases_for_source

STACK_API = "https://api.stackexchange.com/2.3"
SO_API_KEY = os.getenv("SO_API_KEY")

BASELINE_SITES = [
    "superuser", "serverfault", "askubuntu", "softwareengineering",
    "datascience", "ai", "stats", "security", "unix", "webapps",
]


class StackExchangeNetworkAdapter(SourceAdapter):
    adapter_name = "stackexchange_network"

    async def run(self, client, cases):
        await self._discover_sites(client)
        all_sites = await self._choose_sites(limit=40)
        if not all_sites or not cases:
            return self.stats

        # Sites still rotate, but cases no longer use a blind cursor. Each site
        # receives the highest-relevance cases that lack auditable coverage.
        site_cursor = await self._get_cursor("source_network:se:site_cursor")
        site_batch_size = min(6, len(all_sites))
        sites = [
            all_sites[(site_cursor + i) % len(all_sites)]
            for i in range(site_batch_size)
        ]

        for site in sites:
            source_type = f"stackexchange:{site.source_key}"
            batch = await choose_cases_for_source(
                cases,
                source_type,
                limit=min(4, len(cases)),
                min_relevance=2,
            )
            self.stats["controller_cases_selected"] += len(batch)

            for case, candidate in batch:
                query = compact_query(candidate)
                if not query:
                    continue
                await self._search_site(
                    client,
                    site,
                    case.id,
                    candidate.id,
                    query,
                )
                await asyncio.sleep(0.25)

        await self._set_cursor(
            "source_network:se:site_cursor",
            (site_cursor + site_batch_size) % len(all_sites),
        )
        return self.stats

    async def _discover_sites(self, client):
        params = {"pagesize": 500}
        if SO_API_KEY:
            params["key"] = SO_API_KEY
        try:
            response = await client.get(f"{STACK_API}/sites", params=params)
            response.raise_for_status()
            data = response.json()
        except Exception:
            self.stats["site_discovery_errors"] += 1
            return

        for item in data.get("items", []):
            if item.get("site_type") != "main_site":
                continue
            key = item.get("api_site_parameter")
            if not key:
                continue
            status = "ACTIVE" if key in BASELINE_SITES else "WATCH"
            await observe_source(
                source_type="stackexchange_site",
                source_key=key,
                source_url=item.get("site_url"),
                origin="seed" if key in BASELINE_SITES else "discovered",
                evidence_role="DIRECT_PROBLEM",
                metadata={
                    "name": item.get("name"),
                    "audience": item.get("audience"),
                    "site_state": item.get("site_state"),
                },
                status_hint=status,
            )
            self.stats["sites_discovered"] += 1

    async def _choose_sites(self, limit):
        async with async_session() as session:
            active = list((await session.execute(
                select(SourceRegistry)
                .where(
                    SourceRegistry.source_type == "stackexchange_site",
                    SourceRegistry.status == "ACTIVE",
                )
                .order_by(
                    SourceRegistry.yield_score.desc(),
                    SourceRegistry.source_key,
                )
                .limit(limit)
            )).scalars().all())
        return active

    async def _search_site(self, client, site, case_id, candidate_id, query):
        terms = [t for t in query.split() if t]
        pair_query = " ".join(terms[:2]) if len(terms) >= 2 else query
        primary_term = terms[0] if terms else query
        source_type = f"stackexchange:{site.source_key}"

        params = {
            "site": site.source_key,
            "q": pair_query,
            "sort": "relevance",
            "order": "desc",
            "pagesize": 50,
            "filter": "withbody",
            "fromdate": int(
                (datetime.now(timezone.utc) - timedelta(days=730)).timestamp()
            ),
        }
        if SO_API_KEY:
            params["key"] = SO_API_KEY

        try:
            response = await client.get(
                f"{STACK_API}/search/advanced",
                params=params,
            )
            if response.status_code == 429:
                await mark_coverage(
                    case_id=case_id,
                    source_type=source_type,
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429",
                )
                self.stats["rate_limited"] += 1
                return

            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])

            if not items and primary_term:
                fallback = {
                    "site": site.source_key,
                    "intitle": primary_term,
                    "sort": "relevance",
                    "order": "desc",
                    "pagesize": 50,
                    "filter": "withbody",
                }
                if SO_API_KEY:
                    fallback["key"] = SO_API_KEY

                response2 = await client.get(
                    f"{STACK_API}/search",
                    params=fallback,
                )
                if response2.status_code == 429:
                    await mark_coverage(
                        case_id=case_id,
                        source_type=source_type,
                        query=query,
                        hits_seen=0,
                        direct_problem_hits=0,
                        status="RATE_LIMITED",
                        error="HTTP 429 on fallback",
                    )
                    self.stats["rate_limited"] += 1
                    return

                response2.raise_for_status()
                data2 = response2.json()
                items = data2.get("items", [])
                self.stats["fallback_queries"] += 1
                if data2.get("backoff"):
                    await asyncio.sleep(min(int(data2["backoff"]), 120))

        except Exception as exc:
            await mark_coverage(
                case_id=case_id,
                source_type=source_type,
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(exc),
            )
            self.stats["search_errors"] += 1
            return

        direct_hits = 0
        for item in items:
            title = clean_text(item.get("title"))
            body = clean_text(item.get("body"))
            direct = await upsert_external_problem(
                source_type="stackexchange",
                source_key=site.source_key,
                external_id=str(item.get("question_id")),
                title=title,
                body=body,
                url=item.get("link"),
                author=(item.get("owner") or {}).get("display_name"),
                published_at=(
                    datetime.fromtimestamp(
                        item["creation_date"],
                        tz=timezone.utc,
                    ).replace(tzinfo=None)
                    if item.get("creation_date")
                    else None
                ),
                updated_at=(
                    datetime.fromtimestamp(
                        item["last_activity_date"],
                        tz=timezone.utc,
                    ).replace(tzinfo=None)
                    if item.get("last_activity_date")
                    else None
                ),
                score=float(item.get("score") or 0),
                matched_candidate_id=candidate_id,
                raw_metadata={
                    "tags": item.get("tags"),
                    "view_count": item.get("view_count"),
                    "answer_count": item.get("answer_count"),
                    "discovery_query": query,
                    "coverage_truth_version": "v4.4a",
                },
            )
            direct_hits += int(direct)

        await observe_source(
            source_type="stackexchange_site",
            source_key=site.source_key,
            source_url=site.source_url,
            origin=site.origin,
            seen=len(items),
            relevant=len(items),
            direct_problem=direct_hits,
            metadata={"last_query": query},
        )
        await mark_coverage(
            case_id=case_id,
            source_type=source_type,
            query=query,
            hits_seen=len(items),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if items else "SUCCESS_ZERO",
            metadata={
                "quota_remaining": data.get("quota_remaining"),
                "adapter": self.adapter_name,
            },
        )

        self.stats["queries"] += 1
        self.stats["items"] += len(items)
        self.stats["direct_problem_hits"] += direct_hits

        if data.get("backoff"):
            await asyncio.sleep(min(int(data["backoff"]), 120))

    async def _get_cursor(self, key):
        async with async_session() as session:
            row = (await session.execute(
                select(SourceCheckpoint).where(
                    SourceCheckpoint.checkpoint_key == key
                )
            )).scalar_one_or_none()
            return int(row.cursor or 0) if row else 0

    async def _set_cursor(self, key, cursor):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from scrapers.base_scraper import _utc_naive

        table = SourceCheckpoint.__table__
        meta_col = table.c["metadata"]

        async with async_session() as session:
            stmt = pg_insert(table).values({
                table.c.checkpoint_key: key,
                table.c.cursor: cursor,
                meta_col: {
                    "adapter": self.adapter_name,
                    "coverage_controller": "v4.4a",
                },
            }).on_conflict_do_update(
                index_elements=[table.c.checkpoint_key],
                set_={
                    table.c.cursor: cursor,
                    meta_col: {
                        "adapter": self.adapter_name,
                        "coverage_controller": "v4.4a",
                    },
                    table.c.updated_at: _utc_naive(),
                },
            )
            await session.execute(stmt)
            await session.commit()
