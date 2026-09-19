# Radar V4.2 — Local Problem Recurrence

## Purpose

Execute the first V4.1 planned research method:

`local_problem_recurrence_search`

No LLM is called.

## Why this stage exists

The current 46 Radar Cases are all WATCH because C02 (`problem_recurs`)
has not been proven under the new evidence-ledger semantics.

V4.2 asks a narrow question:

> Is there another independent HN/Reddit discussion describing the same underlying problem?

It does not ask whether the opportunity is attractive.

## Corpus

Uses the repository's current HN + Reddit `Post` table.

Direct-problem corpus admission requires:
- non-empty meaningful text;
- explicit friction/failure language;
- product/work/technical context.

The executor preserves discussion independence:
- Reddit comments in one root thread become one discussion;
- Hacker News comments sharing a root story become one discussion.

## Local retrieval

Hybrid local score:
- word TF-IDF (1–2 grams)
- character TF-IDF (3–5 grams)

The score alone cannot create evidence.

A deterministic strong match additionally requires:
- high word similarity;
- high character similarity;
- >=3 shared specific terms;
- overlap in a failure-mode bucket;
- a different discussion/source family.

## Three outcomes

### STRONG

The local deterministic guards all pass.

The discussion may be written into the Evidence Ledger as direct C02 SUPPORT.

### AMBIGUOUS

There is enough lexical/structural similarity to justify a narrow semantic check,
but not enough to call SUPPORT.

The research action can become eligible for:
`same_problem_verify`

The AI call is not executed in V4.2.

### REJECT

No useful evidence.

AI is not allowed to "think harder" because AI cannot manufacture missing evidence.

## Important C02 migration correction

The original first-hand community problem is now counted as the first direct
occurrence family for C02.

C02 requires two independent direct support families.

Therefore:

original occurrence + one strong independent occurrence
= recurrence supported.

This does not mean either individual post proves recurrence by itself; the claim
state is evaluated over the evidence set.

## Cost

V4.2:
- algorithm/local processing only
- LLM calls: 0
- LLM spend: NT$0
