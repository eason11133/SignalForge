from __future__ import annotations


def main() -> int:
    """Validate the browser-visible Backlog API contract at the FastAPI app level.

    Do not inspect ``signalforge_router.routes`` directly. FastAPI versions differ in
    whether included APIRouters are flattened into the parent ``routes`` list or kept
    as nested route objects. The generated OpenAPI schema is the stable effective
    HTTP contract that the browser/API client actually sees.
    """
    from api.main import app

    expected: dict[tuple[str, str], tuple[str, str]] = {
        ("GET", "/api/signalforge/research-backlog"): ("list backlog", "research_backlog_list"),
        ("POST", "/api/signalforge/research-backlog/sync"): ("sync existing candidates", "research_backlog_sync"),
        ("POST", "/api/signalforge/research-backlog/ideas"): ("add external ideas", "research_backlog_add_ideas"),
        ("POST", "/api/signalforge/research-backlog/start"): ("start bounded batch", "research_backlog_start"),
        ("POST", "/api/signalforge/research-backlog/stop"): ("stop after current job", "research_backlog_stop"),
        ("GET", "/api/signalforge/research-backlog/{item_id}"): ("opportunity detail", "research_backlog_item"),
    }

    schema = app.openapi()
    paths = schema.get("paths") if isinstance(schema, dict) else None
    if not isinstance(paths, dict):
        print("RESEARCH_BACKLOG_ROUTE_SMOKE_FAIL", "OpenAPI paths missing")
        return 2

    discovered: list[dict[str, object]] = []
    for path, operations in paths.items():
        if "research-backlog" not in str(path):
            continue
        methods = []
        if isinstance(operations, dict):
            methods = sorted(
                str(method).upper()
                for method in operations.keys()
                if str(method).lower() in {"get", "post", "put", "patch", "delete", "options", "head"}
            )
        discovered.append({"path": str(path), "methods": methods})

    missing: list[dict[str, str]] = []
    wrong_handler: list[dict[str, str]] = []
    for (method, path), (purpose, handler_name) in expected.items():
        operations = paths.get(path)
        if not isinstance(operations, dict) or method.lower() not in operations:
            missing.append({"method": method, "path": path, "purpose": purpose})
            continue
        operation = operations.get(method.lower())
        operation_id = str(operation.get("operationId") or "") if isinstance(operation, dict) else ""
        if handler_name not in operation_id:
            wrong_handler.append({
                "method": method,
                "path": path,
                "expected_handler": handler_name,
                "operation_id": operation_id,
            })

    if missing or wrong_handler:
        print("RESEARCH_BACKLOG_ROUTE_SMOKE_FAIL", {"missing": missing, "wrong_handler": wrong_handler})
        print("RESEARCH_BACKLOG_ROUTE_SMOKE_DISCOVERED", discovered)
        return 2

    print("RESEARCH_BACKLOG_ROUTE_SMOKE_OK", discovered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
