# AI Opportunity Radar — Research Log

> Purpose: preserve algorithmic hypotheses, failures, revisions, and empirical observations so the product can later be written up as a research report.
>
> Status: engineering research log, not yet a peer-reviewed study. Numerical results below come from the local Radar dataset and processor runs.

## Research direction

Working research question:

**How can multi-source AI community and market data be used to distinguish popular topics, real user problems, and commercially meaningful opportunities without forcing the system to invent opportunities when evidence is weak?**

Possible paper framing:

**From Complaints to Opportunities: An Evidence-Aware Multi-Source Framework for AI Market Opportunity Discovery**

Chinese working title:

**從使用者抱怨到商業機會：基於多來源證據融合之 AI 市場商機偵測框架**

## Core research questions

### RQ1
Is textual or semantic similarity sufficient to determine that two discussions describe the same user problem?

### RQ2
Can a structured Problem Fingerprint reduce false positives caused by topic similarity?

Problem Fingerprint fields:

- Actor
- Task
- Object / System
- Failure Mode
- Consequence
- Workaround
- Buyer Context

### RQ3
How should heterogeneous evidence sources play different roles when deciding whether a problem should be upgraded into a market opportunity?

Current evidence semantics:

- HN / Reddit: community problem evidence
- Stack Overflow: direct technical problem corroboration
- GitHub: solution supply / builder activity
- Jobs: buyer / organizational demand
- Packages / Hugging Face: ecosystem activity
- YC: startup / competitor evidence
- News: why-now / market timing
- ArXiv: research / technical enabler

## Iteration history

### Stage 0 — Keyword complaint clustering

Observed dataset:

- 155 complaint candidates
- 21 clusters
- 18 generated pain points

Failure:

- Large `other` bucket mixed unrelated complaints.
- Keyword buckets overlapped heavily.
- Same noun/topic was repeatedly mistaken for the same problem.
- LLM synthesis could turn incoherent clusters into seemingly coherent pain points.

Conclusion:

**Keyword overlap is not a reliable problem identity function.**

### Stage 1 — Semantic clustering

Attempts:

- discussion-level aggregation
- cleaning / boilerplate removal
- TF-IDF / LSA similarity
- cohesion thresholds
- independent discussion requirements

Failure examples:

- different email problems merged because both discussed email/account issues
- abstract AI-human capability debates grouped as actionable problems
- similar topic did not imply same actor-task-failure relationship

Conclusion:

**Semantic topic similarity is still weaker than structured problem equivalence.**

### Stage 2 — Strict precision gate

A strict clustering version produced:

- 143 actionable evidence rows
- 75 independent discussions
- 0 accepted clusters

Interpretation:

The system became able to safely say **NO**, but recall became too weak.

Important principle:

**Zero detected opportunities is preferable to fabricated opportunities.**

### Stage 3 — Problem Fingerprint

Pipeline:

raw discussion
→ structured problem extraction
→ Actor / Task / Object / Failure / Consequence
→ pair retrieval
→ LLM same-problem verification

Observed run:

- 75 independent candidate discussions
- 46 usable structured problems
- 1 candidate same-problem pair
- 0 verified same-problem edges
- 0 recurring problem clusters

Finding:

A real problem does not need to recur in HN/Reddit wording before it can be commercially interesting.

Conclusion:

**Community recurrence alone is too restrictive as an opportunity gate.**

### Stage 4 — Problem Candidate layer

New conceptual model:

Raw Signal
→ Problem Candidate
→ Cross-source Enrichment
→ Corroborated Problem
→ Opportunity

The 46 validated structured problems are preserved as candidates instead of being discarded.

### Stage 5 — Cross-source enrichment v1

Observed run:

- 46 Problem Candidates
- 40 retrieval leads
- 1 verified external evidence
- 45 Candidate
- 1 Corroborated
- 0 Opportunity

Failure:

Using complaint-like wording to search all sources produced poor recall because:

- job postings express capabilities, not complaints
- GitHub repositories describe solutions
- ArXiv describes research concepts
- YC describes company value propositions

Conclusion:

**Cross-source retrieval must be source-aware.**

### Stage 6 — Source-specific retrieval v2

