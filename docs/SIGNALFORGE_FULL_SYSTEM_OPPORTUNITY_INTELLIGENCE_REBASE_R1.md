# SignalForge Full-System Opportunity Intelligence Rebase R1

**Release class:** Full-system strategic and authority rebase  
**Base snapshot:** `SignalForge_Latest_20260904-102356.zip`  
**Release ID:** `signalforge-full-system-opportunity-intelligence-rebase-r1`  
**Brain line:** G3 retained; this release does **not** open U29.  
**Market calibration:** **0 / UNVALIDATED** remains the only honest live-market state until real market outcomes exist.

---

## 1. Why this is a full-system rebase

The pre-release system already had deep evidence, truth, provenance, C01–C14, Brain v2 G3, Published/Shadow separation, bounded Research More, and a usable Founder surface. The primary problem was no longer “missing intelligence.” It was **authority misalignment across generations of the product**:

1. Candidate/solo surfaces still acted like the Founder decision entrance even though Brain v2 had evolved to persistent Problem/Transition lineages and Opportunity Theses.
2. “Founder fit” was too close to buildability/captureability and did not cleanly separate domain knowledge, buyer access, legitimacy, trust burden, and learning distance.
3. Research control still leaned toward “get more machine evidence” even when the next highest-value evidence should be a market action.
4. Evidence-precision protections still contained fail-open behavior and a cross-request cache race.
5. Runtime health could report the HTTP application as alive while the production database was unavailable.
6. Fast market outcomes, structural/Zip2 outcomes, and Founder-addressability outcomes were not separated enough for future calibration.

The shared root cause was **multiple useful subsystems with incomplete authority cutover**, not a lack of another score or another research wave.

---

## 2. Borrow vs Build contract

### Borrow — mature research/design priors, no need to re-prove from scratch

The release treats mature opportunity-discovery research as **design prior, not live market evidence**:

- Entrepreneurial Alertness: scanning/search → association/connection → evaluation/judgment
- Prior Knowledge / industry experience
- Third-person → first-person opportunity belief
- Windows of Opportunity: technological, demand, institutional/regulatory
- Lead User / ahead-of-trend / self-built workaround
- Market Opportunity Choice Set
- Effectuation / Affordable Loss
- Bricolage
- Legitimacy / provider credibility
- Network capability / buyer access
- Lean experimentation after thesis formation

These frameworks have **zero authority to promote C01–C14 claims** merely because academic literature supports the mechanism.

### Build / Experiment — SignalForge-specific unsolved work

- Extracting those constructs from heterogeneous live evidence without LLM truth invention
- Claim → evidence → construct semantic alignment
- Eason-specific first-person addressability without corrupting objective market truth
- Dual Zip2 Structural + Fast Validation search without authority contamination
- Research → market-action switching by marginal value of information
- Longitudinal calibration of which early signals actually predict outcomes

---

## 3. Full-system audit and closure

