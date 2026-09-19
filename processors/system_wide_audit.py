"""SignalForge whole-system fine-grained audit V1.

One command reports every tracked subsystem so development can advance the
whole system in parallel instead of discovering one bottleneck per patch.
Percentages are the last user-accepted baselines and are NEVER auto-inflated.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any
from sqlalchemy import select, func

from database.connection import (
    async_session, ProblemCandidate, RadarCase, RadarClaim, RadarEvidence,
    RadarClaimEvidence, Post, NewsEvent, JobListing, GithubRepo, HFModel,
    SOQuestion, PackageDownload, YCCompany, ProductReview,
)
from processors.quality_guard import audit_quality
from processors.calibration import calibration_report
from processors.validation_cohort import load_validation_cohort
from processors.signalforge_runtime import get_signalforge_runtime_status
from processors.historical_replay import forward_policy_snapshot_status
from processors.market_closure_readiness import market_closure_readiness
from processors.signalforge_market_action_registry import build_market_action_queue, market_action_registry_report
from processors.signalforge_calibration_domains import calibration_domains_report

ENGINE_VERSION = "system-wide-audit-r9-postproduction-durability"

BASELINE = {
    "Data Sources / Crawlers": 87,
    "Source Coverage / Health": 86,
    "Problem Discovery": 78,
    "C02 Recurrence / Same Problem": 82,
    "C03 Pain Materiality": 79,
    "Evidence Ledger": 94,
    "Evidence Integrity / Quality Guard": 96,
    "C05 Buyer Reality": 78,
    "C06 Current Solution": 69,
    "C07 Unresolved Gap": 62,
    "C08 Differentiation": 68,
    "C09 Execution Reality": 80,
    "C10 Distribution": 67,
    "C11 Economics / WTP": 68,
    "C12 Opportunity Window": 72,
    "C13 Competition": 71,
    "C14 Switching": 68,
    "Decision Engine": 87,
    "Research Controller": 91,
    "Scheduler / Research Portfolio": 78,
    "Founder Daily Radar": 78,
    "VALIDATE -> Market Test": 78,
    "Market Result -> Evidence -> Decision": 65,
    "Historical Replay Engine": 70,
    "Calibration Infrastructure": 72,
    "Live Market Calibration": 0,
    "Predictive Accuracy": None,
}

GO_LIVE_TARGET = {
    "Data Sources / Crawlers": 90,
    "Source Coverage / Health": 92,
    "Problem Discovery": 85,
    "C02 Recurrence / Same Problem": 88,
    "C03 Pain Materiality": 88,
    "Evidence Ledger": 95,
    "Evidence Integrity / Quality Guard": 97,
    "C05 Buyer Reality": 88,
    "C06 Current Solution": 85,
    "C07 Unresolved Gap": 82,
    "C08 Differentiation": 80,
    "C09 Execution Reality": 88,
    "C10 Distribution": 80,
    "C11 Economics / WTP": 82,
    "C12 Opportunity Window": 80,
    "C13 Competition": 82,
    "C14 Switching": 80,
    "Decision Engine": 92,
    "Research Controller": 94,
    "Scheduler / Research Portfolio": 90,
    "Founder Daily Radar": 88,
    "VALIDATE -> Market Test": 88,
    "Market Result -> Evidence -> Decision": 75,
    "Historical Replay Engine": 78,
    "Calibration Infrastructure": 82,
}

CLAIM_AREA = {
    "C02": "C02 Recurrence / Same Problem", "C03": "C03 Pain Materiality",
    "C05": "C05 Buyer Reality", "C06": "C06 Current Solution",
    "C07": "C07 Unresolved Gap", "C08": "C08 Differentiation",
    "C09": "C09 Execution Reality", "C10": "C10 Distribution",
    "C11": "C11 Economics / WTP", "C12": "C12 Opportunity Window",
    "C13": "C13 Competition", "C14": "C14 Switching",
}


def _area() -> dict[str, Any]:
    return {
        "observed": {}, "problems": [],
        "m13_progress": [], "m14_progress": [], "m15_progress": [],
        "m16_progress": [], "m17_progress": [], "m18_progress": [],
        "r5_progress": [], "r6_progress": [], "r7_progress": [],
        "r8_progress": [], "r9_progress": [],
    }


def _load_published_founder_snapshot() -> dict[str, Any]:
    path = Path(".radar_runtime/founder_daily.json")
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


async def run_system_wide_audit() -> dict[str, Any]:
    runtime = get_signalforge_runtime_status()
    if runtime.get("running"):
        published = _load_published_founder_snapshot()
        return {
            "engine_version": ENGINE_VERSION,
            "deferred_while_cycle_running": True,
            "published_only": True,
            "runtime": runtime,
            "published_founder": {
                "generated_at": published.get("generated_at"),
                "verdict_counts": published.get("verdict_counts") or {},
                "validation_boundary": published.get("validation_boundary") or {},
                "quality": published.get("quality") or {},
                "cards": published.get("cards") or [],
            },
            "percentages_auto_advanced": False,
            "quality": published.get("quality") or {"status": "PUBLISHED_ONLY"},
            "areas": {},
            "go_live_targets": GO_LIVE_TARGET,
            "note": "Cycle is running. Unpublished DB truth is intentionally hidden; only the last successful Founder snapshot is exposed.",
        }

    areas = {
        name: {
            "baseline_percent": pct,
            "go_live_target": GO_LIVE_TARGET.get(name),
            **_area(),
        }
        for name, pct in BASELINE.items()
    }
    async with async_session() as session:
        candidates = int((await session.execute(select(func.count(ProblemCandidate.id)))).scalar() or 0)
        cases = list((await session.execute(select(RadarCase))).scalars().all())
        claims = list((await session.execute(select(RadarClaim))).scalars().all())
        evidence_n = int((await session.execute(select(func.count(RadarEvidence.id)))).scalar() or 0)
        links_n = int((await session.execute(select(func.count(RadarClaimEvidence.id)))).scalar() or 0)
        source_counts = {
            "posts": int((await session.execute(select(func.count(Post.id)))).scalar() or 0),
            "news": int((await session.execute(select(func.count(NewsEvent.id)))).scalar() or 0),
            "jobs": int((await session.execute(select(func.count(JobListing.id)))).scalar() or 0),
            "github": int((await session.execute(select(func.count(GithubRepo.id)))).scalar() or 0),
            "huggingface": int((await session.execute(select(func.count(HFModel.id)))).scalar() or 0),
            "stackoverflow": int((await session.execute(select(func.count(SOQuestion.id)))).scalar() or 0),
            "packages": int((await session.execute(select(func.count(PackageDownload.id)))).scalar() or 0),
            "yc": int((await session.execute(select(func.count(YCCompany.id)))).scalar() or 0),
            "product_reviews": int((await session.execute(select(func.count(ProductReview.id)))).scalar() or 0),
        }

    by_code: dict[str, Counter] = {}
    for claim in claims:
        by_code.setdefault(str(claim.claim_code), Counter())[str(claim.state or "UNKNOWN").upper()] += 1
    for code, area_name in CLAIM_AREA.items():
        counts = dict(by_code.get(code, Counter()))
        areas[area_name]["observed"]["claim_states"] = counts
        unresolved = counts.get("UNKNOWN", 0) + counts.get("INSUFFICIENT", 0)
        if unresolved:
            areas[area_name]["problems"].append(f"{unresolved}/{len(cases)} cases remain UNKNOWN/INSUFFICIENT")

    quality = await audit_quality()
    calibration = calibration_report()
    cohort = load_validation_cohort()
    forward_policy = forward_policy_snapshot_status()
    market_closure = market_closure_readiness()
    published = _load_published_founder_snapshot()
    market_actions = build_market_action_queue(limit=100)
    action_registry = market_action_registry_report()
    split_calibration = calibration_domains_report()
    verdicts = dict(Counter(str(c.system_verdict or "WATCH") for c in cases))
    gates = dict(Counter(str(c.current_gate or "") for c in cases))

    areas["Data Sources / Crawlers"]["observed"] = source_counts
    areas["Source Coverage / Health"]["observed"] = {
        "runtime": runtime,
        "last_cycle_source_health": (runtime.get("last_cycle") or {}).get("source_health") or {},
    }
    areas["Problem Discovery"]["observed"] = {
        "problem_candidates": candidates,
        "radar_cases": len(cases),
        "last_cycle_discovery": (runtime.get("last_cycle") or {}).get("problem_discovery") or {},
        "discovery_source_health": ((runtime.get("last_cycle") or {}).get("source_health") or {}).get("problem_discovery") or {},
        "discovery_portfolio": (runtime.get("last_cycle") or {}).get("discovery_portfolio") or (((runtime.get("last_cycle") or {}).get("problem_discovery") or {}).get("discovery_portfolio") or {}),
    }
    areas["Evidence Ledger"]["observed"] = {"evidence_rows": evidence_n, "claim_links": links_n}
    areas["Evidence Integrity / Quality Guard"]["observed"] = {
        "status": quality.get("status"), "critical": quality.get("critical_count", 0), "warnings": quality.get("warning_count", 0)
    }
    areas["Decision Engine"]["observed"] = {"verdicts": verdicts, "gates": gates}
    areas["Research Controller"]["observed"] = {
        "wake_catchup_runtime": runtime.get("engine_version"),
        "last_cycle": runtime.get("last_cycle") or {},
        "last_attempt_status": runtime.get("last_attempt_status"),
        "last_attempt_error": runtime.get("last_attempt_error"),
        "last_attempt_cycle": runtime.get("last_attempt_cycle") or {},
        "observability_health": (runtime.get("progress") or {}).get("observability_health"),
        "last_telemetry_error": (runtime.get("progress") or {}).get("last_telemetry_error"),
    }
    areas["Scheduler / Research Portfolio"]["observed"] = {
        "stale_after_hours": runtime.get("stale_after_hours"),
        "fresh": runtime.get("fresh"),
        "last_success_at": runtime.get("last_success_at"),
        "cross_process_lease": runtime.get("lease"),
        "runtime_engine": runtime.get("engine_version"),
        "last_cycle_source_health": (runtime.get("last_cycle") or {}).get("source_health") or {},
        "last_cycle_recurrence": (runtime.get("last_cycle") or {}).get("recurrence") or {},
        "last_cycle_materiality": (runtime.get("last_cycle") or {}).get("materiality") or {},
        "last_cycle_phase_seconds": (runtime.get("last_cycle") or {}).get("phase_seconds") or {},
        "cycle_profile": (runtime.get("last_cycle") or {}).get("cycle_profile") or {},
        "execution_governor": (runtime.get("last_cycle") or {}).get("execution_governor") or published.get("execution_governor") or {},
        "operating_queue": (runtime.get("last_cycle") or {}).get("operating_queue") or published.get("operating_queue") or {},
        "phase_value": (runtime.get("last_cycle") or {}).get("phase_value") or {},
        "brain_refresh": (runtime.get("last_cycle") or {}).get("brain_refresh") or {},
        "post_brain_routing": (runtime.get("last_cycle") or {}).get("post_brain_routing") or {},
        "strategic_routing_coherence": (runtime.get("last_cycle") or {}).get("strategic_routing_coherence") or published.get("strategic_routing_coherence") or {},
        "warm_cache_readiness": (runtime.get("last_cycle") or {}).get("warm_cache_readiness") or {},
        "last_attempt_status": runtime.get("last_attempt_status"),
        "last_attempt_cycle": runtime.get("last_attempt_cycle") or {},
        "last_attempt_phase_seconds": (runtime.get("last_attempt_cycle") or {}).get("phase_seconds") or {},
        "last_attempt_brain_refresh": (runtime.get("last_attempt_cycle") or {}).get("brain_refresh") or {},
        "last_attempt_post_brain_routing": (runtime.get("last_attempt_cycle") or {}).get("post_brain_routing") or {},
        "last_attempt_strategic_routing_coherence": (runtime.get("last_attempt_cycle") or {}).get("strategic_routing_coherence") or {},
        "last_attempt_warm_cache_readiness": (runtime.get("last_attempt_cycle") or {}).get("warm_cache_readiness") or {},
        "observability_health": (runtime.get("progress") or {}).get("observability_health"),
    }
    areas["Founder Daily Radar"]["observed"] = {
        "signalforge_truth_api_ready": True,
        "legacy_candidate_truth_separated": True,
        "founder_strategy": published.get("founder_strategy") or {},
        "execution_governor": published.get("execution_governor") or {},
        "strategic_routing_coherence": published.get("strategic_routing_coherence") or {},
        "operating_queue": published.get("operating_queue") or {},
        "market_action_queue": market_actions,
        "market_action_registry": {k: action_registry.get(k) for k in ("total", "registered", "running", "completed")},
    }
    areas["VALIDATE -> Market Test"]["observed"] = {
        "treatment_candidates": cohort.get("treatment_candidates", 0),
        "control_candidates": cohort.get("control_candidates", 0),
        "matched_pairs": len(cohort.get("matched_pairs", []) or []),
        "clean_matched_pairs": int(cohort.get("clean_matched_pairs", 0) or 0),
        "contaminated_pairs": int(cohort.get("contaminated_pairs", 0) or 0),
        "selection_snapshot_frozen": bool(cohort.get("selection_snapshot_frozen", False)),
    }
    areas["Market Result -> Evidence -> Decision"]["observed"] = {
        "completed_real_experiments": calibration.get("completed_experiments", 0),
        "independent_actor_pairs": calibration.get("independent_actor_pairs", 0),
        "closure_readiness": market_closure,
    }
    areas["Historical Replay Engine"]["observed"] = {
        "policy_mode": "CURRENT_POLICY_ON_HISTORICAL_EVIDENCE",
        "policy_frozen_to_cutoff": False,
        "forward_policy_recording": forward_policy,
    }
    areas["Calibration Infrastructure"]["observed"] = {
        **(calibration.get("prospective_controls") or {}),
        "credibility": (calibration.get("credibility") or {}).get("status"),
    }
    areas["Live Market Calibration"]["observed"] = {
        "completed_real_experiments": calibration.get("completed_experiments", 0),
        "credibility": (calibration.get("credibility") or {}).get("status"),
    }
    areas["Predictive Accuracy"]["observed"] = {"status": "UNVALIDATED"}

    # M13 cross-cutting progress, without awarding percentages yet.
    areas["C03 Pain Materiality"]["m13_progress"].append("material consequence now requires concrete operational/economic impact; C03 added to strict ledger repair")
    areas["C05 Buyer Reality"]["m13_progress"].append("buyer ownership/budget is separated from WTP; C11 remains the WTP claim")
    areas["C06 Current Solution"]["m13_progress"].append("solution recall now includes existing ProductReview + sample-post evidence without lowering same-problem gates")
    areas["C07 Unresolved Gap"]["m13_progress"].append("inherits broader named-solution review corpus while keeping two-family persistence proof")
    for name in ("C08 Differentiation", "C10 Distribution", "C11 Economics / WTP", "C12 Opportunity Window", "C13 Competition", "C14 Switching"):
        areas[name]["m13_progress"].append("commercial context no longer mutates zero-evidence UNKNOWN claims to INSUFFICIENT")
    areas["C09 Execution Reality"]["m13_progress"].append("persistent company capability profile now participates in Company Truth; regulated gaps stay UNKNOWN until explicit proof")
    areas["Evidence Integrity / Quality Guard"]["m13_progress"].append("C03 is now quality-locked and ledger-reconciled with the same threshold discipline as C05-C14")
    areas["Research Controller"]["m13_progress"].append("parallel reality target coverage expanded while AI/source budgets remain unchanged")
    areas["Founder Daily Radar"]["m13_progress"].append("homepage/API can read actual RadarCase/RadarClaim decision truth instead of legacy ProblemCandidate stage")
    areas["VALIDATE -> Market Test"]["m13_progress"].append("prospective treatment/control matching exists before outcomes")
    areas["Historical Replay Engine"]["m13_progress"].append("replay explicitly labels current-policy-on-historical-evidence instead of implying historical-policy fidelity")
    areas["Calibration Infrastructure"]["m13_progress"].append("matched control readiness is reported but never counted as accuracy")
    areas["Live Market Calibration"]["problems"].append("real market outcomes are still required; actual live calibration remains 0%")
    areas["Predictive Accuracy"]["problems"].append("no treatment/control real outcome set yet; predictive accuracy remains UNVALIDATED")

    # M14 engineering progress is reported separately from accepted completion %.
    areas["Data Sources / Crawlers"]["m14_progress"].append(
        "source health is classified from ScraperRun DB truth rather than CLI exit code; UTF-8 child output prevents cp950 reader failures"
    )
    areas["Source Coverage / Health"]["m14_progress"].append(
        "legacy backoff gets one DB-backed re-probe; transient failures use bounded exponential retry instead of six-hour starvation"
    )
    areas["C02 Recurrence / Same Problem"]["m14_progress"].append(
        "production recurrence verifier now runs inside every real Radar cycle under the same global AI budget"
    )
    areas["C03 Pain Materiality"]["m14_progress"].append(
        "new C02 direct evidence is re-evaluated for concrete material consequence in the same cycle"
    )
    areas["C05 Buyer Reality"]["m14_progress"].append(
        "buyer AI cache is evidence/content/contract-versioned; stale INSUFFICIENT decisions expire after 24h"
    )
    areas["C06 Current Solution"]["m14_progress"].append(
        "solution corpus now includes named-solution failure posts from the existing 8k+ community corpus even when ProductReview is empty"
    )
    areas["Problem Discovery"]["m14_progress"].append(
        "stale/corpus-change-aware bounded discovery is part of the real Radar cycle and shares the global AI cap; CandidateEvidence ids are stable across refreshes"
    )
    areas["Evidence Ledger"]["m14_progress"].append(
        "discovery no longer delete/reinserts CandidateEvidence; stable provenance prevents repeated ledger evidence churn"
    )
    areas["C07 Unresolved Gap"]["m14_progress"].append(
        "community named-solution persistence evidence feeds the same two-independent-family C07 contract"
    )
    for name in ("C08 Differentiation", "C10 Distribution", "C11 Economics / WTP", "C12 Opportunity Window", "C13 Competition", "C14 Switching"):
        areas[name]["m14_progress"].append(
            "scheduler can now reach all due problem/buyer/market/timing groups in one cycle instead of starving lower-ranked parallel reality sources"
        )
        areas[name]["m14_progress"].append(
            "parallel reality reports whether a case has no RadarEvidence, no claim-qualified evidence, or no independent family instead of returning an opaque zero-link result"
        )
    areas["Research Controller"]["m14_progress"].append(
        "C02, source refresh, buyer, solution/gap and parallel reality share one cycle budget and one quality gate"
    )
    areas["Scheduler / Research Portfolio"]["m14_progress"].append(
        "up to four source groups can progress per cycle; failed groups are not retried identically in round 2"
    )
    areas["Founder Daily Radar"]["m14_progress"].append(
        "runtime freshness now follows manual and scheduled cycles through one cross-process lease"
    )
    areas["VALIDATE -> Market Test"]["m14_progress"].append(
        "treatment/control assignments are immutable after first pre-outcome freeze; later-selected controls are flagged contaminated instead of silently rematched"
    )
    areas["Market Result -> Evidence -> Decision"]["m14_progress"].append(
        "market-closure readiness verifies preregistration, claim/event mapping, identified-actor PASS rules and fail-closed result ingestion without synthetic outcomes"
    )
    areas["Historical Replay Engine"]["m14_progress"].append(
        "every successful cycle now writes a forward policy/decision snapshot so future replay can use what SignalForge actually said at time t"
    )
    areas["Calibration Infrastructure"]["m14_progress"].append(
        "future comparative calibration is restricted to frozen uncontaminated control pairs; contaminated controls remain visible but excluded from clean lift"
    )

    # M15 focuses on wall-clock and evidence conversion, not new scoring.
    areas["Source Coverage / Health"]["m15_progress"].append(
        "independent source groups execute concurrently with shared-scraper dedupe and hard per-source timeout caps"
    )
    areas["C02 Recurrence / Same Problem"]["m15_progress"].append(
        "the 3k+ direct-problem index is built once per cycle instead of up to three times"
    )
    areas["C03 Pain Materiality"]["m15_progress"].append(
        "direct material-impact documents are mined with structural same-problem gates and the unchanged two-family C03 threshold"
    )
    areas["C05 Buyer Reality"]["m15_progress"].append(
        "top unresolved C05 cases are prefetched even while an earlier gate remains open; Decision gate order is unchanged"
    )
    areas["C06 Current Solution"]["m15_progress"].append(
        "top unresolved C06 cases are prefetched in parallel with earlier-gate research without manufacturing progression"
    )
    areas["C07 Unresolved Gap"]["m15_progress"].append(
        "C07 keeps the same independent-family proof contract while solution evidence is prepared earlier"
    )
    areas["Research Controller"]["m15_progress"].append(
        "one integrated daily round batches source, discovery, recurrence, materiality, buyer, solution and C08-C14 research before final Decision rebuild"
    )
    areas["Scheduler / Research Portfolio"]["m15_progress"].append(
        "manual/scheduled cycles use one round and expose per-phase wall-clock telemetry; unhealthy sources cannot serially consume the whole cycle"
    )
    areas["Founder Daily Radar"]["m15_progress"].append(
        "Founder snapshot is still produced from the final Decision truth, now after a bounded fast cycle"
    )

    # M16 closes the two blockers exposed by the real M15 cycle:
    # solution prefetch was shadowed by earlier-gate rows, and repeated
    # idempotent Reality rebuilds dominated wall-clock.
    areas["C06 Current Solution"]["m16_progress"].append(
        "solution target normalization now filters non-C06/C07 gates before merge, so CURRENT_SOLUTION prefetch cannot be shadowed by PAIN/BUYER rows"
    )
    areas["C07 Unresolved Gap"]["m16_progress"].append(
        "C07 prefetch becomes eligible immediately after C06 SUPPORT while preserving the independent-family persistence contract"
    )
    areas["Evidence Ledger"]["m16_progress"].append(
        "idempotent evidence/link lookups are session-cached from one full ledger preload; truth thresholds and provenance are unchanged"
    )
    areas["C03 Pain Materiality"]["m16_progress"].append(
        "materiality writes reuse the same ledger cache instead of issuing per-link point queries"
    )
    areas["Decision Engine"]["m16_progress"].append(
        "intermediate scheduling reads persisted case/claim truth; full Reality+Decision rebuild is reserved for the final product decision"
    )
    areas["Research Controller"]["m16_progress"].append(
        "normal cycle performs one full Decision rebuild; rollback retains a second rebuild only on quality failure"
    )
    areas["Scheduler / Research Portfolio"]["m16_progress"].append(
        "C06 receives up to three focused adjudications after reserving buyer budget; earlier-gate rows can no longer suppress the solution run"
    )
    areas["Founder Daily Radar"]["m16_progress"].append(
        "Founder output still comes from the final full Decision truth; fast intermediate snapshots are never exposed as Founder truth"
    )
    areas["Founder Daily Radar"]["m17_progress"].append(
        "API/audit hide in-flight DB mutations and expose only the last successful Founder snapshot while a cycle owns the lease"
    )
    areas["Scheduler / Research Portfolio"]["m17_progress"].append(
        "deployment guard blocks startup/scheduled catch-up during code reload; manual CLI/API clears the guard and gets bounded priority over auto owners"
    )
    areas["Research Controller"]["m17_progress"].append(
        "stale RUNNING state without a live lease is surfaced as INTERRUPTED instead of pretending work is still active"
    )

    # M18 operational cutover: remove repeated deterministic recomputation and
    # allocate scarce solution adjudication budget toward actual two-family
    # closure instead of breadth-only one-call sampling.
    areas["C03 Pain Materiality"]["m18_progress"].append(
        "exact C03 structural/consequence features are precomputed once per candidate/document; truth contract is unchanged while repeated regex/token parsing is removed"
    )
    areas["C06 Current Solution"]["m18_progress"].append(
        "solution adjudication is depth-first toward two independent SAME_PROBLEM families, with rank-stable pair-cache reuse and no threshold change"
    )
    areas["C07 Unresolved Gap"]["m18_progress"].append(
        "after real C06 SUPPORT, already-verified SAME_PROBLEM evidence can close C07 in the same cycle only when two independent families also pass deterministic persistence"
    )
    areas["Decision Engine"]["m18_progress"].append(
        "normal final Decision reads persisted RadarEvidence/claim truth instead of rerunning fuzzy source materialization; raw source/candidate changes still trigger one full materializer"
    )
    areas["C09 Execution Reality"]["m18_progress"].append(
        "Company Truth primes the shared evidence/link cache once instead of issuing one point SELECT per local capability artifact"
    )
    areas["Decision Engine"]["m18_progress"].append(
        "commercial claim-state refresh is batched from one ledger preload instead of issuing one link query per C08/C10-C14 claim"
    )
    areas["Research Controller"]["m18_progress"].append(
        "runtime records solution-depth diagnostics and final reality mode for verifiable Go-Live checks"
    )
    areas["Scheduler / Research Portfolio"]["m18_progress"].append(
        "scarce C06/C07 AI budget is allocated for claim closure depth while preserving a buyer-research reserve"
    )

    areas["Problem Discovery"]["r5_progress"].append(
        "opportunity-bearing enrichment portfolio balances workaround/buyer/transition/pain signals against narrow troubleshooting while preserving every raw observation"
    )
    areas["Research Controller"]["r5_progress"].append(
        "one execution governor routes each case to machine research, market action, Founder discovery, wait, park or monitor; routing has zero atomic truth authority"
    )
    areas["Scheduler / Research Portfolio"]["r5_progress"].append(
        "all expensive lanes consume the same bounded machine execution set; machine eligibility is explicitly separated from actual execution"
    )
    areas["Decision Engine"]["r5_progress"].append(
        "persisted no-source cycles scope Company/Commercial/floor decision reduction to touched/new bounded cases; untouched RadarCase dispositions are not mutated"
    )
    areas["Founder Daily Radar"]["r5_progress"].append(
        "Founder surface exposes the operating queue and pre-registered market-action loop instead of treating Candidate backlog as the work queue"
    )
    areas["VALIDATE -> Market Test"]["r5_progress"].append(
        "Brain market/Founder actions can be pre-registered with an immutable pre-test strategic snapshot before execution"
    )
    areas["VALIDATE -> Market Test"]["r5_progress"].append(
        "Founder UI/API now exposes claim-specific C10/C11/C14 validation preregistration before outcomes; thesis-level actions cannot be retroactively converted into atomic truth"
    )
    areas["Market Result -> Evidence -> Decision"]["r5_progress"].append(
        "claim-specific results are recorded only through the existing market_ground_truth quality-locked writer, then the immutable validation registry is closed and only the affected case is recomputed"
    )
    areas["Calibration Infrastructure"]["r5_progress"].append(
        "split calibration consumes only completed PASS/FAIL actions that also satisfy a durable outcome-quality gate: pre-test snapshot, preregistered sample completion, identified actors, observation references and category-specific behavior/findings; Founder discovery cannot masquerade as fast-market validation"
    )

    areas["Decision Engine"]["r6_progress"].append(
        "fresh source/discovery cycles materialize only bounded/new case scope; untouched historical cases read persisted reality instead of triggering full-world reduction"
    )
    areas["Research Controller"]["r6_progress"].append(
        "derived Brain refresh now precedes Founder publication and post-Brain work routing without gaining C01-C14 truth authority"
    )
    areas["Founder Daily Radar"]["r6_progress"].append(
        "machine eligibility, selected execution and capacity backlog are distinct Founder-visible concepts"
    )

    areas["Scheduler / Research Portfolio"]["r7_progress"].append(
        "Windows-safe unique-temp atomic runtime writes remove shared .tmp collisions across watchdog, worker and API processes"
    )
    areas["Research Controller"]["r7_progress"].append(
        "observability write failures are explicitly non-authoritative and cannot convert an otherwise valid production cycle into FAIL; last-attempt diagnostics are separated from last-success truth"
    )
    areas["C02 Recurrence / Same Problem"]["r7_progress"].append(
        "exact retrieval matrices are reused only when the complete bounded query representation and direct-problem corpus hash are identical; thresholds and evidence gates are unchanged"
    )
    areas["C05 Buyer Reality"]["r7_progress"].append(
        "shared exact retrieval caching reuses identical buyer retrieval results across unchanged bounded inputs while reconstructing current source metadata"
    )
    areas["C06 Current Solution"]["r7_progress"].append(
        "shared exact retrieval caching reuses identical solution-recall computations across unchanged bounded inputs without caching claim truth"
    )
    areas["Founder Daily Radar"]["r7_progress"].append(
        "System and Founder surfaces now distinguish last successful cycle from the most recent attempted cycle and show observability degradation independently"
    )

    areas["Live Market Calibration"]["observed"] = split_calibration
    areas["Live Market Calibration"]["problems"].append(
        "Real market outcomes remain externally constrained; zero/UNVALIDATED is preserved until observed actions complete."
    )

    return {
        "engine_version": ENGINE_VERSION,
        "percentages_auto_advanced": False,
        "quality": quality,
        "areas": areas,
        "go_live_targets": GO_LIVE_TARGET,
        "note": "Baselines remain accepted engineering values and are not auto-inflated. R6-R9 advance scoped live execution, strategic freshness, runtime durability, exact derived retrieval reuse, strategic routing coherence, and post-production attempt diagnostics without fabricating market outcomes.",
    }
