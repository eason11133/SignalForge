# SignalForge Founder Experience — Design System v1

## Product posture
SignalForge is a Founder Intelligence Workspace, not an admin dashboard. The primary question on every screen is: **What deserves the founder's attention now, why, and what happens next?**

## Information hierarchy
1. Founder action now
2. Opportunities worth attention
3. Maturity / current blocking question
4. Why-now evidence and named buyers
5. Machine next action
6. Deep evidence, claims, source health, calibration

Internal processor names, claim codes, source-family details, and calibration diagnostics are progressive disclosure. They are never the first reading layer.

## Visual direction
- Premium minimal, editorial data interface, restrained technical SaaS.
- Neutral semantic surfaces from the existing theme; one strong success/info accent at a time.
- Avoid AI-purple gradients, decorative glassmorphism, neon monitoring-dashboard aesthetics, and KPI-card walls.
- Cards exist only when they group a decision. Avoid nested cards for every datum.

## Typography
- System/Inter stack already used by the product.
- Page title: 30px, semibold, tight tracking.
- Opportunity title: 20px, semibold.
- Decision body: 12–14px with comfortable line-height.
- Technical metadata: 10–11px and visually subordinate.

## Opportunity grammar
Each opportunity must answer in this order:
1. Verdict / priority
2. Title
3. Maturity rail: Problem → Pain → Buyer → Solution → Gap → Market → Execution
4. Why it matters now
5. Current blocking question
6. What SignalForge is doing next
7. Named buyers
8. Optional deep evidence and claim states
9. One primary action: View opportunity

## Status grammar
- SUPPORTED: confirmed, success tone, check icon.
- INSUFFICIENT: evidence still needed, warning tone, filled dot.
- UNKNOWN: neutral, open dot.
- REFUTED: danger tone, X icon.
Meaning must never rely on color alone.

## Navigation
Primary founder navigation is deliberately small:
- Today / opportunities
- Research center
- Search
- Data & system
Database tables and processor modules do not become top-level navigation.

## Interaction
- One screen = one decision layer.
- Deep technical evidence uses native disclosure.
- Focus states visible on all interactive controls.
- Click targets are explicit; no hidden hotspot behavior.
- Text and chips must wrap safely at narrow widths.
- Motion is restrained and semantic; reduced-motion preferences remain respected by the browser/platform.

## Anti-pattern blacklist
- Six or more equal-weight KPI cards above the founder's actual work.
- Raw C02–C14 badges as the primary explanation.
- English internal enums as headline copy.
- “Attention 99” without interpretation.
- Separate Watch / Research / Ignore buttons with equal visual weight.
- Old Mind Mirror branding on the Founder product surface.
- Filling empty states with synthetic opportunities.


## Opportunity detail grammar — v2
The detail page is a founder decision brief, not a legacy candidate record. It must merge the candidate's source evidence with the current published RadarCase/RadarClaim decision truth.

Reading order:
1. Published verdict + human title
2. One-sentence current judgment
3. Current gate + maturity rail
4. Founder-action boundary: **Now you act** or **SignalForge keeps researching**
5. Why it matters + biggest unknown + next gate-changing evidence
6. Named Buyer signals
7. Commercial-reality summary
8. Key source evidence
9. Raw claim states / legacy scores only inside technical disclosure

### Founder action boundary
Machine-doable research must never be styled as a Founder task. If the validation boundary is MACHINE_FIRST or PREBUILT, the page says **現在不用你出手** and explains what SignalForge is doing. Only FOUNDER_ACTION_NOW may ask for a real-world human validation action.

### Commercial reality
Do not render a wall of equally weighted UNKNOWN cards. Summarize how many commercial claims remain unproven, explain that SignalForge will continue automatically, then place individual differentiation / distribution / WTP / timing / competition / switching / execution states behind disclosure.

### Evidence
Direct, traceable evidence is readable before technical scoring. Show source, verified state, short excerpt, and source link. Internal claim codes, fingerprints, legacy market scores, and IDs stay in **系統與技術細節**.

## Opportunity intelligence / discussion handoff — v4

The detail page is an **opportunity intelligence brief**, not a product-planning engine. SignalForge's job ends at discovery, filtering, evidence organization, explicit unknowns, and company-reality context.

### Product boundary

SignalForge:
- discovers and ranks opportunities,
- organizes traceable evidence,
- separates current solutions from competitive / alternative context,
- separates confirmed unresolved-gap evidence from unknowns,
- exposes Company Reality without translating demo ability into delivery ability,
- prepares a zero-LLM Founder Discussion Handoff.

Founder + ChatGPT:
- interpret the opportunity,
- challenge the thesis,
- discuss whether it is worth validating,
- only when asked, explore product wedges, MVP scope, pricing, validation, or kill criteria.

Eason One:
- receives a decision only after the Founder chooses to execute.

SignalForge must not silently cross from **"this deserves attention"** into **"this is what you should build."**

### Primary reading order
1. **市場現在怎麼解** — named current solutions first. Competitive / alternative context is shown separately because competitor existence does not prove that the core problem is solved.
2. **為什麼到現在還沒被解掉** — confirmed C07 persistence / failure evidence is visually separated from unknowns and adjacent context such as switching friction or technology regime.
3. **這題適不適合我解** — Company Reality / C09 plus persistent capability gaps. “Can build a demo” is never translated into “can deliver customer satisfaction.”
4. **Founder discussion boundary** — explicitly say that SignalForge stops here. Product wedge, MVP, pricing, and validation decisions belong in Founder + ChatGPT discussion.
5. **Technical / evidence disclosure** — claim states and source evidence remain available below the decision layer.

### Founder Discussion Handoff

Every opportunity detail supports zero-LLM handoff from already collected truth:
- **Copy and open ChatGPT** — copies the handoff to the clipboard and opens a normal ChatGPT tab. It does not pretend the local dashboard can inject text directly into an existing ChatGPT conversation.
- **Copy Handoff only**
- **Download Markdown**
- **Print / Save as PDF**

The handoff includes:
- opportunity title and problem,
- actor / task / consequence / buyer context,
- current workaround,
- published verdict and decision reason,
- named current solutions,
- separate competitive / alternative context,
- confirmed unresolved-gap evidence,
- explicit unknowns and adjacent context,
- named buyers,
- Company Reality and capability gaps,
- any already-existing product hypothesis clearly marked as hypothesis,
- claim states,
- traceable evidence.

### Conversation contract

The ChatGPT handoff is **not** a forced ten-step analysis prompt. It tells ChatGPT to:
- treat the packet as already-read context,
- keep evidence, SignalForge judgment, inference, and hypothesis separate,
- not assume the opportunity is good just because SignalForge surfaced it,
- not automatically generate a 7-day wedge, 30-day MVP, pricing, or execution plan,
- only research externally when the Founder asks for freshness or a key fact needs verification,
- directly answer whatever angle the Founder asks next.

If the pasted handoff contains no Founder question, ChatGPT should only acknowledge the handoff briefly and wait for the next question.

### Truth constraints
- Never invent a named competitor, current solution, failure reason, buyer, or product wedge to make the page feel complete.
- Current solutions and competitors are different data classes and must not be merged for convenience.
- If C07 is UNKNOWN / INSUFFICIENT, say the unresolved gap has not been proven.
- Evidence rows under an unconfirmed C07 state may be shown as evidence-under-review, not as confirmed reasons.
- Product hypotheses, if already present in published reality data, are discussion context only and must never be styled as SignalForge's recommendation.
- Handoff generation is client-side and consumes **zero additional SignalForge LLM calls**.
