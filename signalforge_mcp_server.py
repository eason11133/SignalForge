"""Optional SignalForge MCP adapter — Part 5 Closure.

Deployment contract
-------------------
SignalForge supports **Secure MCP Tunnel only** for ChatGPT connectivity in this
release.  The server binds to loopback (127.0.0.1) and is not an authenticated
public remote endpoint.  Do not expose port 8010 directly to the public internet.
A future public deployment must add authentication/authorization before it can be
considered supported.

Permission contract
-------------------
`signalforge_prepare_decision_artifact` is a WRITE/MODIFY action because it
persists a Pending Decision Artifact, even though it writes zero Market Truth and
cannot confirm Founder Memory.  All other tools are read/search style actions.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_DEPLOYMENT_MODE = "SECURE_MCP_TUNNEL_ONLY"


def build_mcp_server():
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except Exception as exc:  # pragma: no cover - optional core dependency
        raise RuntimeError(
            "Official MCP Python SDK is not installed. Run: pip install -r requirements-signalforge-chatgpt.txt"
        ) from exc

    from processors.signalforge_chatgpt_integration import (
        build_discussion_packet,
        compare_for_chatgpt,
        falsify_for_chatgpt,
        list_decision_artifacts,
        prepare_decision_artifact,
        probe_idea_for_chatgpt,
        search_signalforge_for_chatgpt,
    )

    mcp = MCPServer("SignalForge")

    read_closed = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
    read_open = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)
    write_pending = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

    @mcp.tool(annotations=read_closed)
    async def signalforge_search(query: str, weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
        """Search SignalForge's current decision portfolio. READ-only; creates no Market Truth."""
        return await search_signalforge_for_chatgpt(query, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)

    @mcp.tool(annotations=read_closed)
    async def signalforge_get_thesis(thesis_id: str) -> dict[str, Any]:
        """Get a truth-separated discussion packet for one Published thesis. READ-only."""
        return await build_discussion_packet(thesis_id)

    @mcp.tool(annotations=read_open)
    async def signalforge_probe_idea(title: str, description: str = "") -> dict[str, Any]:
        """READ/search action: run Part 1 zero-AI fast probe. Fresh traces remain unvalidated and are not persisted as Market Truth."""
        return await probe_idea_for_chatgpt(title, description)

    @mcp.tool(annotations=read_open)
    async def signalforge_falsify(title: str, description: str = "", thesis_id: str = "") -> dict[str, Any]:
        """READ/search action: find counterevidence candidates. Fresh results cannot mutate Published Market Truth."""
        return await falsify_for_chatgpt(title=title, description=description, thesis_id=thesis_id or None)

    @mcp.tool(annotations=read_closed)
    async def signalforge_compare(thesis_ids: list[str], weekly_hours: float = 10.0, cash_need: str = "HIGH", long_term: str = "HIGH") -> dict[str, Any]:
        """READ-only: compare Published theses with Part 4 Founder Acceptance Closure rules."""
        return await compare_for_chatgpt(thesis_ids, weekly_hours=weekly_hours, cash_need=cash_need, long_term=long_term)

    @mcp.tool(annotations=write_pending)
    async def signalforge_prepare_decision_artifact(
        subject_key: str,
        entries: list[dict[str, Any]],
        subject_label: str = "",
        thesis_id: str = "",
        discussion_summary: str = "",
    ) -> dict[str, Any]:
        """WRITE/MODIFY: persist a Pending Founder Decision Artifact.

        This action does NOT write Founder Memory or Market Truth, but it DOES
        durably modify SignalForge state.  The Founder must review and explicitly
        confirm the artifact in SignalForge before Founder Memory is appended.
        """
        return prepare_decision_artifact(
            subject_key=subject_key,
            subject_label=subject_label or None,
            thesis_id=thesis_id or None,
            discussion_summary=discussion_summary or None,
            entries=entries,
            source="CHATGPT_MCP",
        )

    @mcp.tool(annotations=read_closed)
    def signalforge_pending_decision_artifacts() -> dict[str, Any]:
        """READ-only: list pending/confirmed/rejected Decision Artifacts."""
        return list_decision_artifacts(limit=100)

    return mcp


mcp = None
try:
    mcp = build_mcp_server()
except RuntimeError:
    # Keeps core SignalForge imports healthy when optional MCP dependency is absent.
    pass


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit("MCP dependency missing. Run: pip install -r requirements-signalforge-chatgpt.txt")
    # SECURITY: loopback only. Use Secure MCP Tunnel; do not expose directly.
    mcp.run("streamable-http", host="127.0.0.1", port=8010)
