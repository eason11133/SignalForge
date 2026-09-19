# SignalForge — Money Trail + Revenue Wedge Product Update

## Why this exists

Founder first-use exposed a product failure that UI copy alone could not solve: the system could contain valid intelligence and still require the Founder to send a screenshot to ChatGPT to understand what to do next.

The acceptance target is now self-serve:

> Without asking ChatGPT, Founder must be able to see where money already flows, which buyer segment is worth pursuing, what existing spend might be captured, what paid dissatisfaction exists, where to find people, what to ask, how to run the cheapest test, and how to record the result.

This update does not add a new C-dimension or replace Radar/Brain truth. It adds one Founder workflow over existing Published evidence.

## Product workflow

```text
Published Radar / Brain thesis
        ↓
Money Trail reconstruction
        ↓
Buyer segment separation
        ↓
Existing spend buckets
        ↓
Who receives the money today
        ↓
Paid dissatisfaction
        ↓
Revenue Wedge projection
        ↓
Cheapest bounded test
        ↓
Founder playbook
        ↓
Existing Market Action registration + outcome recording
```

## 1. Money Trail reconstruction

For each current Brain thesis, SignalForge reads only existing validated Radar evidence and reconstructs six possible spend buckets:

- VENDOR_SPEND
- LABOR_SPEND
- CONTRACTOR_SPEND
- REWORK_COST
- RISK_COST
- LOST_REVENUE

Every spend item retains its source, excerpt, claim context and evidence grade.

Numeric spend is never invented. The system only surfaces amount strings that actually occur in evidence. `numeric_estimate_created` is explicitly false in v1.

## 2. Buyer segment separation

The system no longer defaults to one broad phrase such as “AI software teams”. It projects the evidence into a concrete segment when the current published context supports one, including:

- AI / software agencies
- startup CTO / technical leaders
- engineering teams
- enterprise tech teams
- solo builders
- outsourcing buyers

If the context does not support a segment, the answer stays unknown.

## 3. Paid dissatisfaction

A high-value evidence detector requires both:

- a paid/current-spend cue; and
- a dissatisfaction/manual-work/switching/failure cue.

Ordinary complaints do not qualify.

Paid dissatisfaction remains an investigation signal only. It is not automatic proof of WTP, demand, or an unresolved gap.

## 4. Revenue Wedge

There is no 0–100 Opportunity Score.

The projection uses qualitative states for:

- existing spend
- pain
- buyer reality
- unresolved gap
- buyer reachability
- MVP buildability
- trust burden
- competition evidence

Output is exactly one of:

- TRY_NOW
- INVESTIGATE
- NOT_NOW
- KILL

A critical REFUTED gate or right-to-win hard block forces KILL. TRY_NOW requires a much stronger conjunction of evidence and reachability; partial evidence defaults toward investigation instead of fake precision.

## 5. Founder playbook

The homepage now provides execution help directly:

- who to contact;
- where to start finding them;
- a copyable first outreach message;
- five behavior/current-spend questions;
- when a paid offer is allowed;
- sample target;
- success condition;
- failure / kill condition.

Channel suggestions are planning-only and never become buyer-access truth merely because the UI recommends them.

## 6. Direction probe

Founder can type a direction such as:

`AI-assisted software delivery / acceptance`

The system performs a read-only retrieval over existing SignalForge candidates and Published evidence and builds a provisional Money Trail from related cases.

The probe does not create a Candidate, Brain thesis, Radar claim, evidence row, or Market Truth. If current Published evidence is insufficient, the correct response is `NO_RELATED_PUBLISHED_EVIDENCE` rather than a generated market story.

## 7. Market outcome loop

Existing Market Action registration and completion remain the write authority for Founder/market actions.

The new homepage surfaces open actions and lets Founder record:

- result: PASS / FAIL / INCONCLUSIVE;
- observed sample size;
- actor/company labels;
- durable evidence references;
- decision-relevant findings;
- amount/currency when a positive payment outcome requires it.

The existing fail-closed observation-quality gate is preserved. Empty PASS/FAIL does not become calibration evidence.

## UI hierarchy

The default route is now Money Trail:

> 今天哪一筆錢最值得去拿？

The older Founder opportunity page remains available as `商機工作台`; it is no longer the first screen.

## Truth boundaries preserved

Unchanged core authority files include:

- signalforge_production_admission.py
- problem_recurrence_multi.py
- radar_ledger.py
- signalforge_brain_v2_engine.py
- signalforge_execution_governor.py
- signalforge_market_action_registry.py
- signalforge_runtime.py
- database/connection.py

Money Trail is a derived Founder projection. It cannot write C01–C14, Published evidence, Market Ground Truth, Brain truth, or Market Calibration.

Market Calibration remains dependent on real qualified outcomes.
