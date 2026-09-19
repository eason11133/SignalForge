from __future__ import annotations

import asyncio
from urllib.parse import urljoin

from sqlalchemy import select

from database.connection import async_session, SourceRegistry
from scrapers.source_adapters.base import SourceAdapter
from scrapers.source_network_common import (
    clean_text,
    compact_query,
    mark_coverage,
    observe_source,
    upsert_external_problem,
)
from scrapers.coverage_controller import (
    choose_cases_for_source,
    classify_candidate,
)

DOMAIN_TAG_HINTS = {
    "AI_DATA": {"ai", "research", "programming", "automation", "devops"},
    "TECHNICAL": {"programming", "devops", "automation", "support"},
    "SECURITY_PRIVACY": {"security", "privacy", "support"},
    "CONSUMER_PRODUCT": {"support", "smart-home", "gaming", "audio"},
    "WORKFLOW_COLLAB": {"automation", "programming", "devops", "support"},
    "CREATIVE": {"ai", "audio", "gaming"},
}


class DiscourseTargetedAdapter(SourceAdapter):
    """Candidate-targeted search across discovered public Discourse communities.

    This is intentionally conservative:
    - only communities already discovered by the existing Discover/feed network;
    - at most a few communities per case;
    - public /search.json only;
    - rate limits/errors are recorded as coverage failures, not negative evidence.
    """

    adapter_name = "discourse_targeted"

    async def run(self, client, cases):
        if not cases:
            return self.stats

        batch = await choose_cases_for_source(
            cases,
            "discourse",
            limit=min(3, len(cases)),
            min_relevance=2,
        )
        if not batch:
            return self.stats

        communities = await self._communities(limit=60)
        if not communities:
            return self.stats

        for case, candidate in batch:
            query = compact_query(candidate)
            if not query:
                continue

            picked = self._pick_communities(candidate, communities, limit=3)
            if not picked:
                continue

            total_hits = 0
            direct_hits = 0
            completed = 0
            errors = []
            rate_limited = False

            for community in picked:
                result = await self._search_community(
                    client,
                    community,
                    candidate.id,
                    query,
                )
                total_hits += result["hits"]
                direct_hits += result["direct"]
                completed += int(result["completed"])
                if result["rate_limited"]:
                    rate_limited = True
                if result["error"]:
                    errors.append(result["error"])
                await asyncio.sleep(0.6)

            if completed > 0:
                status = "SUCCESS_HITS" if total_hits > 0 else "SUCCESS_ZERO"
            elif rate_limited:
                status = "RATE_LIMITED"
            else:
                status = "ERROR"

            await mark_coverage(
                case_id=case.id,
                source_type="discourse",
                query=query,
                hits_seen=total_hits,
                direct_problem_hits=direct_hits,
                status=status,
                error=" | ".join(errors)[:1500] if errors else None,
                metadata={
                    "communities_queried": [c.source_key for c in picked],
                    "completed_communities": completed,
                    "adapter": self.adapter_name,
                },
            )

            self.stats["queries"] += 1
            self.stats["items"] += total_hits
            self.stats["direct_problem_hits"] += direct_hits
            self.stats["communities_queried"] += len(picked)

        return self.stats

    async def _communities(self, limit=60):
        async with async_session() as session:
            return list((await session.execute(
                select(SourceRegistry)
                .where(
                    SourceRegistry.source_type == "discourse_community",
                    SourceRegistry.status.in_(["ACTIVE", "WATCH"]),
                )
                .order_by(
                    SourceRegistry.direct_problem_hits.desc(),
                    SourceRegistry.yield_score.desc(),
                    SourceRegistry.last_success_at.desc().nullslast(),
                )
                .limit(limit)
            )).scalars().all())

    def _pick_communities(self, candidate, communities, limit=3):
        domains = classify_candidate(candidate)
        wanted = set()
        for domain in domains:
            wanted |= DOMAIN_TAG_HINTS.get(domain, set())

        ranked = []
        for row in communities:
            meta = dict(row.source_metadata or {})
            tag = str(meta.get("last_discover_tag") or "").lower()
            tag_match = 1 if tag and tag in wanted else 0
            ranked.append((
                -tag_match,
                -int(row.direct_problem_hits or 0),
                -float(row.yield_score or 0.0),
                str(row.source_key),
                row,
            ))
        ranked.sort(key=lambda x: x[:4])
        return [x[-1] for x in ranked[:limit]]

    async def _search_community(self, client, community, candidate_id, query):
        base = str(community.source_url or community.source_key or "").rstrip("/")
        if not base.startswith("http"):
            return {
                "hits": 0, "direct": 0, "completed": False,
                "rate_limited": False, "error": "invalid_community_url",
            }

        try:
            response = await client.get(
                f"{base}/search.json",
                params={"q": query},
                headers={"User-Agent": "community-mind-mirror/1.0"},
                timeout=20.0,
            )
            if response.status_code == 429:
                return {
                    "hits": 0, "direct": 0, "completed": False,
                    "rate_limited": True, "error": "HTTP 429",
                }
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return {
                "hits": 0, "direct": 0, "completed": False,
                "rate_limited": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        topics = {
            int(t.get("id")): t
            for t in (data.get("topics") or [])
            if t.get("id") is not None
        }
        posts = list(data.get("posts") or [])[:50]

        direct_hits = 0
        for post in posts:
            topic_id = post.get("topic_id")
            topic = topics.get(int(topic_id)) if topic_id is not None else {}
            title = clean_text((topic or {}).get("title"))
            body = clean_text(post.get("blurb") or post.get("name") or "")
            slug = (topic or {}).get("slug")
            post_number = post.get("post_number") or 1

            if slug and topic_id:
                url = f"{base}/t/{slug}/{topic_id}/{post_number}"
            elif topic_id:
                url = f"{base}/t/{topic_id}"
            else:
                url = base

            external_id = str(
                post.get("id")
                or f"{topic_id}:{post_number}:{candidate_id}"
            )

            direct = await upsert_external_problem(
                source_type="discourse_search",
                source_key=base,
                external_id=external_id,
                title=title,
                body=body,
                url=url,
                author=post.get("username"),
                published_at=None,
                updated_at=None,
                score=None,
                matched_candidate_id=candidate_id,
                raw_metadata={
                    "discovery_query": query,
                    "community_url": base,
                    "topic_id": topic_id,
                    "post_number": post_number,
                    "adapter": self.adapter_name,
                },
            )
            direct_hits += int(direct)

        await observe_source(
            source_type="discourse_community",
            source_key=community.source_key,
            source_url=base,
            origin=community.origin,
            evidence_role="DIRECT_PROBLEM",
            seen=len(posts),
            relevant=len(posts),
            direct_problem=direct_hits,
            metadata={
                "last_targeted_query": query,
                "targeted_search_adapter": self.adapter_name,
            },
        )

        return {
            "hits": len(posts),
            "direct": direct_hits,
            "completed": True,
            "rate_limited": False,
            "error": None,
        }
