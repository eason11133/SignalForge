# SignalForge Part 5 — ChatGPT Integration

## Product contract

Part 5 makes ChatGPT a Founder reasoning workspace over SignalForge without granting it Market Truth authority.

### Read / reasoning tools

- `signalforge_search`
- `signalforge_get_thesis`
- `signalforge_probe_idea`
- `signalforge_falsify`
- `signalforge_compare`
- `signalforge_pending_decision_artifacts`

### Conversation → Decision Artifact

ChatGPT may call `signalforge_prepare_decision_artifact` to create a **PENDING_FOUNDER_CONFIRMATION** artifact.

It cannot confirm or commit that artifact through MCP. The Founder reviews the complete artifact in SignalForge's `/discuss` page and explicitly confirms it. Only then are the entries appended to the Part 2 Founder Memory ledger.

The write-back path has zero C01-C14 / Published Market Truth / calibration authority.

## Deployment reality (2026-09-06)

The MCP adapter uses the official MCP Python SDK v2. Install it separately with:

```powershell
pip install -r requirements-signalforge-chatgpt.txt
python .\signalforge_mcp_server.py
```

The local adapter listens at `http://127.0.0.1:8010/mcp` by default. ChatGPT cannot directly connect to localhost; a supported remote MCP deployment or Secure MCP Tunnel is required. Actual read/write availability also depends on the ChatGPT plan/workspace. Core SignalForge does not require the optional MCP dependency to run.

## Authority invariants

1. MCP read tools create zero Market Truth writes.
2. Fresh Probe / Falsify traces retain their Part 1/3 unvalidated boundaries.
3. Decision Artifact preparation creates zero Founder Memory writes.
4. Founder confirmation is explicit and occurs in SignalForge UI/API, not in the MCP tool surface.
5. Confirmed artifacts append only to Founder Memory and retain `MARKET_AUTHORITY=NONE` / `MARKET_TRUTH_IMPACT=NONE`.
6. Re-confirmation is idempotent.
7. Rejected artifacts cannot later be confirmed.
8. Artifact ledger is append-only and hash-chain verified.
