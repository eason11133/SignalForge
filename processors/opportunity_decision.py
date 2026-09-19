"""Radar Opportunity Decision V2 — fast signal, slow commitment.

Decision meaning:
- WATCH: surface early, keep machine research running.
- INVESTIGATE: worth allocating focused research now.
- VALIDATE: evidence is strong enough to justify a real customer test.
- PARK / IGNORE: do not spend current attention.
- BUILD remains locked until all hard build gates are production-ready.

Attention score is never an opportunity score and never overrides a blocker.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
import time

from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
)
from processors.opportunity_reality import (
    run_opportunity_reality,
    read_persisted_opportunity_reality,
)
from processors.company_reality import run_company_reality
from processors.commercial_reality import run_commercial_reality
from processors.floor60_reality import run_floor60_reality
from processors.case_progression import attach_progression_packets
from processors.solo_transition_opportunity import assess_solo_transition
from processors import signalforge_runtime_progress as runtime_progress

ENGINE_VERSION = "opportunity-decision-r5-scoped-persisted-reduction"

BUILD_LOCKED = True


def _state(claims: dict[str, RadarClaim], code: str) -> str:
    claim = claims.get(code)
    return str(claim.state if claim else "UNKNOWN").upper()


def _claim_research_status(
    claims: dict[str, RadarClaim],
    code: str,
) -> str:
    claim = claims.get(code)
    if claim is None:
        return ""
    summary = dict(claim.evidence_summary or {})
    if code == "C05":
        block = summary.get("buyer_research_status_v1")
    elif code == "C06":
        block = summary.get("solution_research_status_v1")
    elif code == "C07":
        block = summary.get("gap_research_status_v1")
    elif code in {"C08", "C10", "C11", "C12", "C13", "C14"}:
        block = (
            summary.get("parallel_reality_v2")
            or summary.get("parallel_reality_v1")
        )
    else:
        block = None

    if isinstance(block, dict):
        return str(block.get("status") or "").upper()
    return ""


def _claim_snapshot(claims: dict[str, RadarClaim]) -> dict[str, str]:
    return {
        code: str(claim.state or "UNKNOWN").upper()
        for code, claim in claims.items()
    }


def _real_buyer_organizations(att: dict[str, Any]) -> list[str]:
    out = []
    seen = set()
    for raw in att.get("buyer_companies", []) or []:
        name = str(raw or "").strip()
        key = name.lower()
        if key in {
            "", "unknown", "none", "jobs",
            "prelinked buyer signal", "buyer signal",
        }:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _blocking_refutes(claims: dict[str, RadarClaim]) -> list[str]:
    return sorted(
        code
        for code, claim in claims.items()
        if claim.is_blocking and str(claim.state).upper() == "REFUTED"
    )


def _next_gate(claims: dict[str, RadarClaim]) -> tuple[str, str]:
    order = [
        ("C03", "PAIN_MATERIALITY"),
        ("C05", "BUYER_REALITY"),
        ("C06", "CURRENT_SOLUTION"),
        ("C07", "UNRESOLVED_GAP"),
        ("C09", "COMPANY_REALITY"),
        ("C08", "DIFFERENTIATION"),
        ("C10", "DISTRIBUTION"),
        ("C11", "ECONOMICS"),
        ("C12", "OPPORTUNITY_WINDOW"),
        ("C13", "COMPETITION"),
        ("C14", "SWITCHING"),
    ]
    for code, gate in order:
        if _state(claims, code) not in {"SUPPORTED", "REFUTED"}:
            return gate, code
    return "DECISION_READY", ""


def _decide(
    claims: dict[str, RadarClaim],
    *,
    attention: int,
    coverage: str,
    market_signal: bool,
    buyer_signal: bool,
    solution_signal: bool,
    timing_signal: bool,
    company_fit: str,
) -> tuple[str, str]:
    c01 = _state(claims, "C01")
    c03 = _state(claims, "C03")
    c05 = _state(claims, "C05")
    c06 = _state(claims, "C06")
    c07 = _state(claims, "C07")
    c09 = _state(claims, "C09")

    blockers = _blocking_refutes(claims)

    if c01 == "REFUTED":
        return "IGNORE", "PROBLEM_REALITY_REFUTED"

    if blockers:
        return "PARK", "BLOCKING_CLAIM_REFUTED:" + ",".join(blockers)

    if company_fit == "UNKNOWN" and c09 == "REFUTED":
        return "PARK", "COMPANY_HARD_BLOCKER"

    buyer_research_status = _claim_research_status(
        claims,
        "C05",
    )
    if (
        c05 != "SUPPORTED"
        and buyer_research_status == "SOURCE_SET_EXHAUSTED"
    ):
        return "WATCH", "BUYER_SOURCE_SET_EXHAUSTED"

    solution_research_status = _claim_research_status(
        claims,
        "C06",
    )
    if (
        c06 != "SUPPORTED"
        and solution_research_status == "SOURCE_SET_EXHAUSTED"
    ):
        return "WATCH", "SOLUTION_SOURCE_SET_EXHAUSTED"

    gap_research_status = _claim_research_status(
        claims,
        "C07",
    )
    if (
        c07 != "SUPPORTED"
        and gap_research_status == "SOURCE_SET_EXHAUSTED"
    ):
        return "WATCH", "GAP_SOURCE_SET_EXHAUSTED"

    # VALIDATE means "run a customer validation experiment", not build.
    # Machine-resolvable reality gates C05/C06/C07 must be complete first.
    # Commercial uncertainty can still remain for the validation experiment.
    validation_ready = (
        c03 == "SUPPORTED"
        and c09 == "SUPPORTED"
        and c05 == "SUPPORTED"
        and c06 == "SUPPORTED"
        and c07 == "SUPPORTED"
        and market_signal
        and attention >= 60
    )
    if validation_ready:
        return "VALIDATE", "REALITY_STRONG_ENOUGH_FOR_CUSTOMER_TEST"

    # Fast INVESTIGATE lane:
    # A fresh/market-linked material problem that we can plausibly execute
    # should get focused research attention before recurrence/commercial
    # certainty is complete.
    investigate_ready = (
        c03 == "SUPPORTED"
        and company_fit in {"CAN_DO", "CAN_ACQUIRE"}
        and market_signal
        and attention >= 58
        and (
            coverage == "SATURATED"
            or (buyer_signal and timing_signal)
            or (solution_signal and timing_signal)
        )
    )
    if investigate_ready:
        return "INVESTIGATE", "MATERIAL_MARKET_LINKED_FAST_LANE"

    return "WATCH", "EARLY_SIGNAL_NOT_YET_INVESTIGATE"


def _machine_action(next_gate: str) -> str:
    return {
        "PAIN_MATERIALITY": "find direct cost/blocking consequence evidence",
        "BUYER_REALITY": "find a named buyer that owns or budgets for this exact job",
        "BUYER_REALITY_RECHECK": "wait for new buyer sources/fresh evidence, then recheck C05",
        "CURRENT_SOLUTION": "search solution complaints, failures, and workarounds",
        "CURRENT_SOLUTION_RECHECK": "wait for fresh solution evidence/source coverage, then recheck C06",
        "UNRESOLVED_GAP": "verify the gap persists despite current solutions",
        "UNRESOLVED_GAP_RECHECK": "wait for fresh persistence evidence/source coverage, then recheck C07",
        "COMPANY_REALITY": "resolve missing execution capability evidence",
        "DIFFERENTIATION": "form and falsify a concrete differentiation wedge",
        "DISTRIBUTION": "identify and test a credible customer-acquisition channel",
        "ECONOMICS": "estimate price/WTP, build cost, support cost, and gross margin",
        "OPPORTUNITY_WINDOW": "estimate execution time against the opportunity window",
        "COMPETITION": "search counterevidence and competitive responses",
        "SWITCHING": "test whether users will switch/adopt/pay",
        "ATOMIZE_PROBLEM": "split the theme into a concrete actor + workflow + failure; do not invent a product",
        "EXACT_BUYER_AND_ECONOMIC_OWNER": "find the exact buyer who owns this workflow and the observed cost of the current failure",
        "TRANSITION_ADOPTION_GAP": "find evidence of what changed and the old/manual workflow that has not caught up",
        "ECONOMIC_NECESSITY": "find observed time, labor, revenue, or existing-spend evidence; do not infer willingness to pay",
        "SOLO_CAPTUREABILITY": "resolve whether one founder can build, sell, test, and operate the first version without frontier expertise or large capital",
        "OPPORTUNITY_STRUCTURE": "verify the candidate satisfies its evidence-defined opportunity class without inventing missing facts",
        "RECURRENCE": "find independent recurrence evidence for this concrete friction/workaround",
        "SOLO_OPPORTUNITY_READY": "prepare Founder discussion from the evidence-backed opportunity",
        "DECISION_READY": "prepare final build gate",
    }.get(next_gate, "continue automated evidence research")


async def run_opportunity_decision(
    limit: int = 10,
    *,
    reality_mode: str = "materialize",
    case_ids: list[int] | None = None,
    emit_runtime_progress: bool = False,
) -> dict[str, Any]:
    total_t0 = time.perf_counter()
    phase_ms: dict[str, int] = {}
    mode = str(reality_mode or "materialize").lower()
    if mode not in {"materialize", "persisted"}:
        raise ValueError(f"unsupported reality_mode={reality_mode!r}")
    scope_explicit = case_ids is not None
    scope_ids = sorted({int(x) for x in (case_ids or []) if int(x) > 0})
    scope_set = set(scope_ids)

    def _emit(detail: str, current: int = 0, total: int | None = None) -> None:
        if not emit_runtime_progress:
            return
        runtime_progress.update(
            "round_final_decision",
            detail=detail,
            progress={
                "current": max(0, int(current)),
                "total": max(0, int(total if total is not None else len(scope_ids))),
                "unit": "cases",
            },
            complete_previous=False,
        )

    _emit("decision reality projection", 0)
    t0 = time.perf_counter()
    materialized_scope: dict[str, Any] | None = None
    if mode == "persisted":
        reality = await read_persisted_opportunity_reality()
    elif scope_explicit:
        # R6: source/candidate changes no longer force a full-world fuzzy
        # materialization. Refresh only the explicit decision scope, then
        # rebuild the full read-only attention projection from persisted truth.
        scoped_materialization = await run_opportunity_reality(case_ids=scope_ids if scope_explicit else None)
        materialized_scope = dict(scoped_materialization.get("materialization_scope") or {})
        reality = await read_persisted_opportunity_reality()
        reality = dict(reality)
        reality["evidence_created"] = int(scoped_materialization.get("evidence_created", 0) or 0)
        reality["claim_links_created"] = int(scoped_materialization.get("claim_links_created", 0) or 0)
        reality["materialization_scope"] = materialized_scope
    else:
        reality = await run_opportunity_reality()
        materialized_scope = dict(reality.get("materialization_scope") or {})
    phase_ms["opportunity_reality"] = round((time.perf_counter() - t0) * 1000)
    _emit("company reality reduction", 1 if scope_ids else 0)
    t0 = time.perf_counter()
    company = await run_company_reality(case_ids=scope_ids if scope_explicit else None)
    phase_ms["company_reality"] = round((time.perf_counter() - t0) * 1000)
    _emit("commercial reality reduction", 2 if scope_ids else 0)
    t0 = time.perf_counter()
    commercial = await run_commercial_reality(case_ids=scope_ids if scope_explicit else None)
    phase_ms["commercial_reality"] = round((time.perf_counter() - t0) * 1000)
    _emit("floor60 reality reduction", 3 if scope_ids else 0)
    t0 = time.perf_counter()
    floor60 = await run_floor60_reality(case_ids=scope_ids if scope_explicit else None)
    phase_ms["floor60_reality"] = round((time.perf_counter() - t0) * 1000)

    attention_by_case = {
        int(row["case_id"]): row for row in reality["attention"]
    }

    db_t0 = time.perf_counter()
    async with async_session() as session:
        pairs = list(
            (
                await session.execute(
                    select(RadarCase, ProblemCandidate)
                    .join(
                        ProblemCandidate,
                        ProblemCandidate.id == RadarCase.candidate_id,
                    )
                    .order_by(RadarCase.id)
                )
            ).all()
        )
        claim_rows = list(
            (
                await session.execute(
                    select(RadarClaim).where(
                        RadarClaim.case_id.in_(
                            [case.id for case, _ in pairs]
                        )
                    )
                )
            ).scalars().all()
        )

        claims_by_case: dict[int, dict[str, RadarClaim]] = defaultdict(dict)
        for claim in claim_rows:
            claims_by_case[claim.case_id][claim.claim_code] = claim

        phase_ms["decision_db_load"] = round((time.perf_counter() - db_t0) * 1000)
        _emit("scoped decision projection", 0)
        loop_t0 = time.perf_counter()
        rows = []
        verdict_counts: dict[str, int] = defaultdict(int)
        scoped_done = 0
        scoped_total = len(scope_ids) if scope_explicit else len(pairs)

        for case, candidate in pairs:
            claims = claims_by_case.get(case.id, {})
            att = attention_by_case.get(case.id, {})
            comp = company["results"].get(case.id, {})
            commerce = commercial["results"].get(case.id, {})
            floor = floor60["results"].get(case.id, {})

            attention = int(att.get("attention_score", 0))
            coverage = str(att.get("coverage", "UNKNOWN")).upper()

            buyer_organizations = _real_buyer_organizations(att)
            buyer_signal = bool(buyer_organizations)
            solution_signal = bool(
                att.get("solution_issues", 0)
                or att.get("solution_supply", 0)
            )
            timing_signal = bool(att.get("timing_signals", 0))
            market_signal = buyer_signal or solution_signal or timing_signal
            company_fit = str(comp.get("overall", "UNKNOWN")).upper()
            fresh_claims = _claim_snapshot(claims)

            scoped_execution = (not scope_explicit) or int(case.id) in scope_set
            if scoped_execution:
                verdict, reason = _decide(
                    claims,
                    attention=attention,
                    coverage=coverage,
                    market_signal=market_signal,
                    buyer_signal=buyer_signal,
                    solution_signal=solution_signal,
                    timing_signal=timing_signal,
                    company_fit=company_fit,
                )
            else:
                # Incremental final-decision projection: untouched cases preserve
                # their durable RadarCase disposition. Fresh claim truth is still
                # surfaced, but no Company/Commercial reducers or case mutation
                # run outside the decision scope.
                verdict = str(case.system_verdict or "WATCH").upper()
                reason = str(case.verdict_reason_code or "PERSISTED_UNSCOPED_DECISION")

            if scoped_execution:
                solo_transition = assess_solo_transition(
                    candidate,
                    claim_states=fresh_claims,
                    company_reality=comp,
                    commercial_reality=commerce,
                    attention=att,
                )
                solo_transition = dict(solo_transition or {})
            else:
                # Brain v2 owns structural strategy. Re-running the legacy
                # compatibility classifier for every untouched case made a
                # scoped decision rebuild behave like a full-world reduction.
                solo_transition = {
                    "classification": "PERSISTED_UNSCOPED_COMPATIBILITY",
                    "founder_surface_eligible": False,
                    "scope_recomputed": False,
                }
            # SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_AUTHORITY_CUTOVER_R1
            # Legacy solo-transition output remains compatibility context only. It may not
            # override Radar atomic-truth disposition, next gate, ranking, or why-now.
            solo_transition["decision_authority"] = False
            solo_transition["authority"] = "LEGACY_CONTEXT_ONLY_NO_DECISION_AUTHORITY"
            solo_transition["structural_authority"] = "BRAIN_V2_DERIVED_PORTFOLIO"

            derived_gate, derived_claim = _next_gate(claims)
            next_gate = derived_gate if scoped_execution else str(case.current_gate or derived_gate)
            next_claim = derived_claim
            if reason == "BUYER_SOURCE_SET_EXHAUSTED" and next_gate not in {"ATOMIZE_PROBLEM", "EXACT_BUYER_AND_ECONOMIC_OWNER", "TRANSITION_ADOPTION_GAP", "ECONOMIC_NECESSITY", "SOLO_CAPTUREABILITY"}:
                next_gate = "BUYER_REALITY_RECHECK"
                next_claim = "C05"
            elif reason == "SOLUTION_SOURCE_SET_EXHAUSTED" and next_gate not in {"ATOMIZE_PROBLEM", "EXACT_BUYER_AND_ECONOMIC_OWNER", "TRANSITION_ADOPTION_GAP", "ECONOMIC_NECESSITY", "SOLO_CAPTUREABILITY"}:
                next_gate = "CURRENT_SOLUTION_RECHECK"
                next_claim = "C06"
            elif reason == "GAP_SOURCE_SET_EXHAUSTED" and next_gate not in {"ATOMIZE_PROBLEM", "EXACT_BUYER_AND_ECONOMIC_OWNER", "TRANSITION_ADOPTION_GAP", "ECONOMIC_NECESSITY", "SOLO_CAPTUREABILITY"}:
                next_gate = "UNRESOLVED_GAP_RECHECK"
                next_claim = "C07"

            if scoped_execution:
                case.system_verdict = verdict
                case.verdict_reason_code = reason
                case.current_gate = next_gate
                case.last_evaluated_at = datetime.utcnow()

            verdict_counts[verdict] += 1

            why_now = []
            if buyer_signal:
                why_now.append("named buyer/budget signal")
            if solution_signal:
                why_now.append("solution-market signal")
            if timing_signal:
                why_now.append(
                    f"{int(att.get('timing_signals', 0))} timing signals"
                )
            if coverage == "SATURATED":
                why_now.append("problem-search coverage saturated")

            unresolved = [
                code
                for code in (
                    "C03", "C05", "C06", "C07", "C09",
                    "C08", "C10", "C11", "C12", "C13", "C14",
                )
                if _state(claims, code) not in {"SUPPORTED", "REFUTED"}
            ]

            prepared_plans = dict(
                commerce.get("validation_plans", {}) or {}
            )
            prepared_claims = list(
                commerce.get("validation_ready_claims", []) or []
            )

            founder_action = "NONE"
            if verdict == "VALIDATE":
                founder_action = (
                    "RUN_PREPARED_MARKET_VALIDATION"
                    if prepared_plans
                    else "RUN_CUSTOMER_VALIDATION"
                )
            elif verdict == "INVESTIGATE":
                founder_action = "NONE_MACHINE_RESEARCH_FIRST"

            rows.append(
                {
                    **att,
                    "claims": fresh_claims,
                    "buyer_organizations": buyer_organizations,
                    "case_id": case.id,
                    "candidate_id": candidate.id,
                    "title": candidate.title,
                    "decision_verdict": verdict,
                    "decision_reason": reason,
                    "current_gate": next_gate,
                    "next_claim": next_claim,
                    "machine_action": _machine_action(next_gate),
                    "why_now": why_now,
                    "unresolved_claims": unresolved,
                    "company_reality": comp,
                    "solo_transition": solo_transition,
                    "commercial_reality": commerce,
                    "floor60_reality": floor,
                    "prepared_validation_plans": prepared_plans,
                    "prepared_validation_claims": prepared_claims,
                    "market_validation_boundary": (
                        "FOUNDER_ACTION_NOW"
                        if verdict == "VALIDATE"
                        else (
                            "PREBUILT_WAITING_FOR_VALIDATE"
                            if prepared_plans
                            else "MACHINE_RESEARCH_FIRST"
                        )
                    ),
                    "founder_action": founder_action,
                    "decision_scope_applied": bool(scope_explicit),
                    "decision_scope_member": bool(scoped_execution),
                }
            )
            if scoped_execution:
                scoped_done += 1
                if emit_runtime_progress and (scoped_done == scoped_total or scoped_done % 4 == 0):
                    _emit("scoped decision projection", scoped_done, scoped_total)

        phase_ms["decision_loop"] = round((time.perf_counter() - loop_t0) * 1000)
        commit_t0 = time.perf_counter()
        await session.commit()
        phase_ms["decision_commit"] = round((time.perf_counter() - commit_t0) * 1000)

    order = {
        "VALIDATE": 0,
        "INVESTIGATE": 1,
        "WATCH": 2,
        "PARK": 3,
        "IGNORE": 4,
    }
    rows.sort(
        key=lambda row: (
            order.get(row["decision_verdict"], 9),
            -int(row.get("attention_score", 0)),
            row.get("title") or "",
        )
    )

    _emit("progression projection", len(scope_ids) if scope_explicit else len(rows), len(scope_ids) if scope_explicit else len(rows))
    progression_t0 = time.perf_counter()
    attach_progression_packets(rows)
    phase_ms["progression"] = round((time.perf_counter() - progression_t0) * 1000)
    phase_ms["total"] = round((time.perf_counter() - total_t0) * 1000)

    return {
        "engine_version": ENGINE_VERSION,
        "reality_mode": mode,
        "decision_scope": {
            "mode": ("FULL" if not scope_explicit else ("SCOPED_INCREMENTAL" if scope_ids else "EXPLICIT_ZERO")),
            "case_ids": scope_ids,
            "scoped_case_count": len(scope_ids),
            "total_case_count": len(rows),
            "unscoped_case_mutations": 0,
            "materialization_scope": materialized_scope or {},
            "truth_boundary": "UNSCOPED_CASES_PRESERVE_DURABLE_DISPOSITION_AND_ARE_NOT_REDUCED_OR_MUTATED",
        },
        "phase_ms": phase_ms,
        "reality": reality,
        "company": company,
        "commercial": commercial,
        "floor60": floor60,
        "verdict_counts": dict(verdict_counts),
        "research_theme_count": sum(1 for row in rows if (row.get("solo_transition") or {}).get("classification") == "RESEARCH_THEME"),
        "solo_watch_count": sum(1 for row in rows if (row.get("solo_transition") or {}).get("classification") == "SOLO_WATCH"),
        "solo_ready_count": sum(1 for row in rows if (row.get("solo_transition") or {}).get("founder_surface_eligible")),
        "rows": rows,
        "top": rows[:limit],
        "build_locked": BUILD_LOCKED,
        "llm_calls": 0,
        "api_calls": 0,
    }


async def print_founder_daily_v5(limit: int = 10) -> dict[str, Any]:
    result = await run_opportunity_decision(limit=limit)
    reality = result["reality"]
    company = result["company"]

    print("\n" + "=" * 118)
    print("FOUNDER DAILY RADAR V6 — FRESH CLAIM TRUTH → DECISION")
    print("=" * 118)
    print("Early signals move fast. Expensive commitments move through hard gates.")
    print(f"Cases:                    {reality['cases']}")
    print(
        f"Market-linked:            "
        f"{reality['cases_with_market_signal']}/{reality['cases']}"
    )
    print(
        "Buyer / solution / timing: "
        f"{reality['cases_with_buyer_signal']} / "
        f"{reality['cases_with_solution_signal']} / "
        f"{reality['cases_with_timing_signal']}"
    )
    print(
        "Company reality:           "
        + " | ".join(
            f"{k}={v}" for k, v in sorted(company["counts"].items())
        )
    )
    print(
        "C09 claim sync:            "
        f"SUPPORTED={company['claim_sync_supported']} | "
        f"INSUFFICIENT={company['claim_sync_insufficient']}"
    )
    commercial_state_counts = {}
    for row in result["rows"]:
        claims = row.get("claims", {})
        for code in ("C08", "C10", "C11", "C13", "C14"):
            state = str(claims.get(code, "UNKNOWN")).upper()
            commercial_state_counts[(code, state)] = (
                commercial_state_counts.get((code, state), 0) + 1
            )

    print(
        "Decision lanes:            "
        + " | ".join(
            f"{k}={v}" for k, v in sorted(result["verdict_counts"].items())
        )
    )
    print(
        "Commercial truth:          "
        + " | ".join(
            f"{code}:{state}={count}"
            for (code, state), count in sorted(commercial_state_counts.items())
            if state != "UNKNOWN"
        )
    )
    print("BUILD:                     LOCKED")
    print("LLM/API calls:             0 / 0")
    print("AI cost:                   NT$0.00")

    for i, row in enumerate(result["top"], 1):
        claims = row.get("claims", {})
        comp = row.get("company_reality", {})
        commerce = row.get("commercial_reality", {})

        print("\n" + "-" * 118)
        print(
            f"#{i:02d} [{row['decision_verdict']}] "
            f"attention={int(row.get('attention_score', 0)):3d} "
            f"coverage={row.get('coverage', 'UNKNOWN')} "
            f"gate={row['current_gate']}"
        )
        print(row.get("title") or "")

        if row.get("problem_statement"):
            print("Problem:", str(row["problem_statement"])[:360])

        print(
            "Core reality: "
            f"pain={claims.get('C03', 'UNKNOWN')} | "
            f"buyer={claims.get('C05', 'UNKNOWN')} | "
            f"solution={claims.get('C06', 'UNKNOWN')} | "
            f"gap={claims.get('C07', 'UNKNOWN')} | "
            f"company={claims.get('C09', 'UNKNOWN')} | "
            f"window={claims.get('C12', 'UNKNOWN')}"
        )

        print(
            "Commercial: "
            f"diff={claims.get('C08', 'UNKNOWN')} | "
            f"distribution={claims.get('C10', 'UNKNOWN')} | "
            f"economics={claims.get('C11', 'UNKNOWN')} | "
            f"competition={claims.get('C13', 'UNKNOWN')} | "
            f"switching={claims.get('C14', 'UNKNOWN')}"
        )

        print(
            "Company fit:",
            comp.get("overall", "UNKNOWN"),
            "| required=" + ",".join(comp.get("required", [])),
        )

        if commerce.get("wedge_hypothesis"):
            print("Wedge hypothesis:", commerce["wedge_hypothesis"])
        print(
            "Reachable channels:",
            ", ".join(commerce.get("reachable_channels", [])) or "not proven",
        )
        print(
            "Competition context:",
            commerce.get("competition", "UNKNOWN"),
            f"| observed supply={commerce.get('solution_supply', 0)}",
        )

        buyers = list(row.get("buyer_organizations", []) or [])
        print(
            "Buyer organizations:",
            ", ".join(buyers[:5]) or "not yet directly established",
        )
        print(
            "Why now:",
            ", ".join(row.get("why_now", [])) or "problem signal only",
        )
        print("Decision reason:", row["decision_reason"])
        print("Next machine gate:", row["current_gate"])
        print("Machine action:", row["machine_action"])
        print("Founder action:", row["founder_action"])

    print("\n" + "=" * 118)
    print("Safety:")
    print("  Attention cannot override a blocking claim.")
    print("  INVESTIGATE means focused research, not product commitment.")
    print("  VALIDATE means run a customer test, not BUILD.")
    print("  BUILD remains locked until remaining hard gates are production-ready.")
    print("=" * 118)

    return result
