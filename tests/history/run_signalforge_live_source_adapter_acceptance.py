from __future__ import annotations

import concurrent.futures
import json
import sys
import types
from typing import Any, Callable


def _stub_database() -> None:
    db_pkg = sys.modules.setdefault("database", types.ModuleType("database"))
    conn = types.ModuleType("database.connection")

    class Field:
        def in_(self, *_): return self
        def is_(self, *_): return self

    class Dummy:
        id=Field(); candidate_id=Field(); claim_id=Field(); evidence_id=Field(); case_id=Field()

    for name in ("ProblemCandidate", "RadarCase", "RadarClaim", "RadarClaimEvidence", "RadarEvidence"):
        setattr(conn, name, Dummy)
    conn.async_session = None
    sys.modules["database.connection"] = conn
    setattr(db_pkg, "connection", conn)


_stub_database()

from processors.signalforge_founder_idea_loop import (
    FetchError,
    _search_github_issues,
    _search_github_repositories,
    _search_hn,
    _search_stackoverflow,
)
from processors.signalforge_trust_falsification import build_falsification_queries

TITLE = "RFQ Quote Comparator"
DESCRIPTION = (
    "Small procurement teams receive supplier PDF, Email and Excel quotes and must manually normalize "
    "specifications, price, delivery and terms before comparing them."
)

SEARCHERS: tuple[tuple[str, Callable[[str], dict[str, Any]]], ...] = (
    ("HACKER_NEWS_ALGOLIA", _search_hn),
    ("STACK_OVERFLOW_API", _search_stackoverflow),
    ("GITHUB_ISSUES", _search_github_issues),
    ("GITHUB_REPOSITORIES", _search_github_repositories),
)
CONTRACT_REJECTION_CODES = {400, 422}
ACCESS_LIMIT_CODES = {401, 403, 429}
TRANSIENT_CODES = {408, 425, 500, 502, 503, 504}


def _execute_one(theme: str, raw_query: str, source_name: str, searcher: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {"theme": theme, "source": source_name, "raw_query": raw_query}
    try:
        result = searcher(raw_query)
        transport = dict(result.get("transport") or {})
        row.update({
            "status": "ACCEPTED",
            "http_status": transport.get("status_code"),
            "final_search_query_used": result.get("final_search_query_used"),
            "query_contract": result.get("query_contract"),
            "count": result.get("count"),
        })
    except FetchError as exc:
        status = exc.status_code
        row.update({"http_status": status, "error": str(exc), "response_body": exc.response_body})
        if status in CONTRACT_REJECTION_CODES:
            row["status"] = "CONTRACT_REJECTED"
        elif status in ACCESS_LIMIT_CODES:
            row["status"] = "ACCESS_OR_RATE_LIMITED"
        elif status in TRANSIENT_CODES or status is None:
            row["status"] = "LIVE_PENDING_NETWORK_OR_SOURCE"
        else:
            row["status"] = "LIVE_PENDING_OTHER_HTTP"
    except Exception as exc:
        row.update({"status": "LIVE_PENDING_NETWORK_OR_SOURCE", "http_status": None, "error": f"{type(exc).__name__}: {exc}"})
    return row


def main() -> int:
    queries = build_falsification_queries(TITLE, DESCRIPTION)
    tasks: list[tuple[str, str, str, Callable[[str], dict[str, Any]]]] = []
    for lens in queries:
        theme = str(lens.get("theme") or "UNKNOWN")
        raw_query = str(lens.get("query") or "")
        for source_name, searcher in SEARCHERS:
            tasks.append((theme, raw_query, source_name, searcher))

    print("=" * 118)
    print("SIGNALFORGE LIVE SOURCE ADAPTER ACCEPTANCE — REAL HTTP CONTRACT")
    print("=" * 118)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(_execute_one, *task) for task in tasks]
        rows = [f.result() for f in futures]

    order = {name: i for i, (name, _) in enumerate(SEARCHERS)}
    theme_order = {str(x.get("theme")): i for i, x in enumerate(queries)}
    rows.sort(key=lambda x: (theme_order.get(str(x.get("theme")), 99), order.get(str(x.get("source")), 99)))
    for row in rows:
        status = row.get("status")
        theme = str(row.get("theme"))
        source = str(row.get("source"))
        code = row.get("http_status") or "NO_HTTP"
        if status == "ACCEPTED":
            print(f"PASS   {theme:<35} {source:<24} HTTP {code} query={row.get('final_search_query_used')!r}")
        elif status == "CONTRACT_REJECTED":
            print(f"FAIL   {theme:<35} {source:<24} HTTP {code} QUERY CONTRACT REJECTED")
        elif status == "ACCESS_OR_RATE_LIMITED":
            print(f"REVIEW {theme:<35} {source:<24} HTTP {code} access/rate-limited; not a 400/422 query rejection")
        else:
            print(f"PENDING {theme:<34} {source:<24} {code} {row.get('error')}")

    contract_failures = [x for x in rows if x.get("status") == "CONTRACT_REJECTED"]
    pending = [x for x in rows if x.get("status") not in {"ACCEPTED", "CONTRACT_REJECTED"}]
    print("-" * 118)
    summary = {
        "requests": len(rows),
        "accepted": sum(1 for x in rows if x.get("status") == "ACCEPTED"),
        "contract_rejected": len(contract_failures),
        "pending_or_limited": len(pending),
        "contract_rejection_codes": sorted(CONTRACT_REJECTION_CODES),
        "rows": rows,
        "truth_boundary": "LIVE_SOURCE_ACCEPTANCE_TESTS_TRANSPORT_QUERY_CONTRACT_ONLY;_IT_DOES_NOT_VALIDATE_MARKET_EVIDENCE_OR_MARKET_ABSENCE",
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, sort_keys=True))
    if contract_failures:
        print("FINAL_STATUS: LIVE_SOURCE_QUERY_CONTRACT_FAIL")
        return 1
    if pending:
        print("FINAL_STATUS: LIVE_SOURCE_ACCEPTANCE_PENDING_NETWORK_OR_RATE_LIMIT")
        return 10
    print("FINAL_STATUS: LIVE_SOURCE_ADAPTER_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