| Area | Pre-release state | Root problem | R1 closure | Post-release authority / target | Acceptance proof |
|---|---|---|---|---|---|
| Sources / Crawlers | Broad multi-source infrastructure existed | More sources would not fix decision-quality problems | No unnecessary crawler rewrite; preserve ingestion foundation | Sources remain observations, not opportunities | Existing source contracts preserved; no new truth authority |
| Candidate formation | Candidate evidence could count thread participants that did not support the same problem atom | Discussion/thread identity was confused with same-problem identity | Deterministic `same_problem_posts()` filtering; counts and persisted community evidence use same-problem posts only | Candidate = evidence/observation object; zero matching evidence is legal | No-DB acceptance checks same-problem filtering and zero-evidence legality |
| Evidence precision | Founder middleware had fail-open “keep strongest item” behavior | Fear of empty evidence caused false cleanliness | Removed fail-open; unrelated evidence may reduce to zero | 0 evidence is legal; no filler anchor | Acceptance: `precision.zero_same_problem_is_valid` |
| C05 Buyer Reality | Generic hiring/budget evidence could look too supportive for a narrow thesis | Broad buyer context was conflated with thesis-specific demand | Generic hiring remains RELATED/INSUFFICIENT; only narrow named-organization adjudicated SUPPORT may become DIRECT | Generic AI budget ≠ thesis-specific buyer demand | Acceptance covers RELATED cannot SUPPORT and narrow DIRECT path |
| C01–C14 Radar truth | Strong, sole atomic truth owner | Risk that new strategy/framework layers might become hidden truth writers | Explicitly retained as atomic market truth authority | Brain/strategy may derive, never silently promote Radar truth | Strategy frameworks declare zero live-truth authority |
| Brain v2 G3 | ProblemLineage / TransitionLineage / ExistingSystem / Intersection / Thesis existed | Strategic use lagged behind structural representation | Retain G3; decorate theses with strategy/addressability; portfolio exposes strategic summary/action queue | Brain = derived structural + strategic intelligence; not atomic truth owner | Static strategic enum/overlap/authority checks PASS |
| Zip2 structural search | Structural intelligence existed; legacy transition score already demoted | Founder goal was not explicit enough at final decision layer | Formal `ZIP2_STRUCTURAL` readiness and strategic classification | Primary long-term target = Eason-addressable structural opportunity | BOTH/ZIP2 bounded enum acceptance PASS |
| Fast Validation search | Short-term validation existed implicitly across market-probe thinking | No explicit peer track to Zip2 search | Formal Fast Validation readiness, time-to-truth logic, market-action option | Secondary target = Eason-addressable, cheap-to-falsify opportunity | Market-action-vs-research acceptance PASS |
| Founder Addressability | Buildability / C09/C10/C13 contributed heavily to captureability | AI execution capacity could be mistaken for domain credibility | Deterministic dimensions: task capability, domain knowledge, buyer access, legitimacy, bridgeability, right-to-win, trust burden, learning distance | Third-person opportunity truth is separate from Eason first-person addressability | Regulated-domain and unknown-domain tests PASS |
| AI authority | AI could improve execution | Risk of treating AI as domain expertise/credibility | Explicit iron rule in code/profile: AI execution ≠ domain knowledge, buyer access, legitimacy, trust | AI expands execution but cannot manufacture right-to-win | Profile and strategic acceptance PASS |
| Research Controller | Machine/local evidence plan was close to canonical “next action” | “Best Next Evidence” often meant “more research” | Radar controller explicitly atomic-only; Brain strategic queue may choose RESEARCH, MARKET_ACTION, FOUNDER_DISCOVERY, STOP_OR_PARTNER, HOLD | When buyer behavior is the decisive unknown, market action can outrank desk research | Acceptance: WTP can switch to market action |
| Research State | Initial recommendation could depend on another endpoint having populated process cache | Cross-request race | Research-state endpoint derives claim states and solo assessment within same request | NOT_REGISTERED can receive deterministic initial next evidence without fetch order dependency | Acceptance checks cache removal / no cross-request dependency |
| Founder homepage | Candidate DecisionQueue V3 overlaid homepage | Candidate was still treated as primary strategic object | Retired legacy DecisionQueue import; Opportunity Radar consumes Brain strategic portfolio | Opportunity Thesis = canonical Founder decision object; Candidate = evidence drill-down | UI source acceptance PASS |
| Thesis detail | No dedicated canonical strategic detail surface | Brain intelligence not fully explorable by Founder | Added `/theses/:id` and ThesisDetail with objective truth, strategic track, addressability, gates, next action | Founder can reason from Thesis → evidence / Candidate | Route and TS syntax acceptance PASS |
| Research Center | Legacy blank research-project CRUD | Disconnected from opportunity/thesis | Replaced with opportunity-bound Research Workspace | Research always has thesis/problem context and authority boundary | UI acceptance PASS |
| Search | Raw corpus search only | Founder could not navigate persistent intelligence | Split SignalForge Intelligence search from Raw Corpus search | ProblemLineage / TransitionLineage / Thesis / Intersection searchable separately from posts/news | UI acceptance PASS |
| System / Runtime | Legacy agent UI and misleading “server up” truth | HTTP alive could hide DB failure | DB readiness tracked; DB-backed SignalForge paths return truthful 503; `/healthz`/`/api/healthz` added; System page shows Radar/Brain/runtime/calibration truth | Fail-visible degraded state; no silent product-truth availability claim | Acceptance: DB failure → 503, healthz exists |
| Validation pre-test | Market experiments existed | Strategic/addressability state could be rewritten after outcome | Freeze thesis ID, strategic track, Zip2 readiness, full Founder addressability, Fast Validation, best next action at registration | Future outcomes can calibrate the model as it actually existed before test | Registry source + no-DB tests |
| Fast calibration | Market-result path existed | Could be confused with general/structural success | Separate Fast Validation calibration domain | Payment/reply/demo outcomes calibrate short-cycle hypotheses only | Calibration split tests PASS |
| Structural / Zip2 calibration | Live calibration remained 0 | No correct longitudinal contract for structural predictions | Added pre-registered structural checkpoint registry, minimum 30-day horizon, evidence refs, immutable completion | Track transition strength, legacy mismatch persistence, buyer formation, incumbent response, wedge expansion/collapse | Structural registry tests PASS |
| Founder Addressability calibration | Not separately measurable | Could never learn whether “this is for Eason” judgments were accurate | Separate calibration domain requiring pre-test addressability snapshot | Future outcomes may calibrate first-person opportunity judgment | Calibration domain tests PASS |
| Release safety | Working tree contains extensive local history and uncommitted SignalForge code | Blind patching could overwrite newer user work | Hash-verified source contract + complete backup + rollback + hard gates | No source mismatch may be forced through | Installer verifies every target before first write |

