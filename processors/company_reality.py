"""Radar Company Reality V2 — claim synchronization.

C09 is Company Truth. This engine uses concrete local implementation artifacts
to assess only technical execution capability.

Important boundaries:
- CAN_DO means the currently running repository has concrete artifacts for all
  mapped technical capabilities required by the candidate.
- CAN_ACQUIRE means an adjacent capability appears learnable/acquirable, but is
  not proven in the repository.
- UNKNOWN means the local repository cannot establish a required capability.
- Distribution, customer acquisition, regulation, pricing, economics, and
  demand are NOT inferred from code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from database.connection import async_session, ProblemCandidate, RadarCase, RadarClaim
from processors.opportunity_reality import (
    _candidate_text,
    _domains,
    _ensure_evidence,
    _link_claim,
    _prime_reality_session_caches,
)

ENGINE_VERSION = "company-reality-r5-scoped-capability-sync"


@dataclass(frozen=True)
class CapabilityProbe:
    key: str
    paths_any: tuple[str, ...]
    description: str


PROBES = (
    CapabilityProbe(
        "AI_LLM",
        ("processors/llm_client.py", "processors/ai_task_registry.py"),
        "LLM integration and bounded AI-task infrastructure",
    ),
    CapabilityProbe(
        "DATA_PIPELINE",
        ("scrapers", "database/connection.py"),
        "data collection, normalization, persistence, and evidence pipelines",
    ),
    CapabilityProbe(
        "API_INTEGRATION",
        (
            "scrapers/source_network_scraper.py",
            "scrapers/direct_problem_expansion_scraper.py",
        ),
        "external API/feed integration and rate-limit-aware collection",
    ),
    CapabilityProbe(
        "WEB_BACKEND",
        ("api", "main.py"),
        "Python application/backend execution capability",
    ),
    CapabilityProbe(
        "WEB_FRONTEND",
        ("dashboard/package.json", "dashboard/src"),
        "web frontend/product-interface capability",
    ),
)

ADJACENT = {
    "ENTERPRISE_INTEGRATION": "CAN_ACQUIRE",
    "SECURITY_ENGINEERING": "CAN_ACQUIRE",
    "NETWORKING": "CAN_ACQUIRE",
}

DOMAIN_REQUIREMENTS = {
    "AI_LLM": {"AI_LLM", "DATA_PIPELINE"},
    "GPU_COMPUTE": {"GPU_KERNEL_ENGINEERING", "LLM_INFERENCE_ENGINEERING"},
    "DEVTOOLS": {"WEB_BACKEND", "DATA_PIPELINE"},
    "API_ACCESS": {"WEB_BACKEND", "API_INTEGRATION"},
    "CLOUD_DEVOPS": {"WEB_BACKEND", "API_INTEGRATION"},
    "DATA_ML": {"AI_LLM", "DATA_PIPELINE"},
    "SECURITY_PRIVACY": {"WEB_BACKEND", "SECURITY_ENGINEERING"},
    "NETWORKING": {"WEB_BACKEND", "NETWORKING"},
    "CRM_ENTERPRISE": {
        "WEB_BACKEND", "API_INTEGRATION", "ENTERPRISE_INTEGRATION"
    },
    "CREATIVE": {"AI_LLM", "WEB_FRONTEND"},
    "STARTUP_BUSINESS": {"WEB_BACKEND", "WEB_FRONTEND"},
    "CONSUMER_PRODUCT": {"WEB_BACKEND", "WEB_FRONTEND"},
}


SPECIALIST_PATTERNS = (
    ("GPU_KERNEL_ENGINEERING", ("rocm", "cuda", "cudagraph", "aiter", "gpu kernel", "triton kernel")),
    ("DISTRIBUTED_SERVING", ("vllm", "sglang", "disaggregated serving", "tensor parallel", "expert parallel", "speculative decoding")),
    ("LLM_INFERENCE_ENGINEERING", ("kv cache", "inference runtime", "model serving", "decode kernel", "prefill", "mxfp4", "fp8")),
    ("MODEL_RESEARCH", ("model reliability", "hallucination", "emergent misalignment", "model alignment", "foundation model")),
)

PHYSICAL_PATTERNS = (
    "physical",
    "space constraint",
    "clearance",
    "form factor",
    "manufactur",
    "warehouse",
    "shipping",
    "hardware installation",
)

PROFILE_PATH = Path("config/company_capability_profile.json")
PROFILE_CAPABILITY_MAP = {
    "ai/api integration": {"AI_LLM", "API_INTEGRATION"},
    "python backend development": {"WEB_BACKEND"},
    "web product prototyping": {"WEB_FRONTEND"},
    "data scraping and evidence pipelines": {"DATA_PIPELINE"},
    "rapid ai-assisted mvp implementation": {"WEB_BACKEND", "WEB_FRONTEND", "AI_LLM"},
}
REGULATED_PATTERNS = (
    "healthcare", "medical", "patient", "hipaa", "finance", "financial",
    "banking", "pci", "legal", "regulated", "compliance",
    "critical infrastructure",
)

def _load_company_profile(root: Path) -> dict[str, Any]:
    path = root / PROFILE_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def _profile_capabilities(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in profile.get("strengths", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("level") or "").lower() != "strong":
            continue
        mapped = PROFILE_CAPABILITY_MAP.get(str(row.get("capability") or "").strip().lower(), set())
        for cap in mapped:
            out[cap] = {
                "status": "CAN_DO",
                "artifacts": [str(PROFILE_PATH)],
                "description": str(row.get("evidence") or row.get("capability") or cap),
                "truth_source": "company_capability_profile",
            }
    return out


def _probe_local(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for probe in PROBES:
        found = [rel for rel in probe.paths_any if (root / rel).exists()]
        result[probe.key] = {
            "status": "CAN_DO" if found else "UNKNOWN",
            "artifacts": found,
            "description": probe.description,
        }

    for key, status in ADJACENT.items():
        result[key] = {
            "status": status,
            "artifacts": [],
            "description": (
                "adjacent capability; acquisition/learning is plausible "
                "but not proven"
            ),
        }

    return result


def _required_capabilities(
    candidate: ProblemCandidate,
) -> tuple[set[str], list[str]]:
    text = _candidate_text(candidate)
    domains = _domains(text)
    required: set[str] = set()

    for domain in domains:
        required |= DOMAIN_REQUIREMENTS.get(domain, set())

    notes: list[str] = []
    low = text.lower()

    for capability, patterns in SPECIALIST_PATTERNS:
        if any(pattern in low for pattern in patterns):
            required.add(capability)
            notes.append(
                f"specialist capability {capability} is required; generic AI/API code is not proof"
            )

    # A broad claim that the model itself is unreliable/incorrect requires model
    # research truth, not merely evidence that this repository calls an LLM API.
    if (
        ("ai model" in low or "llm" in low)
        and any(x in low for x in ("unreliable", "incorrect output", "wrong output", "hallucination", "assumption"))
    ):
        required.add("MODEL_RESEARCH")
        notes.append("foundational model-quality problem requires explicit MODEL_RESEARCH capability")

    if any(x in low for x in PHYSICAL_PATTERNS):
        required.add("PHYSICAL_OPERATIONS")
        notes.append("physical/operational capability appears necessary")

    if any(x in low for x in REGULATED_PATTERNS):
        required.add("REGULATED_COMPLIANCE")
        notes.append("regulated-domain capability requires explicit company truth")

    if not required:
        notes.append(
            "candidate domain does not map cleanly to proven local capabilities"
        )

    return required, notes


def _assessment(
    required: set[str],
    local: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    detail = {}
    statuses = []

    for cap in sorted(required):
        row = local.get(
            cap,
            {
                "status": "UNKNOWN",
                "artifacts": [],
                "description": (
                    "not established by local repository evidence"
                ),
            },
        )
        detail[cap] = row
        statuses.append(row["status"])

    if not required:
        overall = "UNKNOWN"
    elif all(x == "CAN_DO" for x in statuses):
        overall = "CAN_DO"
    elif any(x == "UNKNOWN" for x in statuses):
        overall = "UNKNOWN"
    elif any(x == "CAN_ACQUIRE" for x in statuses):
        overall = "CAN_ACQUIRE"
    else:
        overall = "UNKNOWN"

    return {
        "overall": overall,
        "required": sorted(required),
        "detail": detail,
    }


def _capability_gap_plan(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    """Make unresolved Company Truth actionable without pretending capability.

    The plan is routing metadata only. It never changes C09 state.
    """
    out = []
    for cap in assessment.get("required", []) or []:
        detail = (assessment.get("detail") or {}).get(cap) or {}
        status = str(detail.get("status") or "UNKNOWN").upper()
        if status == "CAN_DO":
            continue
        if cap == "REGULATED_COMPLIANCE":
            action = "OBTAIN_EXPERT_AND_REGULATORY_EVIDENCE_BEFORE_VALIDATE"
            boundary = "FOUNDER_OR_PARTNER_REQUIRED"
        elif cap == "PHYSICAL_OPERATIONS":
            action = "IDENTIFY_OPERATIONS_OR_HARDWARE_PARTNER_BEFORE_VALIDATE"
            boundary = "FOUNDER_OR_PARTNER_REQUIRED"
        elif status == "CAN_ACQUIRE":
            action = "PROVE_ACQUISITION_PATH_WITH_SMALL_TECHNICAL_SPIKE_OR_PARTNER"
            boundary = "MACHINE_PREPARES_FOUNDER_DECISION"
        else:
            action = "COLLECT_EXPLICIT_COMPANY_CAPABILITY_EVIDENCE"
            boundary = "COMPANY_TRUTH_REQUIRED"
        out.append({
            "capability": cap,
            "status": status,
            "action": action,
            "boundary": boundary,
            "truth_source": detail.get("truth_source"),
            "description": detail.get("description"),
        })
    return out


async def run_company_reality(case_ids: list[int] | None = None) -> dict[str, Any]:
    root = Path.cwd()
    profile = _load_company_profile(root)
    local = _probe_local(root)
    # Explicit persistent Company Truth can strengthen a technical capability,
    # but only when the profile marks it strong. Unknown/low gaps never become
    # CAN_DO merely because adjacent code exists.
    local.update(_profile_capabilities(profile))
    if any(
        str(row.get("capability") or "").lower() == "regulated-industry compliance"
        and str(row.get("level") or "").lower() in {"low_by_default", "unknown", "unknown_or_low_by_default"}
        for row in profile.get("known_gaps", []) or []
        if isinstance(row, dict)
    ):
        local["REGULATED_COMPLIANCE"] = {
            "status": "UNKNOWN",
            "artifacts": [],
            "description": "company profile explicitly does not establish regulated-industry compliance",
            "truth_source": "company_capability_profile",
        }
    now = datetime.utcnow()

    async with async_session() as session:
        stmt = (
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )
        if case_ids is not None:
            normalized_case_ids = sorted({int(x) for x in case_ids if int(x) > 0})
            stmt = stmt.where(RadarCase.id.in_(normalized_case_ids))
        pairs = list((await session.execute(stmt)).all())

        claims = list(
            (
                await session.execute(
                    select(RadarClaim).where(
                        RadarClaim.case_id.in_(
                            [case.id for case, _ in pairs]
                        ),
                        RadarClaim.claim_code == "C09",
                    )
                )
            ).scalars().all()
        )
        claim_map = {c.case_id: c for c in claims}
        # M18: Company Truth writes are idempotent but previously paid a
        # point-SELECT for every local artifact/link. Prime the shared ledger
        # cache once so the exact same C09 truth is synchronized in O(1)
        # lookups per artifact.
        await _prime_reality_session_caches(
            session, claim_ids=[int(c.id) for c in claims]
        )

        results = {}
        synced_supported = 0
        synced_insufficient = 0

        for case, candidate in pairs:
            required, notes = _required_capabilities(candidate)
            assess = _assessment(required, local)
            claim = claim_map.get(case.id)
            proven_groups = set()
            support_artifacts = []

            if claim:
                for cap in assess["required"]:
                    cap_row = assess["detail"][cap]
                    if cap_row["status"] != "CAN_DO":
                        continue

                    for rel in cap_row["artifacts"][:2]:
                        ev = await _ensure_evidence(
                            session,
                            case.id,
                            source_type="company_truth",
                            source_table="local_repository",
                            source_ref=f"{cap}:{rel}",
                            source_title=f"Local capability artifact: {cap}",
                            excerpt=(
                                f"{cap_row['description']}. "
                                f"Artifact present: {rel}"
                            ),
                            source_url=None,
                            source_family_key=f"company_capability:{cap}",
                            authority_class="COMPANY_CAPABILITY_EVIDENCE",
                            directness="DIRECT",
                            published_at=None,
                            metadata={
                                "engine_version": ENGINE_VERSION,
                                "capability": cap,
                                "artifact": rel,
                                "status": "CAN_DO",
                            },
                        )
                        await _link_claim(
                            session,
                            claim,
                            ev,
                            stance="SUPPORT",
                            rationale=(
                                "Running repository contains direct "
                                f"implementation evidence for required "
                                f"capability {cap}."
                            ),
                            confidence=0.92,
                        )
                        proven_groups.add(cap)
                        support_artifacts.append((cap, rel))

                es = dict(claim.evidence_summary or {})
                gap_plan = _capability_gap_plan(assess)
                es["company_reality_v2"] = {
                    **assess,
                    "notes": notes,
                    "capability_gap_plan": gap_plan,
                    "proven_local_artifacts": support_artifacts,
                    "scope_warning": (
                        "C09 covers technical execution capability only. Generic AI integration never proves model research, GPU kernel, or distributed-serving expertise. "
                        "Distribution, economics, regulation, pricing, "
                        "customer acquisition, and demand are separate claims."
                    ),
                }
                claim.evidence_summary = es

                # C09 is a company-truth claim, so the deterministic capability
                # assessment itself is authoritative for its state. Do not let
                # generic claim required_support_groups create a contradiction
                # such as "Company fit CAN_DO | C09 INSUFFICIENT".
                if assess["overall"] == "CAN_DO" and assess["required"]:
                    claim.state = "SUPPORTED"
                    claim.support_groups = max(
                        len(proven_groups),
                        int(claim.required_support_groups or 1),
                    )
                    claim.direct_support_groups = len(proven_groups)
                    claim.refute_groups = 0
                    claim.insufficient_count = 0
                    synced_supported += 1
                else:
                    claim.state = "INSUFFICIENT"
                    claim.support_groups = len(proven_groups)
                    claim.direct_support_groups = len(proven_groups)
                    claim.refute_groups = 0
                    claim.insufficient_count = max(
                        1, int(claim.insufficient_count or 0)
                    )
                    synced_insufficient += 1

                claim.last_evaluated_at = now

            results[case.id] = {
                "case_id": case.id,
                "candidate_id": candidate.id,
                "title": candidate.title,
                **assess,
                "notes": notes,
                "capability_gap_plan": _capability_gap_plan(assess),
            }

        await session.commit()

    counts: dict[str, int] = {}
    for row in results.values():
        counts[row["overall"]] = counts.get(row["overall"], 0) + 1

    return {
        "engine_version": ENGINE_VERSION,
        "cases": len(results),
        "counts": counts,
        "claim_sync_supported": synced_supported,
        "claim_sync_insufficient": synced_insufficient,
        "local_capabilities": local,
        "company_profile_loaded": bool(profile),
        "company_profile_version": profile.get("version") if isinstance(profile, dict) else None,
        "results": results,
        "llm_calls": 0,
        "api_calls": 0,
    }
