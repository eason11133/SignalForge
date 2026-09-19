from __future__ import annotations


def main() -> int:
    from api.main import app

    expected: dict[tuple[str, str], str] = {
        ("GET", "/api/signalforge/research-backlog"): "research_backlog_list",
        ("POST", "/api/signalforge/research-backlog/sync"): "research_backlog_sync",
        ("POST", "/api/signalforge/research-backlog/ideas"): "research_backlog_add_ideas",
        ("POST", "/api/signalforge/research-backlog/start"): "research_backlog_start",
        ("POST", "/api/signalforge/research-backlog/stop"): "research_backlog_stop",
        ("POST", "/api/signalforge/research-backlog/{item_id}/handoff-copied"): "research_backlog_handoff_copied",
        ("GET", "/api/signalforge/research-backlog/{item_id}"): "research_backlog_item",
    }

    schema = app.openapi()
    paths = schema.get("paths") if isinstance(schema, dict) else None
    if not isinstance(paths, dict):
        print("RESEARCH_BACKLOG_V1_2_ROUTE_SMOKE_FAIL", "OpenAPI paths missing")
        return 2

    failures: list[dict[str, str]] = []
    for (method, path), handler in expected.items():
        operations = paths.get(path)
        if not isinstance(operations, dict) or method.lower() not in operations:
            failures.append({"method": method, "path": path, "error": "missing"})
            continue
        operation = operations[method.lower()]
        operation_id = str(operation.get("operationId") or "") if isinstance(operation, dict) else ""
        if handler not in operation_id:
            failures.append({"method": method, "path": path, "error": f"wrong handler: {operation_id}"})

    if failures:
        print("RESEARCH_BACKLOG_V1_2_ROUTE_SMOKE_FAIL", failures)
        return 2

    print("RESEARCH_BACKLOG_V1_2_ROUTE_SMOKE_PASS", len(expected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