---

## 4. Canonical strategic model after R1

```text
WORLD / MARKET SIGNALS
        ↓
Radar evidence + C01–C14 atomic truth
        ↓
Problem / Transition longitudinal intelligence
        ↓
Opportunity Thesis
        ↓
THIRD-PERSON OPPORTUNITY
“Is this objectively an opportunity?”
        ↓
FIRST-PERSON ADDRESSABILITY
“Is this an opportunity Eason can credibly enter now?”
        ↓
┌───────────────────────────┬───────────────────────────┐
│ ZIP2_STRUCTURAL           │ FAST_VALIDATION           │
│ structural window         │ concrete buyer/pain       │
│ legacy mismatch           │ reachable market          │
│ timing / compounding      │ cheap build/falsification │
└───────────────────────────┴───────────────────────────┘
        ↓
BOTH = highest-priority overlap
        ↓
Best Next Evidence / Action
        ↓
RESEARCH | FOUNDER_DISCOVERY | MARKET_ACTION | STOP_OR_PARTNER | HOLD
        ↓
Real outcome
        ↓
Split calibration domains
```

`NEITHER` and an empty Founder queue are valid outcomes.

---

## 5. Founder Addressability contract

R1 intentionally rejects a single weighted “Founder Fit” score as the sole decision mechanism.

Core dimensions:

- **Task capability** — can the Founder actually execute/evaluate the work?
- **Domain knowledge** — does the Founder understand buyer workflow and failure semantics?
- **Buyer access** — can the Founder reach and learn from the relevant actors?
- **Legitimacy** — is there a credible reason this market would accept the Founder as a provider?
- **Bridgeability** — can missing credibility/knowledge be obtained through a bounded partner, design customer, or learning path?
- **Right-to-win** — is there an actual Founder-specific advantage, not merely global market attractiveness?
- **Trust burden** — how much credential/institutional trust does adoption require?
- **Learning distance** — LOW / MEDIUM / HIGH / PROHIBITIVE-type distance to minimally credible judgment.

**Iron rule:** AI can raise implementation throughput. It cannot itself prove domain expertise, buyer access, legitimacy, regulatory qualification, or trust.

---

