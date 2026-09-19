from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urljoin, urlsplit

import feedparser
from html.parser import HTMLParser
from sqlalchemy import select

from database.connection import (
    async_session,
    GithubIssue,
    Post,
    SOQuestion,
    SourceCheckpoint,
    ExternalProblemItem,
    SourceRegistry,
)
from scrapers.source_adapters.base import SourceAdapter
from scrapers.source_network_common import (
    USER_AGENT,
    clean_text,
    extract_domains,
    observe_source,
    parse_datetime,
    robots_allows,
    stable_external_id,
    upsert_external_problem,
)



class FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        data = {str(k).lower(): v for k, v in attrs}
        rel = str(data.get("rel") or "").lower()
        typ = str(data.get("type") or "").lower()
        href = data.get("href")
        if href and "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
            self.links.append(href)


COMMON_FEEDS = [
    "/latest.rss?order=created",  # Discourse public chronological topics
    "/posts.rss",                 # Discourse public posts
    "/feed",
    "/feed.xml",
    "/rss",
    "/rss.xml",
    "/atom.xml",
]


class FeedNetworkAdapter(SourceAdapter):
    adapter_name = "feed_network"

    async def run(self, client, cases):
        domains = await self._discover_domains(limit=80)
        seed_env = os.getenv("SOURCE_NETWORK_SEED_DOMAINS", "")
        for raw in seed_env.split(","):
            host = raw.strip().lower().replace("https://", "").replace("http://", "").strip("/")
            if host and host not in domains:
                domains.append(host)

        if not domains:
            return self.stats

        cursor = await self._get_cursor("source_network:feed:domain_cursor")
        batch_size = min(8, len(domains))
        batch = [domains[(cursor + i) % len(domains)] for i in range(batch_size)]

        for domain in batch:
            await self._probe_domain(client, domain)

        await self._set_cursor(
            "source_network:feed:domain_cursor",
            (cursor + batch_size) % len(domains),
        )
        return self.stats

    async def _discover_domains(self, limit=80):
        domains, seen = [], set()

        def add_text(text):
            for domain in extract_domains(text or ""):
                if domain in seen:
                    continue
                seen.add(domain)
                domains.append(domain)

        async with async_session() as session:
            # First-class discovered communities are higher-value than random
            # outbound domains embedded in posts. Probe them first.
            community_rows = list((await session.execute(
                select(SourceRegistry)
                .where(SourceRegistry.source_type == "discourse_community")
                .order_by(
                    SourceRegistry.direct_problem_hits.desc(),
                    SourceRegistry.last_seen_at.desc().nullslast(),
                )
                .limit(limit)
            )).scalars().all())
            for row in community_rows:
                add_text(row.source_url)
                if len(domains) >= limit:
                    return domains

            posts = list((await session.execute(
                select(Post.body).order_by(Post.id.desc()).limit(1200)
            )).scalars().all())
            for body in posts:
                add_text(body)
                if len(domains) >= limit:
                    return domains

            so_rows = list((await session.execute(
                select(SOQuestion.raw_metadata).order_by(SOQuestion.id.desc()).limit(800)
            )).scalars().all())
            for meta in so_rows:
                if isinstance(meta, dict):
                    add_text(meta.get("body"))
                if len(domains) >= limit:
                    return domains

            gh_rows = list((await session.execute(
                select(GithubIssue.body).order_by(GithubIssue.id.desc()).limit(800)
            )).scalars().all())
            for body in gh_rows:
                add_text(body)
                if len(domains) >= limit:
                    return domains

            ext_rows = list((await session.execute(
                select(ExternalProblemItem.body)
                .order_by(ExternalProblemItem.id.desc())
                .limit(800)
            )).scalars().all())
            for body in ext_rows:
                add_text(body)
                if len(domains) >= limit:
                    return domains

        return domains

    async def _probe_domain(self, client, domain):
        base = f"https://{domain}"
        feed_urls = []

        # Discover declared RSS/Atom feeds from the public homepage first.
        try:
            if await robots_allows(client, base, base + "/"):
                response = await client.get(
                    base + "/",
                    headers={"User-Agent": USER_AGENT},
                    timeout=15.0,
                )
                if response.status_code < 400 and "text/html" in response.headers.get("content-type", ""):
                    parser = FeedLinkParser()
                    parser.feed(response.text[:600000])
                    for href in parser.links:
                        feed_urls.append(urljoin(base + "/", href))
        except Exception:
            pass

        for path in COMMON_FEEDS:
            feed_urls.append(base + path)

        unique = []
        seen = set()
        for url in feed_urls:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)

        for feed_url in unique[:5]:
            ok = await self._try_feed(client, domain, feed_url)
            if ok:
                return
        self.stats["domains_without_feed"] += 1

    async def _try_feed(self, client, domain, feed_url):
        base = f"https://{domain}"
        if not await robots_allows(client, base, feed_url):
            self.stats["robots_denied"] += 1
            return False

        try:
            response = await client.get(
                feed_url,
                headers={"User-Agent": USER_AGENT},
                timeout=20.0,
            )
            if response.status_code == 429:
                self.stats["rate_limited"] += 1
                return False
            if response.status_code >= 400:
                return False
            parsed = feedparser.parse(response.content)
        except Exception:
            return False

        entries = parsed.entries or []
        if not entries:
            return False

        generator = clean_text(
            getattr(parsed.feed, "generator", "")
            or getattr(parsed.feed, "generator_detail", "")
        ).lower()
        is_discourse = (
            "discourse" in generator
            or "/latest.rss" in feed_url
            or "/posts.rss" in feed_url
        )
        source_type = "discourse_feed" if is_discourse else "generic_feed"
        direct_hits = 0

        for entry in entries[:100]:
            title = clean_text(entry.get("title"))
            body = clean_text(
                entry.get("summary", "")
                or (entry.get("content") or [{}])[0].get("value", "")
            )
            link = entry.get("link")
            external_id = str(
                entry.get("id")
                or link
                or stable_external_id(feed_url, title, body[:200])
            )
            author = clean_text(entry.get("author")) or None
            published = parse_datetime(
                entry.get("published") or entry.get("updated")
            )
            direct = await upsert_external_problem(
                source_type=source_type,
                source_key=feed_url,
                external_id=external_id,
                title=title,
                body=body,
                url=link,
                author=author,
                published_at=published,
                updated_at=published,
                matched_candidate_id=None,
                raw_metadata={
                    "domain": domain,
                    "feed_url": feed_url,
                    "generator": generator,
                    "adapter": self.adapter_name,
                },
            )
            direct_hits += int(direct)

        await observe_source(
            source_type=source_type,
            source_key=feed_url,
            source_url=feed_url,
            origin="discovered",
            evidence_role="DIRECT_PROBLEM" if is_discourse else "CONTEXT_DISCOVERY",
            seen=len(entries[:100]),
            relevant=direct_hits,
            direct_problem=direct_hits,
            metadata={
                "domain": domain,
                "generator": generator,
                "feed_title": clean_text(getattr(parsed.feed, "title", "")),
            },
        )
        self.stats["feeds_found"] += 1
        self.stats["items"] += len(entries[:100])
        self.stats["direct_problem_hits"] += direct_hits
        if is_discourse:
            self.stats["discourse_feeds"] += 1
        return True

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
