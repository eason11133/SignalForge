from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select

from database.connection import async_session, SourceCheckpoint
from scrapers.source_adapters.base import SourceAdapter
from scrapers.source_network_common import (
    clean_text,
    observe_source,
    parse_datetime,
    stable_external_id,
    upsert_external_problem,
)

DISCOVER = "https://discover.discourse.com"


class DiscourseDiscoverAdapter(SourceAdapter):
    adapter_name = "discourse_discover"

    async def run(self, client, cases):
        try:
            response = await client.get(
                f"{DISCOVER}/hot-topics-tags.json",
                headers={"User-Agent": "community-mind-mirror/1.0"},
            )
            response.raise_for_status()
            tags = list(response.json().get("tags") or [])
        except Exception as exc:
            self.stats["tag_errors"] += 1
            return self.stats

        if not tags:
            return self.stats

        cursor = await self._get_cursor("source_network:discourse:tag_cursor")
        batch_size = min(5, len(tags))
        batch = [tags[(cursor + i) % len(tags)] for i in range(batch_size)]

        for tag in batch:
            await self._fetch_tag(client, str(tag))

        await self._set_cursor(
            "source_network:discourse:tag_cursor",
            (cursor + batch_size) % len(tags),
        )
        self.stats["tags_available"] = len(tags)
        return self.stats

    async def _fetch_tag(self, client, tag):
        try:
            response = await client.get(
                f"{DISCOVER}/hot-topics.json",
                params={"tag": tag, "page": 0},
                headers={"User-Agent": "community-mind-mirror/1.0"},
            )
            response.raise_for_status()
            topics = list(response.json().get("hot_topics") or [])
        except Exception:
            self.stats["topic_errors"] += 1
            return

        direct_hits = 0
        communities = set()
        for item in topics:
            community_url = str(item.get("community_url") or "").rstrip("/")
            topic_url = item.get("url")
            if not community_url and topic_url:
                try:
                    p = urlsplit(topic_url)
                    community_url = f"{p.scheme}://{p.netloc}"
                except Exception:
                    community_url = ""

            title = clean_text(item.get("title"))
            body = clean_text(item.get("excerpt"))
            external_id = stable_external_id(
                community_url,
                item.get("id"),
                topic_url,
            )
            direct = await upsert_external_problem(
                source_type="discourse_hot_topic",
                source_key=community_url or f"discover-tag:{tag}",
                external_id=external_id,
                title=title,
                body=body,
                url=topic_url,
                author=None,
                published_at=parse_datetime(item.get("remote_created_at")),
                updated_at=parse_datetime(item.get("remote_created_at")),
                score=float(item.get("score") or 0),
                matched_candidate_id=None,
                raw_metadata={
                    "discover_tag": tag,
                    "community_name": item.get("community_name"),
                    "community_url": community_url,
                    "like_count": item.get("like_count"),
                    "reply_count": item.get("reply_count"),
                    "views": item.get("views"),
                    "adapter": self.adapter_name,
                },
            )
            direct_hits += int(direct)

            if community_url:
                communities.add(community_url)
                await observe_source(
                    source_type="discourse_community",
                    source_key=community_url,
                    source_url=community_url,
                    origin="discovered",
                    evidence_role="DIRECT_PROBLEM",
                    seen=1,
                    relevant=1,
                    direct_problem=int(direct),
                    metadata={
                        "community_name": item.get("community_name"),
                        "last_discover_tag": tag,
                        "discovered_by": "discourse_discover_hot_topics",
                    },
                )

        self.stats["tags_scanned"] += 1
        self.stats["items"] += len(topics)
        self.stats["direct_problem_hits"] += direct_hits
        self.stats["communities_seen"] += len(communities)

    async def _get_cursor(self, key):
        async with async_session() as session:
            row = (await session.execute(
                select(SourceCheckpoint).where(SourceCheckpoint.checkpoint_key == key)
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
                meta_col: {"adapter": self.adapter_name},
            }).on_conflict_do_update(
                index_elements=[table.c.checkpoint_key],
                set_={
                    table.c.cursor: cursor,
                    meta_col: {"adapter": self.adapter_name},
                    table.c.updated_at: _utc_naive(),
                },
            )
            await session.execute(stmt)
            await session.commit()