Added:

- per-source retrieval profiles
- solution terms
- buyer capability terms
- research terms
- word TF-IDF + character n-gram retrieval
- LLM evidence verifier
- evidence verdict cache

Observed run:

- 46 Problem Candidates
- 552 retrieval leads
- 14 verified external evidence
- 37 Candidate
- 7 Corroborated (old semantics)
- 2 Opportunity (old semantics)

Problem:

The two "opportunities" were supported by Jobs + News but lacked direct independent proof that the underlying problem itself recurred.

Conclusion:

**Market activity is not equivalent to problem corroboration.**

### Stage 7 — Decision-quality semantics v3

Current stages:

1. **Problem Candidate**
   - community evidence exists
   - no sufficient external support

2. **Market-supported**
   - jobs / news / solutions / ecosystem evidence exists
   - but no direct independent corroboration of the same problem

3. **Corroborated Problem**
   - same or equivalent problem independently appears elsewhere

4. **Verified Opportunity**
   - corroborated problem
   - buyer evidence
   - market / solution / timing context
   - sufficient specificity
   - sufficient confidence

Observed run after semantic correction:

- 46 total Problem Candidates
- 37 Candidate
- 9 Market-supported
- 0 Corroborated Problem
- 0 Verified Opportunity
- 14 verified external evidence
- LLM cost on cached rerun: NT$0.00

Interpretation:

The system did **not** force an opportunity output when evidence was insufficient.

## Emerging research contribution

The strongest current contribution is not the dashboard.

It is the evidence policy:

> **What evidence is sufficient to upgrade a community problem into a market opportunity?**

A useful finding so far:

- topic similarity ≠ same problem
- market attention ≠ problem corroboration
- job demand ≠ proof that users experience the problem
- missing competitors ≠ proven supply gap
- one complaint ≠ recurring unmet need
- evidence insufficiency should permit abstention

## Important research concept

### Calibrated abstention / uncertainty-aware decision making

A market-opportunity discovery system should not optimize for producing a fixed number of opportunities.

It should be allowed to output:

> "A real problem was detected, but there is not yet enough evidence to call it an opportunity."

This is a core design objective going forward.

## Data snapshot

Current local dataset around 2026-08-23:

- Hacker News posts: 7,009
- Reddit posts: 1,138
- Users: 4,943
- Stack Overflow questions: 532
- GitHub repositories: 208
- Hugging Face models: 100
- Package download time-series rows: 3,444
- YC companies: 164
- News events: 649
- ArXiv events: 582

## What is still missing for a formal study

Before claiming academic performance, add:

1. literature review
2. human-labeled ground truth
3. baseline comparison
4. precision / recall / F1
5. false-positive analysis
6. cross-source ablation
7. source reliability analysis
8. inter-annotator agreement if multiple human annotators are available
9. temporal evaluation on later unseen data
10. explicit cost / latency evaluation

Potential baselines:

- keyword clustering
- TF-IDF clustering
- embedding-only semantic clustering
- Problem Fingerprint without verifier
- Problem Fingerprint + verifier
- source-aware retrieval + evidence policy

## Preservation rule

Do not delete failed algorithm versions or their outputs merely because they were bad.

Failed versions are experimental evidence and should be retained through:

- backups
- commit history
- research log entries
- representative false-positive examples
- run metrics

Future material changes to Radar inference logic should add a short entry to this file.

## Founder Reality / Attention-first milestone

New product finding:

The bottleneck is no longer raw signal discovery. The founder's scarce resource is attention.

The UI therefore changed from a database/status dashboard into an attention triage surface:
- first view shows at most three items
- raw scores and evidence are collapsed
- unknown Solution / Competition / Build / Distribution / Race information is explicitly marked unknown
- the system must not convert missing evidence into optimistic AI prose

New future research / product dimensions:
- persistent Company Capability Profile
- Solution Landscape
- unresolved-gap evidence
- Build-to-customer-satisfaction estimation
- Distribution feasibility
- Opportunity Window / Race Risk
- pre-mortem evidence
- explicit Kill Criteria

Important anti-survivorship rule:
Persistence is not automatically a virtue. Before investing heavily, define evidence-based stop conditions.
