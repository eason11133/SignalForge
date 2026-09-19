# SignalForge Part 4 — Founder Acceptance Closure

## Scope

This closure does not replace the Part 4 Opportunity Decision engine. It closes the seven Founder-acceptance gaps found by independent adversarial review while preserving Part 4's existing truth boundaries and original 43/43 regression contract.

### 1. Distribution / Founder Fit is a real actionability gate

`CASH / BOTH / ZIP2 / PARK` remains a Founder-facing **Market Track** projection of the existing Brain strategic track. It is not reclassified by this closure.

A separate **Founder Action** is now derived from distribution/actionability evidence. High trust burden, weak access, legitimacy, right-to-win, long time-to-value, deep integration, sensitive data, hardware and similar distribution burdens can block `ACTION_NOW` without rewriting the Market Track.

Example:

```text
Market Track: BOTH
Founder Action: VALIDATE_DISTRIBUTION
Reason: trust burden is HIGH
```

A refuted right-to-win can produce:

```text
Market Track: BOTH
Founder Action: PARK_OR_PARTNER
```

This deliberately separates "the market may be structurally + commercially interesting" from "Eason should act now".

### 2. Problem ↔ Structural Thesis relationship mapper

A new relationship mapper exposes the chain:

```text
Problem
→ Problem Lineage
→ Sellable Wedge
→ Structural Thesis
→ Underlying Transition
```

It only consumes existing identifiers/evidence-backed fields. Missing links remain `UNKNOWN`; the closure does not invent a lineage or transition narrative.

### 3. Validation Ladder + Wedge Expansion Ladder

The existing Part 4 Wedge Ladder is retained and explicitly named **Validation Ladder**:

```text
Problem → Buyer → Gap → Existing Spend → Reachable Buyer → Testable Wedge → Real Paid Outcome
```

A separate **Wedge Expansion Ladder** answers:

```text
Current Wedge
→ Evidence to Collect
→ Unlock Condition
→ Possible Next Wedge
```

If no evidence-backed next wedge exists, expansion remains `UNKNOWN`.

### 4. Synthetic provenance

Raw hypotheses must declare provenance such as:

- `FOUNDER_HYPOTHESIS`
- `MODEL_HYPOTHESIS`
- `MULTI_MODEL_CONVERGENCE`
- `SYNTHETIC_HYPOTHESIS`

Multiple models independently generating the same idea may increase the synthetic contributor count, but:

```text
independent_market_recurrence_count = 0
market_authority = NONE
truth_status = SYNTHETIC_UNVALIDATED
```

Synthetic convergence can never become Market Truth recurrence.

### 5. Raw Benchmark Batch ingestion

A bounded batch path accepts at most 60 raw hypotheses and performs:

```text
preserve provenance
→ dedupe
→ optional bounded Fast Probe
→ lineage candidate lookup
→ route for review
```

This is a benchmark / discovery sandbox with zero Market Truth authority. It does not promote hypotheses into C01–C14.

### 6. Compositional Ask SignalForge

Recognized predicates are combined with logical AND. For example:

```text
existing spend + paid dissatisfaction + reachable buyer
```

must satisfy all three predicates. A spend-positive but unreachable buyer is excluded.

Unsupported natural-language questions still fall back to the pre-existing bounded deterministic Ask behavior; the closure does not claim a general-purpose semantic query engine.

### 7. UI separates Market Track from Founder Actionability

The decision UI presents two distinct concepts:

```text
Market · BOTH
Founder · PARK_OR_PARTNER
```

The UI also exposes the relationship mapper, Validation Ladder, Wedge Expansion Ladder and Benchmark Batch provenance warning.

## Truth authority

This closure creates no Market Truth writer, no new C dimension and no automatic promotion/demotion of canonical thesis state. All outputs are Founder-facing decision projections or explicitly synthetic benchmark artifacts.
