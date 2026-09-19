# SignalForge Founder Observation Quality — Human Review Closure R4

This is a narrow cumulative Founder acceptance closure. It supports either the last explicitly safe **Source Expansion Wave 4** baseline or an already-successful **Founder Observation Quality Repair R3** receipt. It does not start Wave 5.

## Scope

Only two behaviors change:

1. exact Founder relevance now requires compatible **actor/workflow/object identity** in addition to problem-dimension overlap;
2. Founder primary evidence selects a representative per independence group while preserving all child traces as raw/depth evidence.

No source adapters are added. Money Trail, C01-C14, dashboard code, thread-independence counting, Published evidence boundaries, and Market Truth authority are unchanged.

## Human-review failure repaired

The previous live run improved to `raw=126`, `relevant=35`, `independent=8`, `unique_authors=12`, but still admitted two classes of false positive:

- **BUILD_AGENT / build infrastructure**: MSBuild, deployment permissions, CI/build agent comments could look relevant because they contained words such as `agent`, `correct`, `check`, or `whether`.
- **DOCUMENTATION review**: automated reviews of markdown, references, license/version metadata, API/security/test/CI documentation could look relevant because they contained `AI`, `agent`, `test`, `quality`, `complete`, and `review`.

R4 does not blacklist the reported Stack Overflow URL or GitHub repository. It introduces general role/object disambiguation.

## Workflow identity contract

The semantic profile now distinguishes conceptually:

- `AI_CODING_AGENT`
- `BUILD_AGENT`
- `CHAT_AGENT`
- `GENERAL_SOFTWARE_AGENT`
- `DOCUMENTATION_AGENT_REVIEW`
- `UNKNOWN_AGENT`

and target objects such as:

- `SOFTWARE_IMPLEMENTATION`, `CODE_CHANGE`, `REFACTOR`, `FEATURE`, `BUG_FIX`
- `DOCUMENTATION`, `DEPLOYMENT_PERMISSION`, `BUILD_INFRASTRUCTURE`, `GENERAL_QA`

For the exact Founder hypothesis, countable evidence requires BOTH:

A. an AI coding/development workflow acting on software implementation work; and
B. a core verification/failure dimension such as requirements, tests, correctness, acceptance, evidence, trust, or implementation completion.

The token `agent` never manufactures AI-coding identity. Build/CI/deployment and documentation-only objects fail closed. Mixed traces remain eligible only when explicit AI-coding implementation identity is actually present.

## Positive controls preserved

- The Hacker News comment about functionality changes, requirements understanding, and human review remaining essential stays relevant.
- AgentTeams traceable AI coding workflow stays eligible.
- Generic review remains supporting-only without a core target failure.

## Primary evidence diversity

`relevant_trace_count` and independent discussion counting are unchanged. All relevant child comments remain inspectable depth evidence. Founder primary evidence now chooses at most one representative per `independence_group_key` and prefers the trace with richer core problem dimensions / implementation evidence. This is display/evidence selection only; raw traces are not deleted and recurrence authority is not changed.

## Truth boundaries

- `historical_published_evidence_used = false` in the fresh-only exact benchmark.
- `published_money_trail_used = false`.
- `market_truth_writes = 0`.
- transport failure remains separate from market absence.
- final `FOUNDER` status stays `PENDING_HUMAN_REVIEW`; it is never promoted automatically from a semantic/live PASS.


## R5 Final Narrow Semantic Closure

- Documentation object dominance now overrides incidental repository vocabulary. Documentation QA does not become software implementation merely because it mentions Pull Requests, CI, tests, APIs, code examples, licenses or versions.
- Bare `correct` no longer establishes `COMPLETION_VERIFICATION`; explicit verification/correctness/acceptance/evidence or other target failure dimensions are required.
- Mixed traces remain eligible when they explicitly establish that an AI coding agent changed/implemented software and that implementation is being verified against tests, requirements, diffs or acceptance.
- No source expansion, dashboard, Money Trail, Market Truth or thread-independence behavior is changed.


## R6 live-path closure

R5's deterministic English documentation fixture passed, but the actual live Korean/English GitHub documentation-quality review still leaked into Founder primary evidence. The cause was a two-cue documentation-dominance threshold: multilingual prose left only one English documentation cue while incidental `Pull Request` text created a `CODE_CHANGE` object.

R6 changes the general contract:

- multilingual documentation cues can establish the `DOCUMENTATION` object;
- when a trace has a documentation object and lacks direct implementation evidence, `DOCUMENTATION` dominates even if repository vocabulary mentions PR/CI/API/code examples;
- explicit implementation relationships still override documentation dominance for genuine mixed implementation+docs traces;
- live acceptance now independently rejects `DOCUMENTATION_AGENT_REVIEW + DOCUMENTATION` primary evidence unless direct implementation evidence is present, so a future classifier regression fails the installer instead of silently reaching Founder review;
- an actual live-failure-shaped multilingual regression fixture is included.


## Automation Artifact Closure R7

R6 removed multilingual documentation QA leakage but the exact live probe still surfaced a Claude Code-generated `DONE` coordination-board comment as `PROBLEM_DISCUSSION`. That is workflow telemetry, not a human market conversation.

R7 adds a narrow provenance/content-authority rule:
- explicit bot/agent-authored operational artifacts remain inspectable but are not countable human market evidence;
- an end-of-message `Generated by Claude Code`/equivalent footer is sufficient to fail closed for `DISCUSSION`/`ISSUE` evidence;
- ordinary human prose that says a report is generated automatically does not trigger this rule;
- a human complaint about having to verify an agent's completion claim remains eligible;
- Founder live acceptance hard-fails if an automated operational artifact reaches primary evidence.

This does not change Market Truth authority, source routing, source adapters, Wave 5, Money Trail, dashboard, or recurrence authority.
