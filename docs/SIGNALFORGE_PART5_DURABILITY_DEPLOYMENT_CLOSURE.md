# SignalForge Part 5 — Durability + Deployment Closure

## Reproducible defect closed

The original Decision Artifact ledger used a process-local `threading.RLock` around whole-file read/modify/rewrite. FastAPI and MCP can run in separate processes, so that lock could not serialize concurrent writers. Independent adversarial review reproduced a lost-update failure where 30 successful prepare processes durably retained fewer than 30 artifacts.

## Decision Artifact persistence

Decision Artifact persistence is now SQLite-backed:

- append-only event table
- `BEGIN IMMEDIATE` write transactions
- WAL journal mode
- `synchronous=FULL`
- bounded SQLite busy timeout
- existing event hash-chain integrity retained
- legacy JSONL migration supported

The durable store declares:

```text
cross_process_safe = true
storage = SQLITE_BEGIN_IMMEDIATE_HASH_CHAIN
```

## Founder Memory cross-process serialization

Confirming a Decision Artifact ultimately appends into the existing Part 2 Founder Memory JSONL/hash-chain ledger. That write path is now protected by a real cross-process lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) in addition to the existing process-local lock.

The Founder Memory data format and Market Truth authority remain unchanged.

## Confirm idempotency

Artifact confirmation holds the Decision Artifact SQLite write transaction while performing the Founder Memory append. Retried / concurrent confirmation of the same artifact resolves as one durable `CONFIRMED` plus idempotent `ALREADY_CONFIRMED` results. Founder Memory receives the artifact exactly once.

## MCP deployment contract

This release supports **Secure MCP Tunnel only** for connecting a local/private SignalForge MCP server to ChatGPT.

- MCP server binds to loopback (`127.0.0.1`).
- An unauthenticated public remote endpoint is **not supported**.
- If public remote hosting is added later, authentication and authorization are mandatory before that mode can be considered supported.

## Permission contract

Market Truth write authority remains zero, but permission classification reflects durable side effects:

- search/read/get thesis/probe/falsify/compare: read-style operations
- `signalforge_prepare_decision_artifact`: **WRITE / MODIFY** because it persists a Pending Artifact
- MCP exposes no confirm/commit Founder Memory tool
- only explicit Founder confirmation in SignalForge UI may append a confirmed artifact to Founder Memory

Tool annotations are UX/permission hints, not the security boundary. The actual boundary is the absence of a remote confirm tool plus explicit Founder UI confirmation and zero Market Truth writer.

## Engineering acceptance vs Live ChatGPT acceptance

These statuses are separate:

```text
Engineering acceptance: independently testable in the repository
Live ChatGPT acceptance: LIVE_ACCEPTANCE_PENDING or PLATFORM_BLOCKED
```

Engineering PASS must never be presented as proof that the user's current ChatGPT plan/workspace can attach or use the custom MCP integration.

## Concurrent durability acceptance

The closure contains process-based adversarial acceptance for:

1. 30 concurrent `prepare_decision_artifact` processes — all 30 must durably persist.
2. Concurrent prepare + confirm processes — every confirmed artifact must exist both in SQLite state and Founder Memory.
3. Multiple processes confirming the same artifact — exactly one Founder Memory append is permitted.