## 6. Evidence and authority boundaries

1. **Academic/practitioner frameworks** generate design priors and discovery hypotheses only.
2. **Practitioner quote corpus** must not become C05/C11/WTP support simply because a successful person said something.
3. **Radar C01–C14** remains the sole atomic market-truth owner.
4. **Brain v2** may derive structural/strategic intelligence but cannot silently rewrite atomic truth.
5. **Founder strategy** may reject an objectively strong market as `NOT EASON-ADDRESSABLE NOW` without claiming the market itself is weak.
6. **Research More / Shadow** cannot silently change Published truth.
7. **Market action outcomes** may update calibration only through registered evidence paths.

---

## 7. Calibration contract

### Fast Validation Calibration
Eligible evidence includes bounded outreach, buyer interview, demo, preorder, paid pilot, payment/rejection events tied to a preregistered hypothesis.

### Structural / Zip2 Calibration
Requires a preregistered longitudinal checkpoint with at least a 30-day horizon. It tracks structural direction; a short-term payment does **not** count as Zip2 success.

### Founder Addressability Calibration
Only experiments with a frozen pre-test Founder-addressability snapshot may calibrate whether SignalForge correctly judged Eason's ability to enter.

### Current truth

**Live Market Calibration = 0 / UNVALIDATED.**

R1 improves the ability to collect valid calibration evidence. It does not create market outcomes that do not exist.

---

## 8. Acceptance completed in the release workspace

### Completed

- Python compilation checks on all changed/new Python release files: PASS
- Frontend TS/TSX syntax transpilation on changed/new Founder UI files: PASS
- Full-system no-DB deterministic acceptance: **49 / 49 PASS**
- Explicit assertion that market calibration is not promoted by engineering acceptance

### Required on the user's real environment during installation

The installer treats these as hard gates:

1. `python run_signalforge_full_system_rebase_acceptance.py`
2. `python run_signalforge_brain_v2_acceptance.py --static-only`
3. `npm run build` in `dashboard/`

If any hard gate fails, the installer rolls back the release files to the pre-install snapshot.

### Still pending by truth, not by convenience

- Live PostgreSQL-backed Founder Product Acceptance: **PENDING**, because the supplied runtime snapshot showed the production database connection refused.
- Real Founder use after DB/runtime restoration: **PENDING**.
- Real market validation outcomes: **0 / UNVALIDATED**.
- Predictive accuracy claim: **NOT PERMITTED**.

---

## 9. Product acceptance path after runtime restoration

```text
Founder Dashboard
→ strategic portfolio (BOTH / ZIP2 / FAST / NEITHER)
→ open a real Opportunity Thesis
→ inspect objective market truth
→ inspect Eason addressability + hard blockers
→ inspect supporting Candidate/evidence drill-down
→ inspect Best Next Evidence / Action
→ if RESEARCH: opportunity-bound Research Workspace
→ if MARKET_ACTION: preregister bounded market test
→ execute real action
→ record outcome
→ verify Published truth authority remains intact
→ update only the appropriate calibration domain
```

Candidate 253 remains a useful regression case, but it is **not** the scope of this release.

---

## 10. Non-claims

R1 does **not** claim:

- SignalForge has found a profitable opportunity.
- SignalForge is 80%+ accurate.
- Brain semantic agreement is market predictive accuracy.
- A short paid test proves Zip2-class structural prediction.
- AI makes Eason credible in any domain.
- A healthy HTTP server means the production database and market truth are healthy.
- Engineering PASS equals Product Acceptance or Market Validation.

---

## 11. Next phase after successful installation

Do **not** open another generic intelligence wave.

1. Restore production database/runtime availability.
2. Run the installer hard gates.
3. Run one real Founder Product Acceptance path.
4. Begin persistent Founder use of Thesis-first workflow.
5. Register and execute real market actions when the action queue says market evidence has higher VOI than more desk research.
6. Record outcomes without hindsight rewriting.
7. Allow calibration to move above zero only when real eligible evidence exists.
