
"""Radar V4.0 Evidence-Governed Foundation.

No LLM calls. This migrates the current ProblemCandidate/CandidateEvidence layer
into a conservative case/claim/evidence ledger without deleting legacy data.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select

from processors.signalforge_production_admission import assess_candidate_admission

from database.connection import (
    async_session, ProblemCandidate, CandidateEvidence,
    RadarCase, RadarClaim, RadarEvidence, RadarClaimEvidence,
    RadarAssumption, RadarUnknown, RadarDecisionEvent,
)

ENGINE_VERSION = "radar-v4.1-ledger-admission-aware"

CLAIMS = [
    ("C01","problem_exists","PROBLEM_REALITY",True,1,1.00,"Does the described problem actually exist in real-world evidence?","existing_evidence_then_local_search","EPISTEMIC"),
    ("C02","problem_recurs","PROBLEM_REALITY",True,2,1.00,"Does the same or equivalent problem recur across independent users or discussions?","local_search_then_ai_fallback","EPISTEMIC"),
    ("C03","consequence_material","PROBLEM_REALITY",False,2,0.90,"Is the consequence materially painful or costly rather than merely annoying?","first_party_evidence_then_human_validation","EPISTEMIC"),
    ("C04","target_user_identifiable","PROBLEM_REALITY",False,1,0.75,"Can the affected user or user group be identified concretely?","existing_evidence_then_local_search","EPISTEMIC"),
    ("C05","buyer_exists","MARKET_REALITY",True,2,0.95,"Is there a plausible named economic buyer that owns or budgets for solving this exact job?","market_evidence_then_human_validation","EPISTEMIC"),
    ("C06","current_solution_unsatisfactory","SOLUTION_REALITY",True,2,0.95,"Are current solutions or workarounds demonstrably unsatisfactory?","solution_reviews_workarounds_complaints","EPISTEMIC"),
    ("C07","unresolved_gap_exists","SOLUTION_REALITY",True,2,1.00,"Does a specific unresolved gap remain after accounting for existing solutions?","solution_landscape_plus_counterevidence","EPISTEMIC"),
    ("C08","differentiation_possible","SOLUTION_REALITY",True,2,0.90,"Is there a meaningful differentiation wedge rather than a clone?","solution_landscape_plus_gap_analysis","EPISTEMIC"),
    ("C09","company_can_execute","COMPANY_REALITY",True,1,1.00,"Can the current company execute, acquire the missing capability, or avoid hard blockers?","company_capability_profile","EPISTEMIC"),
    ("C10","distribution_feasible","DISTRIBUTION_REALITY",True,2,1.00,"Is there a credible path to reach and acquire the target customers?","channel_research_then_human_validation","EPISTEMIC"),
    ("C11","economics_plausible","BUILD_REALITY",True,2,0.90,"Are build, support, maintenance and likely pricing economics plausibly viable?","reference_class_plus_cost_model","EPISTEMIC"),
    ("C12","window_outlasts_execution","RACE_DURABILITY",True,2,1.00,"Is the unresolved opportunity window likely to outlast time-to-customer-satisfaction?","temporal_signals_plus_scenario_watch","FUTURE_UNCERTAINTY"),
    ("C13","competition_survivable","RACE_DURABILITY",True,2,0.95,"Can the opportunity survive incumbent, startup, open-source and platform competition?","competitive_events_plus_counterevidence","FUTURE_UNCERTAINTY"),
    ("C14","customer_switch_plausible","VALIDATION",True,2,1.00,"Is there evidence customers would switch, adopt, or pay rather than merely complain?","human_validation","EPISTEMIC"),
]

UNCLEAR = {"","unclear","unknown","none","not specified","none mentioned","specific user/group or unclear"}

def clean(x: Any) -> str:
    return str(x or "").strip()

def useful(x: Any) -> bool:
    return clean(x).lower() not in UNCLEAR

def norm_url(url: str | None) -> str:
    raw = clean(url)
    if not raw:
        return ""
    try:
        p = urlsplit(raw)
        return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", ""))
    except Exception:
        return raw

def parse_dt(x: Any):
    raw = clean(x)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z","+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def digest(*parts: Any) -> str:
    return hashlib.sha256("\n".join(clean(x) for x in parts).encode("utf-8", errors="ignore")).hexdigest()

def family(e: CandidateEvidence) -> str:
    meta = e.evidence_metadata or {}
    discussion = clean(meta.get("discussion_key"))
    if discussion:
        return f"discussion:{discussion}"
    if clean(e.source_ref):
        return f"{clean(e.source_type)}:ref:{clean(e.source_ref)}"
    if norm_url(e.url):
        return f"{clean(e.source_type)}:url:{norm_url(e.url)}"
    return f"{clean(e.source_type)}:hash:{digest(e.title,e.excerpt)[:24]}"

def directness(rel: str) -> str:
    return "DIRECT" if rel in {"community_problem","direct_problem_corroboration"} else ("INDIRECT" if rel=="buyer_demand" else "RELATED")

def authority(rel: str) -> str:
    return {
        "community_problem":"USER_DISCUSSION",
        "direct_problem_corroboration":"INDEPENDENT_PROBLEM_SOURCE",
        "buyer_demand":"MARKET_ACTIVITY",
        "solution_supply":"SOLUTION_SOURCE",
        "competitor":"SOLUTION_SOURCE",
    }.get(rel,"CONTEXT_SOURCE")

def initial_links(c: ProblemCandidate, e: CandidateEvidence):
    rel = clean(e.relation)
    out = []
    if rel == "community_problem":
        out.append(("C01","SUPPORT","Raw community problem evidence exists."))
        if useful(c.actor):
            out.append(("C04","SUPPORT","Existing problem evidence identifies an affected actor."))
        if useful(c.consequence):
            out.append(("C03","INSUFFICIENT","A consequence is present, but one source does not establish material severity."))
        if useful(c.workaround):
            out.append(("C06","INSUFFICIENT","A workaround exists, but this alone does not prove current solutions are unsatisfactory."))
    elif rel == "direct_problem_corroboration":
        out.append(("C02","SUPPORT" if e.verified else "INSUFFICIENT","Existing external evidence was classified as direct problem corroboration."))
    elif rel == "buyer_demand":
        out.append(("C05","INSUFFICIENT","Buyer/market activity is relevant but does not prove willingness to buy this exact solution."))
    elif rel in {"solution_supply","competitor"}:
        out.append(("C06","RELATED","Solution activity maps the landscape; it does not prove dissatisfaction."))
        out.append(("C07","INSUFFICIENT","Solution activity exists; an unresolved gap still requires direct evidence."))
    elif rel in {"why_now","research_enabler","ecosystem_activity"}:
        out.append(("C12","INSUFFICIENT","Timing/context exists but does not establish opportunity-window durability."))
    return out

async def one(session, stmt):
    return (await session.execute(stmt)).scalar_one_or_none()

def evaluate(code: str, required: int, pairs):
    supports = {ev.source_family_key for link,ev in pairs if link.validated and link.stance=="SUPPORT"}
    direct_supports = {ev.source_family_key for link,ev in pairs if link.validated and link.stance=="SUPPORT" and ev.directness=="DIRECT"}
    refutes = {ev.source_family_key for link,ev in pairs if link.validated and link.stance=="REFUTE"}
    weak = sum(1 for link,_ in pairs if link.validated and link.stance in {"INSUFFICIENT","RELATED"})
    support_count = len(direct_supports) if code=="C02" else len(supports)
    required = max(1,int(required or 1))
    if len(refutes)>=required and support_count>=required:
        state="CONFLICTED"
    elif len(refutes)>=required:
        state="REFUTED"
    elif support_count>=required:
        state="SUPPORTED"
    elif support_count or refutes or weak:
        state="INSUFFICIENT"
    else:
        state="UNKNOWN"
    return state, {
        "support_groups":len(supports),
        "direct_support_groups":len(direct_supports),
        "refute_groups":len(refutes),
        "insufficient_or_related":weak,
        "required_support_groups":required,
    }

async def run_radar_ledger(
    *,
    candidate_ids: list[int] | None = None,
    admit_new: bool = True,
    brain_candidate_ids: list[int] | None = None,
):
    """Migrate candidate evidence into Radar truth without forcing every observation into workload.

    Existing RadarCases are always preserved and may be refreshed. When
    ``admit_new`` is true, a new Candidate becomes a RadarCase only when the
    deterministic production-admission layer says it is worth expensive truth
    research. Deferred candidates remain in ProblemCandidate/CandidateEvidence
    provenance and can be admitted later when stronger evidence appears.
    """
    now = datetime.now()
    summary = Counter()
    admission_states = Counter()
    async with async_session() as session:
        stmt = select(ProblemCandidate).order_by(ProblemCandidate.id)
        if candidate_ids is not None:
            wanted = sorted({int(x) for x in candidate_ids if int(x) > 0})
            if not wanted:
                return {
                    "engine_version": ENGINE_VERSION,
                    "llm_calls": 0,
                    "llm_cost_twd": 0.0,
                    "candidates_seen": 0,
                    "candidates_deferred": 0,
                    "admission_states": {},
                    "truth_boundary": "ADMISSION_ONLY_CONTROLS_NEW_CASE_WORKLOAD_NO_C01_C14_THRESHOLD_CHANGE",
                }
            stmt = stmt.where(ProblemCandidate.id.in_(wanted))
        candidates = list((await session.execute(stmt)).scalars().all())

        for c in candidates:
            case = await one(session, select(RadarCase).where(RadarCase.candidate_id==c.id))
            if case is None:
                if not admit_new:
                    summary["candidates_deferred"] += 1
                    admission_states["NEW_CASE_CREATION_DISABLED"] += 1
                    continue
                admission = assess_candidate_admission(c, brain_candidate_ids=brain_candidate_ids or [])
                admission_states[admission["state"]] += 1
                if not admission.get("ledger_admit_new"):
                    summary["candidates_deferred"] += 1
                    continue
                case = RadarCase(candidate_id=c.id, case_key=f"candidate:{c.canonical_key}", legacy_stage=c.stage,
                                 system_verdict="WATCH", research_state="ACTIVE", current_gate="PROBLEM_REALITY")
                session.add(case); await session.flush(); summary["cases_created"] += 1
            else:
                case.legacy_stage = c.stage; summary["cases_reused"] += 1

            claim_map = {}
            for code,ctype,gate,blocking,required,impact,question,method,utype in CLAIMS:
                claim = await one(session, select(RadarClaim).where(RadarClaim.case_id==case.id, RadarClaim.claim_code==code))
                if claim is None:
                    claim = RadarClaim(case_id=case.id, claim_code=code, claim_type=ctype, gate_group=gate,
                                       statement=f"{ctype}: {question}", state="UNKNOWN", is_blocking=blocking,
                                       required_support_groups=required)
                    session.add(claim); await session.flush(); summary["claims_created"] += 1
                claim_map[code] = claim

            current_evidence = list((await session.execute(
                select(CandidateEvidence).where(CandidateEvidence.candidate_id==c.id)
            )).scalars().all())

            for ce in current_evidence:
                ev_key = f"candidate:{c.id}:evidence:{ce.id}"
                lev = await one(session, select(RadarEvidence).where(RadarEvidence.evidence_key==ev_key))
                if lev is None:
                    meta = ce.evidence_metadata or {}
                    lev = RadarEvidence(
                        case_id=case.id, candidate_evidence_id=ce.id, evidence_key=ev_key,
                        source_type=clean(ce.source_type) or "unknown", source_table=clean(ce.source_table) or None,
                        source_ref=clean(ce.source_ref) or None, source_url=norm_url(ce.url) or None,
                        source_title=clean(ce.title) or None, excerpt=clean(ce.excerpt) or None,
                        source_family_key=family(ce), directness=directness(clean(ce.relation)),
                        authority_class=authority(clean(ce.relation)),
                        published_at=parse_dt(meta.get("date") or meta.get("published_at")),
                        freshness_class="UNASSESSED",
                        content_hash=digest(ce.source_type,ce.source_ref,ce.title,ce.excerpt,ce.url),
                        raw_metadata=meta,
                    )
                    session.add(lev); await session.flush(); summary["evidence_created"] += 1
                else:
                    summary["evidence_reused"] += 1

                for code,stance,rationale in initial_links(c,ce):
                    claim = claim_map[code]
                    link = await one(session, select(RadarClaimEvidence).where(
                        RadarClaimEvidence.claim_id==claim.id, RadarClaimEvidence.evidence_id==lev.id
                    ))
                    if link is None:
                        validated = clean(ce.relation)=="community_problem" or bool(ce.verified) or stance in {"INSUFFICIENT","RELATED"}
                        session.add(RadarClaimEvidence(
                            claim_id=claim.id, evidence_id=lev.id, stance=stance,
                            interpretation_method="DETERMINISTIC_MIGRATION", method_version=ENGINE_VERSION,
                            interpretation_confidence=float(ce.verification_confidence) if ce.verification_confidence is not None else None,
                            rationale=rationale, validated=validated,
                        ))
                        summary["claim_links_created"] += 1

            await session.flush()

            for code,ctype,gate,blocking,required,impact,question,method,utype in CLAIMS:
                claim = claim_map[code]
                pairs = list((await session.execute(
                    select(RadarClaimEvidence,RadarEvidence)
                    .join(RadarEvidence,RadarEvidence.id==RadarClaimEvidence.evidence_id)
                    .where(RadarClaimEvidence.claim_id==claim.id)
                )).all())
                state, es = evaluate(code, required, pairs)
                claim.state = state
                claim.support_groups = es["support_groups"]
                claim.direct_support_groups = es["direct_support_groups"]
                claim.refute_groups = es["refute_groups"]
                claim.insufficient_count = es["insufficient_or_related"]
                claim.evidence_summary = es
                claim.last_evaluated_at = now
                summary[f"claim_state_{state.lower()}"] += 1

                u = await one(session, select(RadarUnknown).where(
                    RadarUnknown.case_id==case.id, RadarUnknown.unknown_code==f"U_{code}"
                ))
                ustate = "RESOLVED" if state in {"SUPPORTED","REFUTED"} else "OPEN"
                if u is None:
                    session.add(RadarUnknown(
                        case_id=case.id, claim_id=claim.id, unknown_code=f"U_{code}", question=question,
                        uncertainty_type=utype, state=ustate, decision_impact=impact,
                        reducibility=0.45 if utype=="FUTURE_UNCERTAINTY" else 0.90,
                        recommended_method=method,
                    ))
                    summary["unknowns_created"] += 1
                else:
                    u.claim_id=claim.id; u.question=question; u.state=ustate
                    u.decision_impact=impact; u.recommended_method=method

            if claim_map["C01"].state=="REFUTED":
                verdict,reason="IGNORE","problem_not_supported"
            elif claim_map["C02"].state=="SUPPORTED":
                verdict,reason="INVESTIGATE","problem_reality_passed"
            else:
                verdict,reason="WATCH","problem_recurrence_unproven"

            previous=case.system_verdict
            case.system_verdict=verdict
            case.current_gate="PROBLEM_REALITY"
            case.verdict_reason_code=reason
            case.last_evaluated_at=now

            latest = await one(session, select(RadarDecisionEvent).where(
                RadarDecisionEvent.case_id==case.id
            ).order_by(RadarDecisionEvent.id.desc()).limit(1))
            if latest is None or latest.new_verdict!=verdict or latest.reason_code!=reason:
                session.add(RadarDecisionEvent(
                    case_id=case.id, previous_verdict=previous, new_verdict=verdict, reason_code=reason,
                    reason_text="V4.0 conservative migration. Legacy scores/stages remain context only.",
                    triggering_claim_code="C01" if reason=="problem_not_supported" else "C02",
                    engine_version=ENGINE_VERSION,
                    decision_snapshot={"legacy_stage":c.stage,"C01":claim_map["C01"].state,
                                       "C02":claim_map["C02"].state,"founder_status":c.founder_status},
                ))
                summary["decision_events_created"] += 1
            summary[f"verdict_{verdict.lower()}"] += 1

        await session.commit()

    print("\n"+"="*94)
    print("RADAR V4.0 — EVIDENCE-GOVERNED FOUNDATION")
    print("="*94)
    print(f"Candidates considered: {len(candidates)}")
    print(f"Candidates deferred before new RadarCase: {summary['candidates_deferred']}")
    print(f"Cases created/reused: {summary['cases_created']} / {summary['cases_reused']}")
    print(f"Claims created: {summary['claims_created']}")
    print(f"Ledger evidence created/reused: {summary['evidence_created']} / {summary['evidence_reused']}")
    print(f"Claim-evidence links created: {summary['claim_links_created']}")
    print(f"Unknowns created: {summary['unknowns_created']}")
    print("Claim states:")
    for s in ("supported","insufficient","unknown","refuted","conflicted"):
        print(f"  {s:12s}: {summary[f'claim_state_{s}']}")
    print("System verdicts:")
    for v in ("watch","investigate","ignore"):
        print(f"  {v:12s}: {summary[f'verdict_{v}']}")
    print("LLM calls: 0")
    print("LLM cost:  NT$0.00")
    print("No ProblemCandidate or CandidateEvidence rows were deleted.")
    print("="*94)
    return {
        "engine_version": ENGINE_VERSION,
        "llm_calls": 0,
        "llm_cost_twd": 0.0,
        "candidates_seen": len(candidates),
        "admission_states": dict(admission_states),
        "truth_boundary": "ADMISSION_ONLY_CONTROLS_NEW_CASE_WORKLOAD_NO_C01_C14_THRESHOLD_CHANGE",
        **dict(summary),
    }
