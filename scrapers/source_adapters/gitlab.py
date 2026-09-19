from __future__ import annotations

import asyncio
import os

from scrapers.source_adapters.base import SourceAdapter
from scrapers.coverage_controller import choose_cases_for_source
from scrapers.source_network_common import (
    clean_text,
    compact_query,
    mark_coverage,
    observe_source,
    parse_datetime,
    upsert_external_problem,
)

GITLAB_API = os.getenv("GITLAB_API_BASE", "https://gitlab.com/api/v4").rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")


class GitLabIssuesAdapter(SourceAdapter):
    adapter_name = "gitlab_issues"

    async def run(self, client, cases):
        if not cases:
            return self.stats

        batch_size = min(6 if GITLAB_TOKEN else 3, len(cases))
        batch = await choose_cases_for_source(
            cases,
            "gitlab",
            limit=batch_size,
            min_relevance=2,
        )

        headers = {"User-Agent": "community-mind-mirror/1.0"}
        if GITLAB_TOKEN:
            headers["PRIVATE-TOKEN"] = GITLAB_TOKEN

        for case, candidate in batch:
            query = compact_query(candidate)
            if not query:
                continue
            await self._search_candidate(
                client,
                headers,
                case.id,
                candidate.id,
                query,
            )
            await asyncio.sleep(0.8)

        self.stats["controller_cases_selected"] += len(batch)
        return self.stats

    async def _search_candidate(self, client, headers, case_id, candidate_id, query):
        if GITLAB_TOKEN:
            await self._global_issue_search(
                client, headers, case_id, candidate_id, query
            )
            return

        terms = [t for t in query.split() if t]
        project_term = terms[0] if terms else query
        issue_query = " ".join(terms[:2]) if len(terms) >= 2 else query

        try:
            response = await client.get(
                f"{GITLAB_API}/projects",
                params={
                    "search": project_term,
                    "simple": "true",
                    "visibility": "public",
                    "with_issues_enabled": "true",
                    "order_by": "last_activity_at",
                    "sort": "desc",
                    "per_page": 10,
                },
                headers=headers,
            )
            if response.status_code == 429:
                await mark_coverage(
                    case_id=case_id,
                    source_type="gitlab",
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429 project discovery",
                    metadata={"mode": "public_project_discovery"},
                )
                self.stats["rate_limited"] += 1
                return
            response.raise_for_status()
            projects = response.json()
        except Exception as exc:
            await mark_coverage(
                case_id=case_id,
                source_type="gitlab",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(exc),
                metadata={"mode": "public_project_discovery"},
            )
            self.stats["errors"] += 1
            return

        total_items = 0
        direct_hits = 0
        completed_projects = 0
        rate_limited = False
        errors = []

        for project in projects[:3]:
            pid = project.get("id")
            path = project.get("path_with_namespace") or str(pid)
            if not pid:
                continue

            result = await self._project_issues(
                client,
                headers,
                pid,
                path,
                candidate_id,
                issue_query,
            )
            total_items += result["items"]
            direct_hits += result["direct"]
            completed_projects += int(result["completed"])
            rate_limited = rate_limited or result["rate_limited"]
            if result["error"]:
                errors.append(result["error"])

        # A successful project-discovery request with zero matching public
        # projects is a valid SUCCESS_ZERO. If projects were found, at least
        # one issue endpoint must complete before coverage counts as success.
        if not projects:
            status = "SUCCESS_ZERO"
        elif completed_projects > 0:
            status = "SUCCESS_HITS" if total_items > 0 else "SUCCESS_ZERO"
        elif rate_limited:
            status = "RATE_LIMITED"
        else:
            status = "ERROR"

        await mark_coverage(
            case_id=case_id,
            source_type="gitlab",
            query=query,
            hits_seen=total_items,
            direct_problem_hits=direct_hits,
            status=status,
            error=" | ".join(errors)[:1500] if errors else None,
            metadata={
                "mode": "public_project_discovery",
                "projects_discovered": len(projects[:3]),
                "projects_completed": completed_projects,
            },
        )

        self.stats["queries"] += 1
        self.stats["items"] += total_items
        self.stats["direct_problem_hits"] += direct_hits

    async def _global_issue_search(self, client, headers, case_id, candidate_id, query):
        try:
            response = await client.get(
                f"{GITLAB_API}/search",
                params={"scope": "issues", "search": query, "per_page": 50},
                headers=headers,
            )
            if response.status_code == 429:
                await mark_coverage(
                    case_id=case_id,
                    source_type="gitlab",
                    query=query,
                    hits_seen=0,
                    direct_problem_hits=0,
                    status="RATE_LIMITED",
                    error="HTTP 429 global search",
                    metadata={"mode": "authenticated_global_search"},
                )
                self.stats["rate_limited"] += 1
                return
            response.raise_for_status()
            items = response.json()
        except Exception as exc:
            await mark_coverage(
                case_id=case_id,
                source_type="gitlab",
                query=query,
                hits_seen=0,
                direct_problem_hits=0,
                status="ERROR",
                error=str(exc),
                metadata={"mode": "authenticated_global_search"},
            )
            self.stats["errors"] += 1
            return

        direct_hits = 0
        for item in items:
            project_id = item.get("project_id")
            project_key = str(project_id or "global")
            title = clean_text(item.get("title"))
            body = clean_text(item.get("description"))
            direct = await upsert_external_problem(
                source_type="gitlab_issue",
                source_key=project_key,
                external_id=str(item.get("id") or item.get("iid")),
                title=title,
                body=body,
                url=item.get("web_url"),
                author=(item.get("author") or {}).get("username"),
                published_at=parse_datetime(item.get("created_at")),
                updated_at=parse_datetime(item.get("updated_at")),
                score=float(item.get("upvotes") or 0)
                - float(item.get("downvotes") or 0),
                matched_candidate_id=candidate_id,
                raw_metadata={
                    "project_id": project_id,
                    "labels": item.get("labels"),
                    "discovery_query": query,
                    "mode": "authenticated_global_search",
                    "coverage_truth_version": "v4.4a",
                },
            )
            direct_hits += int(direct)

        await mark_coverage(
            case_id=case_id,
            source_type="gitlab",
            query=query,
            hits_seen=len(items),
            direct_problem_hits=direct_hits,
            status="SUCCESS_HITS" if items else "SUCCESS_ZERO",
            metadata={"mode": "authenticated_global_search"},
        )
        self.stats["queries"] += 1
        self.stats["items"] += len(items)
        self.stats["direct_problem_hits"] += direct_hits

    async def _project_issues(
        self,
        client,
        headers,
        project_id,
        path,
        candidate_id,
        query,
    ):
        try:
            response = await client.get(
                f"{GITLAB_API}/projects/{project_id}/issues",
                params={
                    "scope": "all",
                    "search": query,
                    "in": "title,description",
                    "order_by": "updated_at",
                    "sort": "desc",
                    "per_page": 30,
                },
                headers=headers,
            )
            if response.status_code == 429:
                return {
                    "items": 0,
                    "direct": 0,
                    "completed": False,
                    "rate_limited": True,
                    "error": f"{path}:HTTP429",
                }
            response.raise_for_status()
            items = response.json()
        except Exception as exc:
            return {
                "items": 0,
                "direct": 0,
                "completed": False,
                "rate_limited": False,
                "error": f"{path}:{type(exc).__name__}",
            }

        direct_hits = 0
        for item in items:
            title = clean_text(item.get("title"))
            body = clean_text(item.get("description"))
            direct = await upsert_external_problem(
                source_type="gitlab_issue",
                source_key=path,
                external_id=str(item.get("id") or item.get("iid")),
                title=title,
                body=body,
                url=item.get("web_url"),
                author=(item.get("author") or {}).get("username"),
                published_at=parse_datetime(item.get("created_at")),
                updated_at=parse_datetime(item.get("updated_at")),
                score=float(item.get("upvotes") or 0)
                - float(item.get("downvotes") or 0),
                matched_candidate_id=candidate_id,
                raw_metadata={
                    "project_id": project_id,
                    "labels": item.get("labels"),
                    "discovery_query": query,
                    "mode": "public_project_issues",
                    "coverage_truth_version": "v4.4a",
                },
            )
            direct_hits += int(direct)

        await observe_source(
            source_type="gitlab_project_issues",
            source_key=path,
            source_url=f"https://gitlab.com/{path}/-/issues",
            origin="discovered",
            seen=len(items),
            relevant=len(items),
            direct_problem=direct_hits,
            metadata={"project_id": project_id, "last_query": query},
        )

        return {
            "items": len(items),
            "direct": direct_hits,
            "completed": True,
            "rate_limited": False,
            "error": None,
        }
