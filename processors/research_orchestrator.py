"""Radar Auto Research Orchestrator V1.

Turns "Next machine gate" into actual machine work.

Cycle:
1. Read current decision state.
2. Select INVESTIGATE / VALIDATE cases.
3. Route the earliest unresolved gate to the cheapest appropriate sources.
4. Respect source-group cooldowns.
5. Refresh only the source families needed for the current gate.
6. Perform deterministic focused local evidence research.
7. Re-run Reality + Decision and report what actually changed.

No LLM calls are used in V1.
No claim threshold is weakened merely to create progress.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarEvidence,
    RadarClaimEvidence,
    RadarAIBudgetLedger,
    RadarResearchAction,
    JobListing,
    ScraperRun,
)
from processors.opportunity_decision import run_opportunity_decision
from processors.buyer_source_network import fetch_structured_buyer_jobs
from processors.solution_gap_research import run_solution_gap_research
from processors.parallel_reality_bundle import run_parallel_reality_bundle
from processors.research_portfolio import (
    build_research_portfolio,
    prioritize_source_groups,
)
from processors.case_progression import attach_progression_packets, select_progression_targets
from processors.problem_recurrence_multi import run_problem_recurrence_multi
from processors.problem_discovery_refresh import run_problem_discovery_refresh
from processors.materiality_research import run_materiality_research
from processors.quality_guard import (
    audit_quality,
    capture_quality_snapshot,
    rollback_quality_snapshot,
    repair_ledger_state_from_validated_links,
)
from processors.evidence_integrity import run_evidence_integrity_reconcile
from processors.ai_budget_gate import evaluate_ai_gate
from processors.ai_task_registry import get_ai_task
# SIGNALFORGE_BRAIN_V2_FULL_SYSTEM_RESEARCH_ADVISORY_R1
from processors.signalforge_production_admission import annotate_rows, active_rows
from processors.signalforge_execution_governor import annotate_execution_routes, machine_rows, operating_queue
from processors import signalforge_runtime_progress as runtime_progress
from processors.signalforge_brain_v2_integration import (
    safe_brain_research_advisory,
    merge_research_source_priority,
    safe_record_brain_research_execution,
)
from processors.llm_client import TokenUsage, call_llm
from processors.opportunity_reality import (
    _match_rows,
    _ensure_evidence,
    _link_claim,
    _refresh_claim_state,
    retrieval_cache_diagnostics,
)

ENGINE_VERSION = "auto-research-orchestrator-r7-durable-incremental-retrieval"
STATE_PATH = Path(".radar_runtime/research_cycle_state.json")

BUYER_GROUP = ("jobs",)
PROBLEM_GROUP = ("problem_sources", "source_network")
MARKET_GROUP = ("yc", "packages", "github")
TIMING_GROUP = ("news", "packages")

GROUP_COOLDOWN_HOURS = {
    "buyer": 12,
    "problem": 12,
    "market": 24,
    "timing": 6,
}

SCRAPER_TIMEOUT_CAP_SECONDS = {
    # M15 hard wall-clock discipline. Independent source groups run in
    # parallel; one unhealthy collector may not hold the Founder cycle hostage.
    "github": 75,
    "yc": 60,
    "packages": 60,
    "news": 60,
    "jobs": 75,
    "problem_sources": 150,
    "source_network": 120,
}

SCRAPER_BACKOFF_HOURS = {
    "github": 24,
    "yc": 6,
    "packages": 6,
    "news": 6,
    "jobs": 6,
    "problem_sources": 6,
    "source_network": 6,
}

GROUP_SUCCESS_TARGET = {
    "buyer": 1,
    "problem": 1,
    "market": 2,
    "timing": 1,
}

MAX_SOURCE_GROUPS_PER_CYCLE = 4
MAX_SOURCE_GROUPS_PER_ROUND = 3
MAX_ACTIVE_RESEARCH_CASES = max(4, min(40, int(os.getenv("SIGNALFORGE_MAX_ACTIVE_RESEARCH_CASES", "24") or 24)))
GROUP_WALLCLOCK_CAP_SECONDS = {"buyer": 75, "problem": 120, "market": 90, "timing": 75}
SCRAPER_RUN_NAME = {
    "jobs": "job_scraper",
    "problem_sources": "direct_problem_expansion",
    "source_network": "source_network",
    "github": "github_scraper",
    "yc": "yc_scraper",
    "packages": "package_scraper",
    "news": "news_scraper",
}

MAX_RESEARCH_AI_CALLS_PER_CYCLE = max(
    0,
    min(
        12,
        int(os.getenv("RADAR_MAX_RESEARCH_AI_CALLS", "12") or 12),
    ),
)
MAX_BUYER_AI_CALLS_PER_CYCLE = MAX_RESEARCH_AI_CALLS_PER_CYCLE
MAX_BUYER_AI_CALLS_PER_ROUND = max(
    1,
    min(
        6,
        int(os.getenv("RADAR_MAX_BUYER_AI_CALLS_PER_ROUND", "4") or 4),
    ),
)
ESTIMATED_BUYER_AI_CALL_TWD = max(
    0.0,
    float(os.getenv("RADAR_BUYER_AI_ESTIMATED_TWD", "0.02") or 0.02),
)
USD_TWD_RATE = max(
    1.0,
    float(os.getenv("USD_TWD_RATE", "31.83") or 31.83),
)
BUYER_AI_CACHE_KEY = "buyer_claim_stance_ai_v2_evidence_versioned"

BUYER_AI_SYSTEM = """You are a skeptical evidence adjudicator.

Your only task is to judge whether ONE already-retrieved public job posting is
evidence for the atomic claim: a plausible economic buyer exists for the
specific problem described in CASE A.

False positives are more costly than false negatives.

SUPPORT requires all of these:
1. a concrete named organization is hiring/spending real budget;
2. the role explicitly owns responsibilities that directly address the same
   concrete problem or an operational capability whose purpose is to prevent,
   measure, mitigate, or solve that problem;
3. the link is specific, not merely shared AI/ML/software vocabulary.

Generic AI hiring, generic model development, or a role that merely uses the
same technology is INSUFFICIENT.

Use only supplied case/job text. Do not use outside knowledge. Do not infer
purchase intent, market size, willingness-to-pay, or product attractiveness.
A single job posting cannot REFUTE buyer existence.

Return valid JSON only."""


def _buyer_ai_prompt(
    case: RadarCase,
    candidate: ProblemCandidate,
    match: dict[str, Any],
) -> str:
    case_payload = {
        "case_id": case.id,
        "title": candidate.title,
        "problem_statement": candidate.problem_statement,
        "actor": candidate.actor,
        "task": candidate.task,
        "object": candidate.object,
        "failure_mode": candidate.failure_mode,
        "consequence": candidate.consequence,
        "buyer_context": candidate.buyer_context,
    }
    job_payload = {
        "job_id": str(match.get("id")),
        "company": match.get("company"),
        "title": match.get("title"),
        "excerpt": str(match.get("text") or "")[:2200],
        "semantic_score": match.get("semantic_score"),
        "lexical_score": match.get("lexical_score"),
        "shared_terms": match.get("shared_terms", []),
        "rare_shared": match.get("rare_shared", []),
        "named_shared": match.get("named_shared", []),
        "domain_shared": match.get("domain_shared", []),
    }
    return f"""Classify the supplied job posting against C05 buyer_exists.

CASE A:
{json.dumps(case_payload, ensure_ascii=False, indent=2)}

JOB EVIDENCE B:
{json.dumps(job_payload, ensure_ascii=False, indent=2)}

Return exactly:
{{
  "stance": "SUPPORT | INSUFFICIENT",
  "evidence_ids": ["CASE_{case.id}", "JOB_{str(match.get('id'))}"],
  "rationale": "1-3 skeptical sentences using only supplied evidence"
}}

SUPPORT only when the job clearly allocates budget to responsibilities directly
aimed at the concrete CASE A problem/capability. Otherwise INSUFFICIENT.
"""


def _validate_buyer_ai_result(
    obj: Any,
    *,
    case_id: int,
    job_id: str,
) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not_object"
    if obj.get("stance") not in {"SUPPORT", "INSUFFICIENT"}:
        return False, "bad_stance"
    ids = obj.get("evidence_ids")
    if not isinstance(ids, list):
        return False, "bad_evidence_ids"
    required = {f"CASE_{case_id}", f"JOB_{job_id}"}
    if not required.issubset({str(x) for x in ids}):
        return False, "missing_required_evidence_ids"
    rationale = str(obj.get("rationale") or "").strip()
    if not rationale:
        return False, "missing_rationale"
    return True, "OK"


def _buyer_capability_terms(candidate: ProblemCandidate) -> list[str]:
    text = " ".join(
        str(x or "")
        for x in (
            candidate.title,
            candidate.problem_statement,
            candidate.failure_mode,
            candidate.consequence,
            candidate.task,
            candidate.object,
        )
    ).lower()

    terms = {
        "ai platform",
        "machine learning platform",
        "production ai",
    }

    groups = (
        (
            (
                "reliable", "reliability", "incorrect", "wrong output",
                "assumption", "hallucin", "quality", "unusable output",
            ),
            (
                "llm evaluation", "model evaluation", "ai reliability",
                "model quality", "evals", "guardrails", "correctness",
                "hallucination detection",
            ),
        ),
        (
            (
                "complex", "complexity", "deployment", "system prompt",
                "orchestration", "configuration",
            ),
            (
                "ml platform", "ai platform", "developer experience",
                "model deployment", "llm platform", "ai infrastructure",
                "mlops",
            ),
        ),
        (
            (
                "slow", "latency", "response time", "performance",
                "local model", "throughput", "overload",
            ),
            (
                "inference optimization", "model serving", "inference latency",
                "gpu inference", "performance engineering", "quantization",
                "throughput optimization",
            ),
        ),
        (
            (
                "context", "retain", "memory", "forget", "instruction",
                "agent",
            ),
            (
                "agent reliability", "agent memory", "context management",
                "llm agents", "tool use", "agent evaluation",
            ),
        ),
        (
            (
                "api", "integration", "salesforce", "enterprise",
            ),
            (
                "enterprise integration", "api platform",
                "integration engineering", "developer platform",
            ),
        ),
    )

    for triggers, additions in groups:
        if any(trigger in text for trigger in triggers):
            terms.update(additions)

    return sorted(terms)


def _buyer_proxy(candidate: ProblemCandidate) -> Any:
    expansion = " ".join(_buyer_capability_terms(candidate))
    return SimpleNamespace(
        id=candidate.id,
        title=candidate.title,
        problem_statement=(
            f"{candidate.problem_statement or ''} "
            f"BUYER_CAPABILITY_TERMS {expansion}"
        ),
        actor=candidate.actor,
        task=candidate.task,
        object=candidate.object,
        failure_mode=candidate.failure_mode,
        consequence=candidate.consequence,
        buyer_context=candidate.buyer_context,
        workaround=candidate.workaround,
    )


def _buyer_shortlist_fingerprint(
    case_id: int,
    matches: list[dict[str, Any]],
) -> str:
    # Cache identity must change when the evidence itself or the adjudication
    # contract changes. M13 keyed only on source ids, which allowed stale
    # INSUFFICIENT judgments to survive refreshed job text/ranking.
    parts = [BUYER_AI_CACHE_KEY, str(case_id)]
    for match in matches:
        evidence_blob = json.dumps(
            {
                "source": match.get("structured_source"),
                "id": match.get("id"),
                "company": match.get("company"),
                "title": match.get("title"),
                "text": str(match.get("text") or "")[:6000],
                "semantic_score": match.get("semantic_score"),
                "lexical_score": match.get("lexical_score"),
                "shared_terms": match.get("shared_terms") or [],
                "domain_shared": match.get("domain_shared") or [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        parts.append(hashlib.sha256(evidence_blob.encode("utf-8")).hexdigest())
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _buyer_shortlist_prompt(
    case: RadarCase,
    candidate: ProblemCandidate,
    matches: list[dict[str, Any]],
) -> str:
    case_payload = {
        "case_id": case.id,
        "title": candidate.title,
        "problem_statement": candidate.problem_statement,
        "actor": candidate.actor,
        "task": candidate.task,
        "object": candidate.object,
        "failure_mode": candidate.failure_mode,
        "consequence": candidate.consequence,
        "buyer_context": candidate.buyer_context,
        "capability_search_terms": _buyer_capability_terms(candidate),
    }

    jobs = []
    for idx, match in enumerate(matches, 1):
        jobs.append({
            "evidence_id": f"JOB_{idx}",
            "company": match.get("company"),
            "title": match.get("title"),
            "excerpt": str(match.get("text") or "")[:1800],
            "semantic_score": match.get("semantic_score"),
            "lexical_score": match.get("lexical_score"),
            "shared_terms": match.get("shared_terms", []),
            "domain_shared": match.get("domain_shared", []),
        })

    return f"""Judge the shortlist against atomic claim C05 buyer_exists.

CASE:
{json.dumps(case_payload, ensure_ascii=False, indent=2)}

ALREADY-RETRIEVED NAMED JOB EVIDENCE:
{json.dumps(jobs, ensure_ascii=False, indent=2)}

Choose SUPPORT only if at least one specific job clearly shows a named
organization allocating hiring budget to responsibilities directly aimed at
the concrete CASE problem or the operational capability that prevents,
measures, mitigates, or solves it.

Generic AI/ML hiring, generic software work, or merely using similar technology
is INSUFFICIENT.

Return valid JSON only:
{{
  "stance": "SUPPORT | INSUFFICIENT",
  "evidence_ids": ["CASE_{case.id}", "JOB_N"],
  "rationale": "1-3 skeptical sentences"
}}

If stance is SUPPORT, JOB_N must be the single strongest supporting job.
If stance is INSUFFICIENT, use CASE_{case.id} plus the strongest reviewed JOB_N.
Do not use outside knowledge and do not infer purchase intent or WTP.
"""


def _validate_shortlist_result(
    obj: Any,
    *,
    case_id: int,
    shortlist_size: int,
) -> tuple[bool, str, int | None]:
    if not isinstance(obj, dict):
        return False, "not_object", None

    stance = obj.get("stance")
    if stance not in {"SUPPORT", "INSUFFICIENT"}:
        return False, "bad_stance", None

    ids = obj.get("evidence_ids")
    if not isinstance(ids, list):
        return False, "bad_evidence_ids", None

    normalized = [str(x) for x in ids]
    if f"CASE_{case_id}" not in normalized:
        return False, "missing_case_id", None

    selected = None
    for value in normalized:
        m = re.fullmatch(r"JOB_(\d+)", value)
        if m:
            idx = int(m.group(1))
            if 1 <= idx <= shortlist_size:
                selected = idx
                break

    if selected is None:
        return False, "missing_valid_job_id", None

    if not str(obj.get("rationale") or "").strip():
        return False, "missing_rationale", None

    return True, "OK", selected


def _compact_ref(value: Any) -> str:
    raw = str(value or "")
    if len(raw) <= 180:
        return raw
    return raw[:120] + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _ai_candidate_reason(
    match: dict[str, Any],
) -> tuple[bool, str]:
    """Eligibility for shortlist review only, never SUPPORT."""
    if not _concrete_company(match.get("company")):
        return False, "missing_company"
    if not str(match.get("structured_source") or "").strip():
        return False, "not_structured"

    sem = float(match.get("semantic_score", 0) or 0)
    lex = float(match.get("lexical_score", 0) or 0)
    shared = {
        str(x).lower()
        for x in match.get("shared_terms", [])
        if str(x).lower() not in GENERIC_BUYER_TERMS
    }
    domains = set(match.get("domain_shared", []) or [])

    if sem >= 0.24 and (shared or domains):
        return True, "semantic_plus_capability"
    if sem >= 0.34:
        return True, "high_semantic"
    if lex >= 0.035 and len(shared) >= 2:
        return True, "lexical_capability_overlap"

    if sem < 0.18 and lex < 0.02:
        return False, "low_relevance"
    if not shared and not domains:
        return False, "generic_overlap_only"
    return False, "below_shortlist_threshold"


async def _buyer_ai_budget(
    session,
    *,
    case: RadarCase,
) -> RadarAIBudgetLedger:
    cycle_key = "buyer-ai:" + datetime.utcnow().strftime("%Y-%m-%d")
    row = (await session.execute(
        select(RadarAIBudgetLedger).where(
            RadarAIBudgetLedger.case_id == case.id,
            RadarAIBudgetLedger.cycle_key == cycle_key,
        )
    )).scalar_one_or_none()

    if row is None:
        cap = 0.30 if str(case.system_verdict or "").upper() in {
            "INVESTIGATE", "VALIDATE"
        } else 0.05
        row = RadarAIBudgetLedger(
            case_id=case.id,
            cycle_key=cycle_key,
            verdict_state=str(case.system_verdict or "WATCH").upper(),
            budget_cap_twd=cap,
            reserved_twd=0.0,
            spent_twd=0.0,
        )
        session.add(row)
        await session.flush()

    return row


GATE_SOURCE_GROUP = {
    "PAIN_MATERIALITY": "problem",
    "BUYER_REALITY": "buyer",
    "BUYER_REALITY_RECHECK": "buyer",
    "CURRENT_SOLUTION": "problem",
    "CURRENT_SOLUTION_RECHECK": "problem",
    "UNRESOLVED_GAP": "problem",
    "UNRESOLVED_GAP_RECHECK": "problem",
    "DIFFERENTIATION": "market",
    "DISTRIBUTION": "buyer",
    "ECONOMICS": "buyer",
    "OPPORTUNITY_WINDOW": "timing",
    "COMPETITION": "market",
    "SWITCHING": "market",
}

GROUP_SCRAPERS = {
    "buyer": BUYER_GROUP,
    "problem": PROBLEM_GROUP,
    "market": MARKET_GROUP,
    "timing": TIMING_GROUP,
}

GENERIC_BUYER_TERMS = {
    "ai", "model", "models", "software", "system", "systems", "data",
    "platform", "product", "products", "engineer", "engineering",
    "developer", "development", "team", "teams", "company", "business",
    "user", "users", "work", "working", "build", "building",
}

BUYER_RESPONSIBILITY_PATTERNS = (
    r"\breliab", r"\bquality\b", r"\bevaluat", r"\blatency\b",
    r"\bperformance\b", r"\binference\b", r"\bproduction\b",
    r"\bobservab", r"\bmonitor", r"\btool[- ]?use\b", r"\bagent",
    r"\bcontext\b", r"\baccuracy\b", r"\bcorrectness\b",
    r"\boptimization\b", r"\boptimiz", r"\bscalab", r"\bdeployment\b",
)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_refresh": {}, "cycles": 0}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"last_refresh": {}, "cycles": 0}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _due(state: dict[str, Any], group: str, force: bool) -> bool:
    if force:
        return True
    raw = (state.get("last_refresh") or {}).get(group)
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except Exception:
        return True
    hours = GROUP_COOLDOWN_HOURS.get(group, 12)
    return datetime.utcnow() - last >= timedelta(hours=hours)


def _scraper_backoff(
    state: dict[str, Any],
    name: str,
) -> tuple[bool, str | None]:
    block = (state.get("scraper_backoff") or {}).get(name)
    if not isinstance(block, dict):
        return False, None

    # M13 backoff entries were derived from CLI exit status. That could mark a
    # scraper failed even when its ScraperRun row completed successfully (for
    # example if the post-scrape summary crashed). Re-probe those legacy blocks
    # once under the M14 DB-backed health contract instead of starving a source
    # family for hours.
    if block.get("schema_version") != "m14-db-backed":
        return False, None

    raw = block.get("until")
    if not raw:
        return False, None
    try:
        until = datetime.fromisoformat(str(raw))
    except Exception:
        return False, None
    if datetime.utcnow() >= until:
        return False, None
    return True, until.isoformat(timespec="seconds")


def _record_scraper_result(
    state: dict[str, Any],
    result: dict[str, Any],
) -> None:
    name = str(result.get("name") or "")
    if not name:
        return
    status = str(result.get("status") or "").upper()
    backoff = state.setdefault("scraper_backoff", {})
    if status in {"PASS", "PASS_WITH_CLI_ERROR", "SUCCESS_ZERO"}:
        backoff.pop(name, None)
        return
    if status not in {"TIMEOUT", "FAILED", "ERROR"}:
        return

    previous = backoff.get(name) if isinstance(backoff.get(name), dict) else {}
    failures = int(previous.get("consecutive_failures", 0) or 0) + 1
    cap_hours = float(SCRAPER_BACKOFF_HOURS.get(name, 6))
    # Fast retry for transient source/network failures, exponential thereafter.
    # This avoids both hot-looping and the old six-hour starvation after one bad
    # probe.
    hours = min(cap_hours, 0.5 * (2 ** max(0, failures - 1)))
    backoff[name] = {
        "schema_version": "m14-db-backed",
        "status": status,
        "consecutive_failures": failures,
        "until": (
            datetime.utcnow() + timedelta(hours=hours)
        ).isoformat(timespec="seconds"),
        "last_error": result.get("error") or result.get("scraper_error"),
    }


async def _latest_scraper_run(scraper_name: str) -> dict[str, Any] | None:
    if not scraper_name:
        return None
    async with async_session() as session:
        row = (
            await session.execute(
                select(ScraperRun)
                .where(ScraperRun.scraper_name == scraper_name)
                .order_by(ScraperRun.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": int(row.id),
        "status": str(row.status or "").lower(),
        "records_fetched": int(row.records_fetched or 0),
        "records_new": int(row.records_new or 0),
        "records_updated": int(row.records_updated or 0),
        "error_message": str(row.error_message or ""),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _classify_scraper_process_result(
    *,
    name: str,
    returncode: int | None,
    before_run_id: int | None,
    after_run: dict[str, Any] | None,
    output_tail: str,
) -> dict[str, Any]:
    """Classify source health from the scraper's own DB lifecycle first.

    CLI exit code is secondary because main.py also prints a database summary
    after the scraper. A summary/terminal failure must not poison source health
    when ScraperRun says the scraper itself completed.
    """
    new_run = bool(
        after_run
        and int(after_run.get("id") or 0) > int(before_run_id or 0)
    )
    db_status = str((after_run or {}).get("status") or "").lower()
    base = {
        "name": name,
        "returncode": returncode,
        "scraper_run": after_run,
        "records_new": int((after_run or {}).get("records_new") or 0),
        "records_updated": int((after_run or {}).get("records_updated") or 0),
        "records_changed": int((after_run or {}).get("records_new") or 0) + int((after_run or {}).get("records_updated") or 0),
        "output_tail": output_tail[-4000:],
        "health_contract": "scraper_run_db_v1",
    }

    if new_run and db_status == "completed":
        status = "PASS" if returncode == 0 else "PASS_WITH_CLI_ERROR"
        return {**base, "status": status}
    if new_run and db_status == "failed":
        return {
            **base,
            "status": "FAILED",
            "scraper_error": (after_run or {}).get("error_message"),
        }
    if returncode == 0:
        # Some source adapters may not create ScraperRun rows. A clean child
        # process still counts as a successful probe, but the diagnostic makes
        # the absence visible.
        return {**base, "status": "PASS", "warning": "NO_NEW_SCRAPER_RUN_ROW"}
    return {
        **base,
        "status": "FAILED",
        "error": f"child process exited {returncode} without a completed ScraperRun",
    }


async def _run_scraper(name: str, timeout_seconds: int) -> dict[str, Any]:
    effective_timeout = min(
        int(timeout_seconds),
        int(SCRAPER_TIMEOUT_CAP_SECONDS.get(name, timeout_seconds)),
    )
    scraper_run_name = SCRAPER_RUN_NAME.get(name, name)
    before = await _latest_scraper_run(scraper_run_name)
    before_id = int((before or {}).get("id") or 0)

    runtime_progress.update(
        "source_refresh",
        detail=f"scraper:{name}",
        progress={"scraper": name, "timeout_seconds": effective_timeout},
        complete_previous=False,
    )
    print(
        f"  [source] {name}: START "
        f"(timeout={effective_timeout}s, health=ScraperRun)"
    )
    try:
        env = dict(os.environ)
        # Keep Windows child-process output deterministic and prevent the cp950
        # reader failures seen during M13 acceptance/debugging.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "main.py",
            "--scraper",
            name,
            cwd=str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        try:
            raw, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                raw, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                raw, _ = await proc.communicate()
            output = (raw or b"").decode("utf-8", errors="replace")
            print(f"  [source] {name}: TIMEOUT")
            runtime_progress.heartbeat(detail=f"scraper:{name}:TIMEOUT")
            return {
                "name": name,
                "status": "TIMEOUT",
                "returncode": None,
                "output_tail": output[-4000:],
                "health_contract": "scraper_run_db_v1",
            }

        output = (raw or b"").decode("utf-8", errors="replace")
        after = await _latest_scraper_run(scraper_run_name)
        result = _classify_scraper_process_result(
            name=name,
            returncode=proc.returncode,
            before_run_id=before_id,
            after_run=after,
            output_tail=output,
        )
        print(
            f"  [source] {name}: {result['status']} "
            f"returncode={proc.returncode} "
            f"records_new={int((after or {}).get('records_new') or 0)}"
        )
        runtime_progress.heartbeat(detail=f"scraper:{name}:{result['status']}")
        return result
    except Exception as exc:
        print(f"  [source] {name}: ERROR {type(exc).__name__}: {exc}")
        return {
            "name": name,
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "health_contract": "scraper_run_db_v1",
        }



async def _refresh_groups_parallel(
    *,
    source_groups: list[str],
    state: dict[str, Any],
    force_refresh: bool,
    timeout_seconds: int,
    groups_refreshed_this_cycle: set[str],
    groups_attempted_this_cycle: set[str],
    scrapers_refreshed_this_cycle: set[str],
) -> list[dict[str, Any]]:
    """Refresh independent source groups concurrently with shared scraper dedupe.

    The old scheduler waited for buyer -> problem -> timing sequentially. One
    jobs/news/packages timeout could therefore add minutes even though those
    collectors are independent. M15 runs groups concurrently while preserving
    per-group fallback order and success targets. A scraper shared by two groups
    (e.g. packages) executes at most once per cycle.
    """
    selected: list[str] = []
    skipped: list[dict[str, Any]] = []
    for group in source_groups:
        if group in groups_refreshed_this_cycle or group in groups_attempted_this_cycle:
            continue
        if not _due(state, group, force_refresh):
            skipped.append({"group": group, "status": "COOLDOWN"})
            continue
        selected.append(group)
        if len(selected) >= MAX_SOURCE_GROUPS_PER_CYCLE:
            break

    if not selected:
        return skipped

    task_cache: dict[str, asyncio.Task] = {}
    result_cache: dict[str, dict[str, Any]] = {}

    async def run_once(scraper: str, max_timeout_seconds: int | None = None) -> dict[str, Any]:
        if scraper in result_cache:
            return result_cache[scraper]
        if scraper in task_cache:
            return await task_cache[scraper]

        backed_off, until = _scraper_backoff(state, scraper)
        if backed_off and not force_refresh:
            result = {"name": scraper, "status": "BACKOFF", "until": until}
            result_cache[scraper] = result
            return result
        if scraper in scrapers_refreshed_this_cycle:
            result = {"name": scraper, "status": "ALREADY_REFRESHED_THIS_CYCLE"}
            result_cache[scraper] = result
            return result

        async def execute() -> dict[str, Any]:
            effective_group_timeout = int(timeout_seconds)
            if max_timeout_seconds is not None:
                effective_group_timeout = max(1, min(effective_group_timeout, int(max_timeout_seconds)))
            result = await _run_scraper(scraper, effective_group_timeout)
            scrapers_refreshed_this_cycle.add(scraper)
            _record_scraper_result(state, result)
            result_cache[scraper] = result
            return result

        task = asyncio.create_task(execute())
        task_cache[scraper] = task
        return await task

    async def refresh_group(group: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        pass_count = 0
        target = int(GROUP_SUCCESS_TARGET.get(group, 1))
        loop = asyncio.get_running_loop()
        started = loop.time()
        group_cap = int(GROUP_WALLCLOCK_CAP_SECONDS.get(group, timeout_seconds))
        for scraper in GROUP_SCRAPERS[group]:
            if pass_count >= target:
                rows.append({"name": scraper, "status": "SKIPPED_AFTER_SUCCESS_TARGET"})
                continue
            remaining = max(0, group_cap - int(loop.time() - started))
            if remaining <= 0:
                rows.append({
                    "name": scraper,
                    "status": "GROUP_TIME_BUDGET_EXHAUSTED",
                    "group_wallclock_cap_seconds": group_cap,
                })
                continue
            result = await run_once(scraper, max_timeout_seconds=remaining)
            rows.append(dict(result))
            if str(result.get("status") or "").upper() in {
                "PASS", "PASS_WITH_CLI_ERROR", "SUCCESS_ZERO"
            }:
                pass_count += 1
        return {
            "group": group,
            "status": "ATTEMPTED",
            "scrapers": rows,
            "pass_count": pass_count,
            "records_new": sum(int((row or {}).get("records_new", 0) or 0) for row in rows),
            "records_updated": sum(int((row or {}).get("records_updated", 0) or 0) for row in rows),
            "records_changed": sum(int((row or {}).get("records_changed", 0) or 0) for row in rows),
            "success_target": target,
            "wallclock_cap_seconds": group_cap,
            "wallclock_seconds": round(loop.time() - started, 3),
            "degraded_cache_fallback_legal": pass_count < target,
        }

    attempted = await asyncio.gather(*(refresh_group(g) for g in selected))
    for row in attempted:
        group = str(row.get("group") or "")
        groups_attempted_this_cycle.add(group)
        if int(row.get("pass_count", 0) or 0) > 0:
            groups_refreshed_this_cycle.add(group)
            state.setdefault("last_refresh", {})[group] = datetime.utcnow().isoformat(timespec="seconds")
    _save_state(state)
    return skipped + list(attempted)


def _claim_prefetch_rows(
    rows: list[dict[str, Any]],
    *,
    claim_code: str,
    forced_gate: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Prepare later-gate evidence without changing the current decision gate."""
    candidates = []
    for row in rows:
        if not bool(((row.get("production_admission") or {}).get("machine_research_eligible"))):
            continue
        state = str((row.get("claims") or {}).get(claim_code) or "UNKNOWN").upper()
        if state in {"SUPPORTED", "REFUTED"}:
            continue
        if str(row.get("decision_verdict") or "").upper() == "IGNORE":
            continue
        copy = dict(row)
        copy["current_gate"] = forced_gate
        candidates.append(copy)
    candidates.sort(
        key=lambda r: (
            -float(r.get("attention_score", 0) or 0),
            int(r.get("case_id", 0) or 0),
        )
    )
    return candidates[: max(0, int(limit))]

def _concrete_company(value: Any) -> str | None:
    name = str(value or "").strip()
    if not name:
        return None
    if name.lower() in {
        "unknown", "none", "confidential", "undisclosed",
        "stealth", "stealth startup", "n/a", "nan",
    }:
        return None
    return name[:255]


def _nested_value(data: Any, path: tuple[str, ...]) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _company_from_ats_url(url: Any) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        parts = [x for x in parsed.path.split("/") if x]
    except Exception:
        return None

    slug = None
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts:
        slug = parts[0]
    elif host == "jobs.lever.co" and parts:
        slug = parts[0]
    elif host == "jobs.ashbyhq.com" and parts:
        slug = parts[0]

    if not slug:
        return None

    cleaned = re.sub(r"[-_]+", " ", slug).strip()
    return _concrete_company(cleaned.title())


def _job_company(row: JobListing) -> tuple[str | None, str]:
    direct = _concrete_company(getattr(row, "company", None))
    if direct:
        return direct, "job_listings.company"

    raw = getattr(row, "raw_metadata", None)
    if not isinstance(raw, dict):
        raw = {}

    paths = (
        ("company",),
        ("company_name",),
        ("companyName",),
        ("employer",),
        ("employer_name",),
        ("employerName",),
        ("organization",),
        ("organization_name",),
        ("hiringOrganization", "name"),
        ("company", "name"),
        ("employer", "name"),
    )

    for path in paths:
        value = _nested_value(raw, path)
        company = _concrete_company(value)
        if company:
            return company, "raw_metadata." + ".".join(path)

    company = _company_from_ats_url(getattr(row, "url", None))
    if company:
        return company, "ats_url"

    company = _company_from_ats_url(getattr(row, "apply_url", None))
    if company:
        return company, "ats_apply_url"

    return None, "missing"


def _buyer_text_alignment(
    candidate: ProblemCandidate,
    match: dict[str, Any],
) -> tuple[bool, list[str]]:
    shared = {
        str(x).lower()
        for x in match.get("shared_terms", [])
        if str(x).lower() not in GENERIC_BUYER_TERMS
    }
    rare = {
        str(x).lower()
        for x in match.get("rare_shared", [])
        if str(x).lower() not in GENERIC_BUYER_TERMS
    }
    named = {
        str(x).lower()
        for x in match.get("named_shared", [])
        if str(x).lower() not in GENERIC_BUYER_TERMS
    }
    domains = set(match.get("domain_shared", []) or [])

    sem = float(match.get("semantic_score", 0) or 0)
    lex = float(match.get("lexical_score", 0) or 0)
    text = str(match.get("text") or "")

    responsibility = any(
        re.search(pattern, text, re.I)
        for pattern in BUYER_RESPONSIBILITY_PATTERNS
    )

    strong_identity = bool(
        named
        or len(rare) >= 2
        or (
            domains
            and len(shared) >= 2
            and sem >= 0.36
            and lex >= 0.045
        )
    )

    # A job listing is real budget allocation, but only support C05 when
    # its responsibilities are strongly aligned with the candidate's
    # concrete capability/problem area.
    accepted = bool(
        strong_identity
        and responsibility
        and sem >= 0.30
    )

    reasons = []
    if named:
        reasons.append("named_anchor")
    if len(rare) >= 2:
        reasons.append("rare_term_overlap")
    if domains:
        reasons.append("domain_overlap")
    if responsibility:
        reasons.append("problem_responsibility")
    if sem >= 0.30:
        reasons.append("semantic_alignment")

    return accepted, reasons


async def _focused_buyer_research(
    target_rows: list[dict[str, Any]],
    *,
    ai_call_allowance: int = MAX_BUYER_AI_CALLS_PER_CYCLE,
    force_structured_refresh: bool = False,
) -> dict[str, Any]:
    target_ids = {
        int(row["case_id"])
        for row in target_rows
        if row.get("current_gate") in {
            "BUYER_REALITY", "BUYER_REALITY_RECHECK"
        }
    }
    runtime_progress.heartbeat(
        detail="c05 buyer targets accepted",
        progress={
            "cases_completed": 0,
            "cases_total": len(target_ids),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )
    if not target_ids:
        return {
            "cases": 0,
            "support_links": 0,
            "companies": {},
            "reviewed_matches": 0,
            "job_corpus_size": 0,
            "corpus_diagnostics": {},
        }

    async with async_session() as session:
        pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .where(RadarCase.id.in_(target_ids))
        )).all())

        claims = list((await session.execute(
            select(RadarClaim).where(
                RadarClaim.case_id.in_(target_ids),
                RadarClaim.claim_code == "C05",
            )
        )).scalars().all())
        claim_map = {c.case_id: c for c in claims}

        jobs = list((await session.execute(
            select(JobListing)
            .order_by(JobListing.created_at.desc())
            .limit(4000)
        )).scalars().all())

    runtime_progress.heartbeat(
        detail="c05 buyer corpus loaded",
        progress={
            "cases_completed": 0,
            "cases_total": len(pairs),
            "job_rows": len(jobs),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    if not jobs or not pairs:
        return {
            "cases": len(pairs),
            "support_links": 0,
            "companies": {},
            "reviewed_matches": 0,
        }

    def safe_json(value: Any) -> str:
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "")

    job_docs = []
    corpus_diagnostics = {
        "db_rows_loaded": len(jobs),
        "recent_rows": 0,
        "with_company": 0,
        "without_company": 0,
        "company_sources": {},
        "usable_docs": 0,
    }

    for row in jobs:
        published = row.published_at
        if isinstance(published, datetime):
            # Normalize aware timestamps for a safe age comparison.
            try:
                cutoff_now = (
                    datetime.now(published.tzinfo)
                    if published.tzinfo is not None
                    else datetime.utcnow()
                )
                if published < cutoff_now - timedelta(days=240):
                    continue
            except Exception:
                pass

        corpus_diagnostics["recent_rows"] += 1

        company, company_source = _job_company(row)
        if company:
            corpus_diagnostics["with_company"] += 1
            src_counts = corpus_diagnostics["company_sources"]
            src_counts[company_source] = src_counts.get(company_source, 0) + 1
        else:
            corpus_diagnostics["without_company"] += 1

        # Do NOT discard a job merely because company identity is missing.
        # It is still useful for retrieval / demand context, but it can never
        # create C05 SUPPORT until a concrete organization is established.
        text = " ".join([
            row.title or "",
            company or "",
            row.department or "",
            row.description or "",
            safe_json(row.tags),
            safe_json(row.raw_metadata),
        ]).strip()

        if len(text) < 20:
            continue

        job_docs.append({
            "id": row.id,
            "text": text,
            "title": row.title or "",
            "url": row.url,
            "published_at": row.published_at,
            "company": company,
            "company_source": company_source,
            "row": row,
        })

    corpus_diagnostics["legacy_usable_docs"] = len(job_docs)

    structured = await fetch_structured_buyer_jobs(force=force_structured_refresh)
    structured_rows = structured.get("rows", []) or []
    structured_named = 0
    structured_by_source = {}
    structured_job_docs = []

    for item in structured_rows:
        company = _concrete_company(item.get("company"))
        if not company:
            continue

        source = str(item.get("source") or "structured_jobs")
        structured_by_source[source] = structured_by_source.get(source, 0) + 1
        structured_named += 1

        published = None
        raw_published = item.get("published_at")
        if raw_published:
            try:
                published = datetime.fromisoformat(str(raw_published))
            except Exception:
                published = None

        structured_doc = {
            "id": f"{source}:{item.get('external_id')}",
            "text": str(item.get("text") or ""),
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "published_at": published,
            "company": company,
            "company_source": f"structured:{source}",
            "structured_source": source,
            "source_metadata": item.get("metadata") or {},
            "row": None,
        }
        job_docs.append(structured_doc)
        structured_job_docs.append(structured_doc)

    corpus_diagnostics["structured_cache_hit"] = bool(
        structured.get("cache_hit", False)
    )
    corpus_diagnostics["structured_forced_refresh"] = bool(
        force_structured_refresh
    )
    corpus_diagnostics["structured_requests"] = int(
        structured.get("request_count", 0) or 0
    )
    corpus_diagnostics["structured_named"] = structured_named
    corpus_diagnostics["structured_by_source"] = structured_by_source
    corpus_diagnostics["structured_status"] = (
        structured.get("source_status") or {}
    )
    corpus_diagnostics["usable_docs"] = len(job_docs)
    corpus_diagnostics["with_company"] += structured_named
    runtime_progress.heartbeat(
        detail="c05 structured buyer sources ready",
        progress={
            "cases_completed": 0,
            "cases_total": len(pairs),
            "job_rows": len(job_docs),
            "structured_named": structured_named,
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    candidates = [candidate for _, candidate in pairs]
    matches = _match_rows(
        candidates,
        job_docs,
        threshold=0.075,
        top_k=15,
        role="buyer",
    )

    # Separate named-structured retrieval for AI candidate generation.
    # This is candidate generation only; semantic similarity cannot create
    # evidence or SUPPORT by itself.
    buyer_proxies = [_buyer_proxy(candidate) for candidate in candidates]
    structured_ai_matches = _match_rows(
        buyer_proxies,
        structured_job_docs,
        threshold=0.012,
        top_k=12,
        role="buyer",
    ) if structured_job_docs else {}
    runtime_progress.heartbeat(
        detail="c05 buyer retrieval ready",
        progress={
            "cases_completed": 0,
            "cases_total": len(pairs),
            "job_rows": len(job_docs),
            "matched_cases": len(matches),
            "ai_calls": 0,
            "ai_allowance": int(ai_call_allowance),
        },
    )

    support_links = 0
    reviewed_matches = 0
    companies_by_case: dict[int, list[str]] = defaultdict(list)

    buyer_ai_calls = 0
    buyer_ai_cache_hits = 0
    buyer_ai_support = 0
    buyer_ai_insufficient = 0
    buyer_ai_gate_denied = 0
    buyer_ai_deferred = 0
    buyer_ai_errors = 0
    buyer_ai_tokens = 0
    buyer_ai_cost_twd = 0.0
    buyer_ai_candidate_cases = 0
    buyer_ai_prefilter_rejects: dict[str, int] = defaultdict(int)
    buyer_ai_selected: dict[int, dict[str, Any]] = {}
    task_spec = get_ai_task("claim_stance_classify")

    async with async_session() as session:
        # Reload ORM objects in this write session.
        session_pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(
                ProblemCandidate,
                ProblemCandidate.id == RadarCase.candidate_id,
            )
            .where(RadarCase.id.in_(target_ids))
        )).all())
        session_claims = list((await session.execute(
            select(RadarClaim).where(
                RadarClaim.case_id.in_(target_ids),
                RadarClaim.claim_code == "C05",
            )
        )).scalars().all())
        session_claim_map = {c.case_id: c for c in session_claims}

        for buyer_case_index, (case, candidate) in enumerate(session_pairs, 1):
            runtime_progress.heartbeat(
                detail="c05 buyer case verification",
                progress={
                    "cases_completed": buyer_case_index - 1,
                    "cases_total": len(session_pairs),
                    "case_id": int(case.id),
                    "ai_calls": buyer_ai_calls,
                    "ai_allowance": int(ai_call_allowance),
                },
            )
            claim = session_claim_map.get(case.id)
            if not claim:
                continue

            seen_companies = set()

            for match in matches.get(candidate.id, []):
                reviewed_matches += 1
                company = _concrete_company(match.get("company"))
                if company and company.lower() in seen_companies:
                    continue

                accepted, reasons = _buyer_text_alignment(
                    candidate,
                    match,
                )
                deterministic_candidate = bool(accepted)

                # Production integrity rule: deterministic retrieval may
                # nominate a buyer candidate, but cannot directly prove C05.
                # Narrow semantic adjudication owns SUPPORT.
                if deterministic_candidate:
                    reasons = list(reasons) + [
                        "requires_narrow_ai_confirmation"
                    ]
                accepted = False

                # C05 is about an economic buyer. A semantically relevant
                # anonymous job can be demand context, but cannot prove a buyer.
                if not company:
                    accepted = False
                    reasons = list(reasons) + ["missing_concrete_organization"]

                structured_source = str(
                    match.get("structured_source") or ""
                ).strip()
                evidence_source_type = (
                    f"buyer_jobs:{structured_source}"
                    if structured_source
                    else "jobs"
                )
                evidence_source_table = (
                    "structured_buyer_cache"
                    if structured_source
                    else "job_listings"
                )

                ev = await _ensure_evidence(
                    session,
                    case.id,
                    source_type=evidence_source_type,
                    source_table=evidence_source_table,
                    source_ref=str(match["id"]),
                    source_title=match.get("title") or "",
                    excerpt=str(match.get("text") or "")[:8000],
                    source_url=match.get("url"),
                    source_family_key=(
                        (
                            f"{structured_source}:"
                            if structured_source
                            else "jobs:"
                        )
                        + (
                            re.sub(
                                r"[^a-z0-9._-]+",
                                "-",
                                company.lower(),
                            ).strip("-")[:120]
                            if company
                            else "anonymous-source"
                        )
                    ),
                    authority_class="BUYER_BUDGET_SIGNAL",
                    directness="RELATED",
                    published_at=match.get("published_at"),
                    metadata={
                        "engine_version": ENGINE_VERSION,
                        "company": company,
                        "company_source": match.get("company_source", "missing"),
                        "structured_source": structured_source or None,
                        "source_metadata": match.get("source_metadata") or {},
                        "research_mode": "focused_buyer",
                        "retrieval_score": match.get("retrieval_score"),
                        "lexical_score": match.get("lexical_score"),
                        "semantic_score": match.get("semantic_score"),
                        "shared_terms": match.get("shared_terms", []),
                        "rare_shared": match.get("rare_shared", []),
                        "named_shared": match.get("named_shared", []),
                        "domain_shared": match.get("domain_shared", []),
                        "acceptance_reasons": reasons,
                    },
                )

                new_link = await _link_claim(
                    session,
                    claim,
                    ev,
                    stance="SUPPORT" if accepted else "INSUFFICIENT",
                    rationale=(
                        "Named organization is allocating hiring budget to "
                        "responsibilities strongly aligned with this "
                        "problem/capability. This supports buyer existence "
                        "only; it does not prove purchase intent or WTP."
                        if accepted
                        else
                        "Named hiring activity was retrieved, but concrete "
                        "problem/capability alignment is not strong enough "
                        "to prove buyer existence."
                    ),
                    confidence=0.79 if accepted else 0.52,
                )
                support_links += int(new_link and accepted)

                if accepted and company:
                    seen_companies.add(company.lower())
                    companies_by_case[case.id].append(company)

                if len(seen_companies) >= 3:
                    break

            # Dedicated Stage 2 — shortlist AI adjudication.
            # Deterministic SUPPORT rules remain unchanged. AI sees only a
            # small shortlist of named, already-retrieved jobs and selects
            # strongest evidence or abstains.
            ranked = structured_ai_matches.get(candidate.id, []) or []
            shortlist = []
            for candidate_match in ranked:
                eligible, reason = _ai_candidate_reason(candidate_match)
                if eligible:
                    candidate_match = dict(candidate_match)
                    candidate_match["ai_candidate_reason"] = reason
                    shortlist.append(candidate_match)
                    if len(shortlist) >= 5:
                        break
                else:
                    buyer_ai_prefilter_rejects[reason] += 1

            source_status = corpus_diagnostics.get(
                "structured_status", {}
            ) or {}
            passed_sources = [
                source
                for source, status in source_status.items()
                if status.get("status") == "PASS"
            ]

            ai_result = None
            selected_idx = None
            shortlist_fp = (
                _buyer_shortlist_fingerprint(case.id, shortlist)
                if shortlist
                else None
            )

            if not seen_companies and shortlist:
                buyer_ai_candidate_cases += 1
                buyer_ai_selected[case.id] = {
                    "company": shortlist[0].get("company"),
                    "title": shortlist[0].get("title"),
                    "reason": shortlist[0].get(
                        "ai_candidate_reason"
                    ),
                    "semantic_score": shortlist[0].get(
                        "semantic_score"
                    ),
                    "lexical_score": shortlist[0].get(
                        "lexical_score"
                    ),
                    "shortlist_size": len(shortlist),
                }

                es_existing = dict(claim.evidence_summary or {})
                cached = es_existing.get(
                    "buyer_shortlist_ai_v2"
                )
                cached_at = None
                if isinstance(cached, dict):
                    try:
                        cached_at = datetime.fromisoformat(
                            str(cached.get("adjudicated_at") or "")
                        )
                    except Exception:
                        cached_at = None
                cached_result = (cached or {}).get("result") if isinstance(cached, dict) else None
                cached_stance = str(
                    (cached_result or {}).get("stance") or ""
                ).upper() if isinstance(cached_result, dict) else ""
                negative_cache_fresh = bool(
                    cached_stance != "INSUFFICIENT"
                    or (
                        cached_at is not None
                        and datetime.utcnow() - cached_at < timedelta(hours=24)
                    )
                )

                if (
                    isinstance(cached, dict)
                    and cached.get("contract_version") == BUYER_AI_CACHE_KEY
                    and cached.get("fingerprint") == shortlist_fp
                    and cached.get("validation") == "OK"
                    and negative_cache_fresh
                ):
                    buyer_ai_cache_hits += 1
                    ai_result = cached.get("result") or {}
                    _, _, selected_idx = _validate_shortlist_result(
                        ai_result,
                        case_id=case.id,
                        shortlist_size=len(shortlist),
                    )
                elif buyer_ai_calls >= ai_call_allowance:
                    buyer_ai_deferred += 1
                else:
                    budget = await _buyer_ai_budget(
                        session,
                        case=case,
                    )
                    remaining = max(
                        0.0,
                        float(budget.budget_cap_twd or 0)
                        - float(budget.spent_twd or 0)
                        - float(budget.reserved_twd or 0),
                    )

                    gate = evaluate_ai_gate(
                        task_name="claim_stance_classify",
                        local_attempted=True,
                        local_result="AMBIGUOUS",
                        estimated_call_cost_twd=(
                            ESTIMATED_BUYER_AI_CALL_TWD
                        ),
                        remaining_case_budget_twd=remaining,
                        decision_impact=0.90,
                    )

                    if not gate.allowed:
                        buyer_ai_gate_denied += 1
                    else:
                        usage = TokenUsage()
                        buyer_ai_calls += 1
                        try:
                            runtime_progress.heartbeat(
                                detail="c05 buyer AI adjudication",
                                progress={
                                    "cases_completed": buyer_case_index - 1,
                                    "cases_total": len(session_pairs),
                                    "case_id": int(case.id),
                                    "ai_calls": buyer_ai_calls,
                                    "ai_allowance": int(ai_call_allowance),
                                    "shortlist_size": len(shortlist),
                                },
                            )
                            ai_result = await call_llm(
                                prompt=_buyer_shortlist_prompt(
                                    case,
                                    candidate,
                                    shortlist,
                                ),
                                system_message=BUYER_AI_SYSTEM,
                                model=str(
                                    task_spec.get("model_tier")
                                    or "mini"
                                ),
                                temperature=0.0,
                                max_tokens=min(
                                    500,
                                    int(
                                        task_spec.get("max_tokens")
                                        or 600
                                    ),
                                ),
                                parse_json=True,
                                usage_tracker=usage,
                            )

                            valid, validation, selected_idx = (
                                _validate_shortlist_result(
                                    ai_result,
                                    case_id=case.id,
                                    shortlist_size=len(shortlist),
                                )
                            )

                            cost_twd = (
                                usage.estimated_cost_usd
                                * USD_TWD_RATE
                            )
                            budget.spent_twd = (
                                float(budget.spent_twd or 0)
                                + cost_twd
                            )
                            buyer_ai_tokens += int(
                                usage.total_tokens or 0
                            )
                            buyer_ai_cost_twd += cost_twd

                            es_existing["buyer_shortlist_ai_v2"] = {
                                "contract_version": BUYER_AI_CACHE_KEY,
                                "fingerprint": shortlist_fp,
                                "validation": (
                                    "OK" if valid else validation
                                ),
                                "result": ai_result,
                                "task": "claim_stance_classify",
                                "adjudicated_at": (
                                    datetime.utcnow().isoformat()
                                ),
                                "cost_twd": round(cost_twd, 6),
                            }
                            claim.evidence_summary = es_existing

                            if not valid:
                                buyer_ai_errors += 1
                                ai_result = None
                                selected_idx = None

                        except Exception as exc:
                            if usage.calls:
                                cost_twd = (
                                    usage.estimated_cost_usd
                                    * USD_TWD_RATE
                                )
                                budget.spent_twd = (
                                    float(budget.spent_twd or 0)
                                    + cost_twd
                                )
                                buyer_ai_tokens += int(
                                    usage.total_tokens or 0
                                )
                                buyer_ai_cost_twd += cost_twd

                            buyer_ai_errors += 1
                            es_existing["buyer_shortlist_ai_v2"] = {
                                "contract_version": BUYER_AI_CACHE_KEY,
                                "fingerprint": shortlist_fp,
                                "validation": "AI_ERROR",
                                "error": (
                                    f"{type(exc).__name__}: {exc}"
                                ),
                                "adjudicated_at": (
                                    datetime.utcnow().isoformat()
                                ),
                            }
                            claim.evidence_summary = es_existing
                            ai_result = None
                            selected_idx = None

                if ai_result and selected_idx is not None:
                    selected_match = shortlist[selected_idx - 1]
                    stance = str(
                        ai_result.get("stance") or "INSUFFICIENT"
                    )
                    company = _concrete_company(
                        selected_match.get("company")
                    )
                    structured_source = str(
                        selected_match.get(
                            "structured_source"
                        ) or ""
                    ).strip()

                    selected_ev = await _ensure_evidence(
                        session,
                        case.id,
                        source_type=(
                            f"buyer_jobs:{structured_source}"
                        ),
                        source_table="structured_buyer_cache",
                        source_ref=_compact_ref(
                            selected_match.get("id")
                        ),
                        source_title=(
                            selected_match.get("title") or ""
                        ),
                        excerpt=str(
                            selected_match.get("text") or ""
                        )[:8000],
                        source_url=selected_match.get("url"),
                        source_family_key=(
                            f"{structured_source}:"
                            + re.sub(
                                r"[^a-z0-9._-]+",
                                "-",
                                (company or "unknown").lower(),
                            ).strip("-")[:120]
                        ),
                        authority_class="BUYER_BUDGET_SIGNAL",
                        # A narrow adjudicator may promote directness only after
                        # selecting a concrete named organization and explicitly
                        # judging the supplied responsibilities as C05 SUPPORT.
                        # Generic retrieval above remains RELATED/INSUFFICIENT.
                        directness=("DIRECT" if stance == "SUPPORT" else "RELATED"),
                        published_at=selected_match.get(
                            "published_at"
                        ),
                        metadata={
                            "engine_version": ENGINE_VERSION,
                            "company": company,
                            "structured_source": (
                                structured_source
                            ),
                            "research_mode": (
                                "buyer_shortlist_ai"
                            ),
                            "shortlist_fingerprint": (
                                shortlist_fp
                            ),
                            "shortlist_size": len(shortlist),
                            "ai_selected_index": selected_idx,
                            "semantic_score": (
                                selected_match.get(
                                    "semantic_score"
                                )
                            ),
                            "lexical_score": (
                                selected_match.get(
                                    "lexical_score"
                                )
                            ),
                            "shared_terms": (
                                selected_match.get(
                                    "shared_terms", []
                                )
                            ),
                            "domain_shared": (
                                selected_match.get(
                                    "domain_shared", []
                                )
                            ),
                        },
                    )

                    created = await _link_claim(
                        session,
                        claim,
                        selected_ev,
                        stance=stance,
                        rationale=(
                            "Narrow AI shortlist adjudication "
                            "using only already-retrieved named "
                            "job evidence: "
                            + str(
                                ai_result.get("rationale") or ""
                            )
                        ),
                        confidence=(
                            0.80
                            if stance == "SUPPORT"
                            else 0.70
                        ),
                    )

                    if stance == "SUPPORT":
                        support_links += int(created)
                        buyer_ai_support += 1
                        if company:
                            seen_companies.add(
                                company.lower()
                            )
                            companies_by_case[
                                case.id
                            ].append(company)
                    else:
                        buyer_ai_insufficient += 1

            await _refresh_claim_state(session, claim)

            # Research exhaustion is NOT refutation. It only means this
            # currently configured source set has been searched thoroughly
            # enough that repeatedly spending on the same gate has low VOI.
            es = dict(claim.evidence_summary or {})
            if str(claim.state or "").upper() == "SUPPORTED":
                es["buyer_research_status_v1"] = {
                    "status": "SUPPORTED",
                    "structured_named": (
                        corpus_diagnostics.get(
                            "structured_named", 0
                        )
                    ),
                    "source_families": passed_sources,
                    "updated_at": (
                        datetime.utcnow().isoformat()
                    ),
                }
            elif (
                int(
                    corpus_diagnostics.get(
                        "structured_named", 0
                    ) or 0
                ) >= 500
                and len(passed_sources) >= 2
                and (
                    (
                        ai_result
                        and ai_result.get("stance")
                        == "INSUFFICIENT"
                    )
                    or not shortlist
                )
            ):
                es["buyer_research_status_v1"] = {
                    "status": "SOURCE_SET_EXHAUSTED",
                    "structured_named": (
                        corpus_diagnostics.get(
                            "structured_named", 0
                        )
                    ),
                    "source_families": passed_sources,
                    "shortlist_size": len(shortlist),
                    "reason": (
                        "AI_SHORTLIST_INSUFFICIENT"
                        if shortlist
                        else "NO_RELEVANT_SHORTLIST"
                    ),
                    "reviewed_at": (
                        datetime.utcnow().isoformat()
                    ),
                    "recheck_after": (
                        datetime.utcnow()
                        + timedelta(days=7)
                    ).isoformat(),
                    "warning": (
                        "This is source-set exhaustion, "
                        "not proof that no buyer exists."
                    ),
                }
            claim.evidence_summary = es


            es = dict(claim.evidence_summary or {})
            es["focused_buyer_research_v1"] = {
                "engine_version": ENGINE_VERSION,
                "accepted_companies": companies_by_case.get(case.id, []),
                "job_corpus_size": len(job_docs),
            }
            claim.evidence_summary = es

        runtime_progress.heartbeat(
            detail="c05 buyer verification complete",
            progress={
                "cases_completed": len(session_pairs),
                "cases_total": len(session_pairs),
                "ai_calls": buyer_ai_calls,
                "ai_allowance": int(ai_call_allowance),
                "support_links": support_links,
            },
        )
        await session.commit()

    return {
        "cases": len(target_ids),
        "support_links": support_links,
        "companies": {
            str(k): v for k, v in companies_by_case.items()
        },
        "reviewed_matches": reviewed_matches,
        "job_corpus_size": len(job_docs),
        "corpus_diagnostics": corpus_diagnostics,
        "ai_calls": buyer_ai_calls,
        "ai_cache_hits": buyer_ai_cache_hits,
        "ai_support": buyer_ai_support,
        "ai_insufficient": buyer_ai_insufficient,
        "ai_gate_denied": buyer_ai_gate_denied,
        "ai_deferred": buyer_ai_deferred,
        "ai_errors": buyer_ai_errors,
        "ai_tokens": buyer_ai_tokens,
        "ai_cost_twd": round(buyer_ai_cost_twd, 6),
        "ai_candidate_cases": buyer_ai_candidate_cases,
        "ai_prefilter_rejects": dict(buyer_ai_prefilter_rejects),
        "ai_selected": {
            str(k): v for k, v in buyer_ai_selected.items()
        },
    }


def _snapshot(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in result.get("rows", []):
        out[int(row["case_id"])] = {
            "verdict": row.get("decision_verdict"),
            "gate": row.get("current_gate"),
            "claims": dict(row.get("claims", {})),
            "title": row.get("title"),
        }
    return out


def _changes(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for case_id in sorted(set(before) | set(after)):
        a = before.get(case_id, {})
        b = after.get(case_id, {})
        if (
            a.get("verdict") != b.get("verdict")
            or a.get("gate") != b.get("gate")
            or a.get("claims") != b.get("claims")
        ):
            rows.append({
                "case_id": case_id,
                "title": b.get("title") or a.get("title"),
                "before_verdict": a.get("verdict"),
                "after_verdict": b.get("verdict"),
                "before_gate": a.get("gate"),
                "after_gate": b.get("gate"),
            })
    return rows


GATE_RESEARCH_PRIORITY = {
    "UNRESOLVED_GAP": 100,
    "UNRESOLVED_GAP_RECHECK": 96,
    "CURRENT_SOLUTION": 92,
    "CURRENT_SOLUTION_RECHECK": 88,
    "BUYER_REALITY": 78,
    "BUYER_REALITY_RECHECK": 74,
    "PAIN_MATERIALITY": 60,
    "DIFFERENTIATION": 50,
    "OPPORTUNITY_WINDOW": 45,
    "COMPETITION": 40,
}


def _ordered_targets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            int(((row.get("production_admission") or {}).get("priority_tier", 9)) or 9),
            -GATE_RESEARCH_PRIORITY.get(
                str(row.get("current_gate") or ""),
                0,
            ),
            -float(row.get("attention_score", 0) or 0),
            int(row.get("case_id", 0) or 0),
        ),
    )


def _target_count(
    rows: list[dict[str, Any]],
    gates: set[str],
) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("current_gate") or "") in gates
    )


FAST_GATE_ORDER = [
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

FAST_MACHINE_ACTION = {
    "PAIN_MATERIALITY": "find direct cost/blocking consequence evidence",
    "BUYER_REALITY": "find a named buyer that owns or budgets for this exact job",
    "CURRENT_SOLUTION": "search solution complaints, failures, and workarounds",
    "UNRESOLVED_GAP": "verify the gap persists despite current solutions",
    "COMPANY_REALITY": "resolve missing execution capability evidence",
    "DIFFERENTIATION": "form and falsify a concrete differentiation wedge",
    "DISTRIBUTION": "identify and test a credible customer-acquisition channel",
    "ECONOMICS": "estimate price/WTP, build cost, support cost, and gross margin",
    "OPPORTUNITY_WINDOW": "estimate execution time against the opportunity window",
    "COMPETITION": "search counterevidence and competitive responses",
    "SWITCHING": "test whether users will switch/adopt/pay",
    "DECISION_READY": "prepare final build gate",
}


def _fast_next_gate(claims: dict[str, str]) -> tuple[str, str]:
    for code, gate in FAST_GATE_ORDER:
        if str(claims.get(code, "UNKNOWN")).upper() not in {"SUPPORTED", "REFUTED"}:
            return gate, code
    return "DECISION_READY", ""


async def _load_fast_cycle_state(*, limit: int = 50) -> dict[str, Any]:
    """Read persisted claim/case truth without rebuilding Reality.

    M15 spent ~300-500s per cycle rebuilding the same idempotent Reality graph
    before source work and again immediately after C03. M16 uses the durable
    RadarCase/RadarClaim state for those intermediate scheduling snapshots and
    reserves the full Reality+Decision rebuild for the final product decision.
    """
    async with async_session() as session:
        pairs = list((await session.execute(
            select(RadarCase, ProblemCandidate)
            .join(ProblemCandidate, ProblemCandidate.id == RadarCase.candidate_id)
            .order_by(RadarCase.id)
        )).all())
        case_ids = [int(case.id) for case, _ in pairs]
        claim_rows = list((await session.execute(
            select(RadarClaim).where(RadarClaim.case_id.in_(case_ids))
        )).scalars().all()) if case_ids else []
        c02_action_rows = list((await session.execute(
            select(RadarResearchAction)
            .where(
                RadarResearchAction.case_id.in_(case_ids),
                RadarResearchAction.claim_code == "C02",
            )
            .order_by(RadarResearchAction.id)
        )).scalars().all()) if case_ids else []

    claims_by_case: dict[int, dict[str, str]] = defaultdict(dict)
    research_status_by_case: dict[int, dict[str, str]] = defaultdict(dict)
    for claim in claim_rows:
        code = str(claim.claim_code)
        claims_by_case[int(claim.case_id)][code] = str(claim.state or "UNKNOWN").upper()
        summary = dict(claim.evidence_summary or {})
        block = None
        if code == "C05":
            block = summary.get("buyer_research_status_v1")
        elif code == "C06":
            block = summary.get("solution_research_status_v1")
        elif code == "C07":
            block = summary.get("gap_research_status_v1")
        elif code in {"C08", "C10", "C11", "C12", "C13", "C14"}:
            block = summary.get("parallel_reality_v2") or summary.get("parallel_reality_v1")
        if isinstance(block, dict):
            status = str(block.get("status") or "").upper()
            if status:
                research_status_by_case[int(claim.case_id)][code] = status

    latest_c02_action: dict[int, RadarResearchAction] = {}
    for action in c02_action_rows:
        latest_c02_action[int(action.case_id)] = action

    rows = []
    verdict_counts: dict[str, int] = defaultdict(int)
    for case, candidate in pairs:
        claims = dict(claims_by_case.get(int(case.id), {}))
        gate, next_claim = _fast_next_gate(claims)
        verdict = str(case.system_verdict or "WATCH").upper()
        verdict_counts[verdict] += 1

        attention = int(max(
            float(candidate.market_score or 0),
            float(candidate.community_problem_score or 0),
            float(candidate.confidence_score or 0),
        ))
        boundary = (
            "FOUNDER_ACTION_NOW"
            if verdict == "VALIDATE"
            else "MACHINE_RESEARCH_FIRST"
        )
        rows.append({
            "case_id": int(case.id),
            "candidate_id": int(candidate.id),
            "title": candidate.title,
            "problem_statement": candidate.problem_statement,
            "actor": candidate.actor,
            "task": candidate.task,
            "object": candidate.object,
            "failure_mode": candidate.failure_mode,
            "consequence": candidate.consequence,
            "buyer_context": candidate.buyer_context,
            "workaround": candidate.workaround,
            "stage": str(candidate.stage or "candidate"),
            "community_evidence_count": int(candidate.community_evidence_count or 0),
            "community_user_count": int(candidate.community_user_count or 0),
            "market_score": float(candidate.market_score or 0),
            "confidence_score": float(candidate.confidence_score or 0),
            "community_problem_score": float(candidate.community_problem_score or 0),
            "corroboration_score": float(candidate.corroboration_score or 0),
            "buyer_demand_score": float(candidate.buyer_demand_score or 0),
            "source_support": dict(candidate.source_support or {}),
            "relation_support": dict(candidate.relation_support or {}),
            "fingerprint": dict(candidate.fingerprint or {}),
            "first_seen_at": candidate.first_seen_at,
            "last_seen_at": candidate.last_seen_at,
            "c02_research_status": str((latest_c02_action.get(int(case.id)).status if latest_c02_action.get(int(case.id)) else "NOT_REGISTERED") or "NOT_REGISTERED").upper(),
            "research_status_by_claim": {
                **dict(research_status_by_case.get(int(case.id), {})),
                "C02": str((latest_c02_action.get(int(case.id)).status if latest_c02_action.get(int(case.id)) else "NOT_REGISTERED") or "NOT_REGISTERED").upper(),
            },
            "claims": claims,
            "attention_score": attention,
            "decision_verdict": verdict,
            "current_gate": gate,
            "next_claim": next_claim,
            "machine_action": FAST_MACHINE_ACTION.get(
                gate, "continue automated evidence research"
            ),
            "founder_action": (
                "RUN_PREPARED_MARKET_VALIDATION"
                if verdict == "VALIDATE"
                else "NONE_MACHINE_RESEARCH_FIRST"
            ),
            "market_validation_boundary": boundary,
            "floor60_reality": {},
            "commercial_reality": {},
            "company_reality": {},
            "prepared_validation_plans": {},
            "prepared_validation_claims": [],
        })

    rows.sort(
        key=lambda row: (
            {"VALIDATE": 0, "INVESTIGATE": 1, "WATCH": 2, "PARK": 3, "IGNORE": 4}.get(
                str(row.get("decision_verdict") or ""), 9
            ),
            -int(row.get("attention_score", 0) or 0),
            int(row.get("case_id", 0) or 0),
        )
    )
    attach_progression_packets(rows)
    return {
        "engine_version": "cycle-state-snapshot-v2-admission-inputs",
        "rows": rows,
        "top": rows[: max(1, int(limit))],
        "verdict_counts": dict(verdict_counts),
        "build_locked": True,
        "reality": {
            "attention": rows,
            "evidence_created": 0,
            "claim_links_created": 0,
            "snapshot_only": True,
        },
        "api_calls": 0,
        "llm_calls": 0,
    }


def _annotate_current_workload(
    current: dict[str, Any],
    *,
    brain_advisory: dict[str, Any] | None,
    corpus_changed: bool = False,
) -> dict[str, Any]:
    rows, summary = annotate_rows(
        list(current.get("rows", []) or []),
        brain_candidate_ids=(brain_advisory or {}).get("candidate_ids") or [],
        corpus_changed=corpus_changed,
    )
    rows, governor = annotate_execution_routes(
        rows,
        brain_advisory=brain_advisory,
        corpus_changed=corpus_changed,
        machine_limit=MAX_ACTIVE_RESEARCH_CASES,
    )
    out = dict(current)
    out["rows"] = rows
    out["top"] = rows[:50]
    out["production_admission"] = summary
    out["execution_governor"] = governor
    out["operating_queue"] = operating_queue(rows, limit=100)
    if isinstance(out.get("reality"), dict):
        out["reality"] = dict(out["reality"])
        out["reality"]["attention"] = rows
    return out


def _merge_workload_admission(
    decision: dict[str, Any],
    annotated_snapshot: dict[str, Any],
) -> dict[str, Any]:
    by_candidate = {
        int(row.get("candidate_id") or 0): {
            "production_admission": row.get("production_admission") or {},
            "execution_route": row.get("execution_route") or {},
            "research_status_by_claim": row.get("research_status_by_claim") or {},
        }
        for row in annotated_snapshot.get("rows", []) or []
        if int(row.get("candidate_id") or 0) > 0
    }
    out = dict(decision)
    rows = []
    for row in decision.get("rows", []) or []:
        copy = dict(row)
        meta = by_candidate.get(int(copy.get("candidate_id") or 0), {})
        copy["production_admission"] = meta.get("production_admission") or {}
        copy["execution_route"] = meta.get("execution_route") or {}
        copy["research_status_by_claim"] = meta.get("research_status_by_claim") or {}
        rows.append(copy)
    out["rows"] = rows
    out["top"] = rows[: len(decision.get("top", []) or []) or 50]
    out["production_admission"] = annotated_snapshot.get("production_admission") or {}
    out["execution_governor"] = annotated_snapshot.get("execution_governor") or {}
    out["operating_queue"] = annotated_snapshot.get("operating_queue") or {}
    return out


def _active_workload_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # R5 canonical machine-execution universe. R2 admission remains visible for
    # regression/audit, but the execution governor removes market-action,
    # Founder-discovery, exhausted-method and parked work before expensive lanes.
    governed = machine_rows(rows, limit=MAX_ACTIVE_RESEARCH_CASES)
    if governed or any("execution_route" in row for row in rows):
        return governed
    # Backward-compatible fallback for snapshots created before R5 annotation.
    active = active_rows(rows)
    active.sort(
        key=lambda row: (
            int(((row.get("production_admission") or {}).get("priority_tier", 9)) or 9),
            {"VALIDATE": 0, "INVESTIGATE": 1, "WATCH": 2, "PARK": 3, "IGNORE": 4}.get(str(row.get("decision_verdict") or "WATCH").upper(), 9),
            -float(row.get("attention_score", 0) or 0),
            int(row.get("case_id", 0) or 0),
        )
    )
    return active[:MAX_ACTIVE_RESEARCH_CASES]


def _recurrence_case_ids(current: dict[str, Any]) -> list[int]:
    return [
        int(row.get("case_id") or 0)
        for row in _active_workload_rows(list(current.get("rows", []) or []))
        if bool(((row.get("production_admission") or {}).get("recurrence_eligible")))
        and int(row.get("case_id") or 0) > 0
    ]


def _materiality_case_ids(current: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for row in _active_workload_rows(list(current.get("rows", []) or [])):
        claims = row.get("claims") or {}
        if str(claims.get("C03", "UNKNOWN")).upper() in {"SUPPORTED", "REFUTED"}:
            continue
        cid = int(row.get("case_id") or 0)
        if cid > 0:
            out.append(cid)
    return out


def _incremental_decision_scope(
    current: dict[str, Any],
    before_snapshot: dict[int, dict[str, Any]],
    *,
    raw_reality_refresh_required: bool,
) -> list[int]:
    """Return the bounded final-decision/materialization scope.

    R5 treated *any* fresh raw source row as a global invalidation and therefore
    rebuilt fuzzy market reality for every historical case. The first R5 live
    cycle proved that this erased most of the bounded-workload performance gain.

    R6 keeps source freshness and truth separate: fresh raw corpus permits the
    bounded active/new cases to rematerialize against the new corpus, while
    untouched cases preserve their durable published state until they are routed
    back into active work. No evidence threshold or claim state is weakened.
    """
    rows = list(current.get("rows", []) or [])
    active = {
        int(row.get("case_id") or 0)
        for row in _active_workload_rows(rows)
        if int(row.get("case_id") or 0) > 0
    }
    current_ids = {
        int(row.get("case_id") or 0)
        for row in rows
        if int(row.get("case_id") or 0) > 0
    }
    new_ids = current_ids - set(before_snapshot)
    return sorted(active | new_ids)


def _parallel_reality_targets(
    current: dict[str, Any],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    # R4 live acceptance found that parallel/prefetch lanes could select from
    # all machine-eligible rows even though C02/C03 used the bounded active
    # set. That violated the intended thesis-controlled execution universe.
    # Every expensive research lane must start from the same bounded set.
    bounded = _active_workload_rows(list(current.get("rows", []) or []))
    rows = [
        row
        for row in bounded
        if row.get("decision_verdict") in {
            "VALIDATE", "INVESTIGATE", "WATCH"
        }
        and int(row.get("attention_score", 0) or 0) >= 45
    ]
    rows.sort(
        key=lambda row: (
            {"VALIDATE": 0, "INVESTIGATE": 1, "WATCH": 2}.get(
                str(row.get("decision_verdict") or ""),
                9,
            ),
            -int(row.get("attention_score", 0) or 0),
            int(row.get("case_id", 0) or 0),
        )
    )
    if not rows:
        rows = [
            row
            for row in bounded
            if row.get("decision_verdict") in {
                "VALIDATE", "INVESTIGATE", "WATCH"
            }
        ][:limit]
    return rows[:limit]


def _parallel_needed_groups(
    rows: list[dict[str, Any]],
) -> list[str]:
    return prioritize_source_groups(rows)


def _normalize_solution_targets(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only legal C06/C07 targets and normalize recheck aliases.

    M15 accidentally returned PAIN/BUYER targets unchanged. Because the
    solution prefetch merge used setdefault(), those earlier-gate rows could
    overwrite the forced CURRENT_SOLUTION prefetch row for the same case.
    The downstream strict solution engine then correctly filtered them out,
    producing solution_allowance>0 but solution_calls=0.
    """
    out = []
    for row in rows:
        copy_row = dict(row)
        gate = str(copy_row.get("current_gate") or "")
        if gate == "CURRENT_SOLUTION_RECHECK":
            copy_row["current_gate"] = "CURRENT_SOLUTION"
        elif gate == "UNRESOLVED_GAP_RECHECK":
            copy_row["current_gate"] = "UNRESOLVED_GAP"
        elif gate not in {"CURRENT_SOLUTION", "UNRESOLVED_GAP"}:
            continue
        out.append(copy_row)
    return out


def _select_focused_targets(
    rows: list[dict[str, Any]],
    *,
    state: dict[str, Any],
    force_refresh: bool,
    groups_attempted_this_cycle: set[str],
    groups_refreshed_this_cycle: set[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Select focused work after source probing.

    Recheck gates are legal only when their source group was freshly probed in
    this cycle (successful or not) or when it remains independently due. This
    prevents stale identical research while still allowing M14's new local
    corpus/cache contracts to be exercised after a due probe.
    """
    out = []
    bounded_rows = _active_workload_rows(rows)
    for row in select_progression_targets(bounded_rows, limit=limit):
        gate = str(row.get("current_gate") or "")
        group = GATE_SOURCE_GROUP.get(gate)
        if gate.endswith("_RECHECK") and group:
            cycle_probe = (
                group in groups_attempted_this_cycle
                or group in groups_refreshed_this_cycle
            )
            if not cycle_probe and not _due(state, group, force_refresh):
                continue
        out.append(row)
    return _ordered_targets(out)


async def run_research_cycle(
    *,
    rounds: int = 2,
    force_refresh: bool = False,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    rounds = max(1, min(int(rounds), 2))
    cycle_started_perf = time.perf_counter()
    phase_seconds: dict[str, float] = defaultdict(float)
    phase_value: dict[str, dict[str, Any]] = {}
    state = _load_state()
    state["cycles"] = int(state.get("cycles", 0)) + 1

    t0 = time.perf_counter()
    runtime_progress.update("integrity_precheck", detail="evidence integrity + persisted claim snapshot")
    integrity_result = await run_evidence_integrity_reconcile()
    ledger_repair = await repair_ledger_state_from_validated_links()
    current = await _load_fast_cycle_state(limit=50)
    brain_advisory = safe_brain_research_advisory(limit=24)
    current = _annotate_current_workload(
        current, brain_advisory=brain_advisory, corpus_changed=False
    )
    runtime_progress.update(
        "integrity_precheck",
        detail="workload admission computed",
        progress={
            "total_cases": len(current.get("rows", []) or []),
            "machine_eligible_total": int((current.get("production_admission") or {}).get("active_machine_research", 0) or 0),
            "bounded_active_cases": len(_active_workload_rows(list(current.get("rows", []) or []))),
            "bounded_active_limit": MAX_ACTIVE_RESEARCH_CASES,
            "admission_states": (current.get("production_admission") or {}).get("states") or {},
        },
        metrics={"production_admission": current.get("production_admission") or {}},
        complete_previous=False,
    )

    quality_before = await audit_quality(decision=current)
    if quality_before.get("status") != "PASS":
        raise RuntimeError(
            "QUALITY_GUARD_PRECHECK_FAILED: "
            + json.dumps(
                quality_before.get("critical", [])[:8],
                ensure_ascii=False,
                default=str,
            )
        )

    rollback_snapshot = await capture_quality_snapshot()
    phase_seconds["integrity_decision_precheck"] += time.perf_counter() - t0
    initial = current
    initial_snapshot = _snapshot(initial)

    cycle_rounds = []
    groups_refreshed_this_cycle = set()
    groups_attempted_this_cycle = set()
    scrapers_refreshed_this_cycle = set()
    cycle_ai_calls = 0
    cycle_ai_tokens = 0
    cycle_ai_cost_twd = 0.0
    cycle_ai_remaining = MAX_RESEARCH_AI_CALLS_PER_CYCLE
    discovery_result: dict[str, Any] | None = None
    materialization_runs: list[dict[str, Any]] = []
    raw_reality_refresh_required = False
    execution_phase_counts: dict[str, int] = {
        "recurrence_selected": 0,
        "materiality_selected": 0,
        "focused_selected_max": 0,
        "buyer_selected_max": 0,
        "solution_selected_max": 0,
        "parallel_selected_max": 0,
    }

    # M15 runs C02 exactly once per real cycle, *after* fresh source collection
    # and stale-aware discovery. M14 rebuilt the same 3k+ document index up to
    # three times per cycle, which dominated wall-clock time without adding
    # truth. Thresholds and adjudication rules are unchanged.
    recurrence_result: dict[str, Any] = {
        "status": "DEFERRED_UNTIL_AFTER_SOURCE_AND_DISCOVERY",
        "llm_calls": 0,
        "llm_tokens": 0,
        "llm_cost_twd": 0.0,
    }
    materiality_result: dict[str, Any] = {
        "status": "NOT_RUN",
        "llm_calls": 0,
    }
    recurrence_has_run = False

    for round_no in range(1, rounds + 1):
        # Snapshot before any round mutation so claim/gate progression caused by
        # source materialization, buyer research, solution research, or the
        # parallel bundle is all visible in diagnostics.
        before_round = _snapshot(current)

        active_cycle_rows = _active_workload_rows(list(current.get("rows", []) or []))
        source_priority_targets = _ordered_targets(
            select_progression_targets(active_cycle_rows, limit=8)
        )
        parallel_targets = _parallel_reality_targets(current, limit=18)

        # Zero active Radar research is a legal state, not a reason to disable
        # discovery. R2 keeps the cheap/stale-aware discovery lane alive even
        # when no existing case deserves expensive research. The cycle may
        # finish after discovery if admission still yields zero active work.

        gates = []
        for row in source_priority_targets:
            gate = str(row.get("current_gate") or "")
            if gate and gate not in gates:
                gates.append(gate)

        gate_groups = []
        for gate in gates:
            group = GATE_SOURCE_GROUP.get(gate)
            if group and group not in gate_groups:
                gate_groups.append(group)

        portfolio = build_research_portfolio(active_cycle_rows)
        source_groups = prioritize_source_groups(
            active_cycle_rows,
            include_groups=gate_groups,
        )
        source_groups = merge_research_source_priority(
            source_groups,
            blocking_gate_groups=gate_groups,
            brain_advisory=brain_advisory,
        )
        # Discovery must remain alive even when zero existing RadarCases deserve
        # expensive research. In that state, probe only the problem-source group
        # when due; do not fan out buyer/market/timing merely to keep the machine
        # busy. This creates a bounded feeder lane into ProblemCandidate formation.
        if not active_cycle_rows and _due(state, "problem", force_refresh):
            if "problem" not in source_groups:
                source_groups.append("problem")

        runtime_progress.update(
            "source_refresh",
            detail=f"round:{round_no}",
            progress={"active_cases": len(active_cycle_rows), "source_groups": source_groups},
        )
        source_t0 = time.perf_counter()
        refresh_results = await _refresh_groups_parallel(
            source_groups=source_groups,
            state=state,
            force_refresh=force_refresh,
            timeout_seconds=timeout_seconds,
            groups_refreshed_this_cycle=groups_refreshed_this_cycle,
            groups_attempted_this_cycle=groups_attempted_this_cycle,
            scrapers_refreshed_this_cycle=scrapers_refreshed_this_cycle,
        )
        phase_seconds["source_refresh"] += time.perf_counter() - source_t0
        brain_research_execution = safe_record_brain_research_execution(
            cycle_key=f"research-cycle:{state.get('cycles', 0)}:round:{round_no}",
            group_results=refresh_results,
            candidate_ids=brain_advisory.get("candidate_ids") or [],
        )

        # If fresh problem-source data landed, immediately re-run the local
        # recurrence verifier without AI. New direct evidence can advance C02
        # and C03 now instead of waiting for tomorrow's cycle.
        problem_refreshed = any(
            item.get("group") == "problem"
            and int(item.get("pass_count", 0) or 0) > 0
            for item in refresh_results
        )
        problem_records_changed = sum(
            int(item.get("records_changed", 0) or 0)
            for item in refresh_results
            if item.get("group") == "problem" and item.get("status") == "ATTEMPTED"
        )
        # M15 deliberately does not rebuild recurrence here. Fresh problem
        # rows and any newly discovered cases are folded into one recurrence
        # pass later in this round.
        recurrence_refresh_result = None

        any_source_refreshed = any(
            int(item.get("pass_count", 0) or 0) > 0
            for item in refresh_results
            if item.get("status") == "ATTEMPTED"
        )
        source_records_changed = sum(
            int(item.get("records_changed", 0) or 0)
            for item in refresh_results
            if item.get("status") == "ATTEMPTED"
        )
        # A successful probe with zero new rows is source-health evidence, not
        # a reason to rebuild Reality. Materialize only when persisted source
        # data actually changed or downstream research writes new truth links.
        any_source_changed = source_records_changed > 0
        if any_source_changed:
            raw_reality_refresh_required = True
        # M15 batches fresh raw sources, discovery, C02 and C03 before one
        # Reality/Decision materialization. M14 repeatedly rebuilt the same
        # full decision surface after each sub-step, which was expensive and
        # did not add truth.
        if any_source_changed:
            materialization_runs.append({
                "round": round_no,
                "phase": "raw_source_materialization",
                "status": "BATCHED_WITH_RECURRENCE_MATERIALITY",
                "evidence_created": 0,
                "claim_links_created": 0,
            })

        runtime_progress.update(
            "problem_discovery",
            detail=f"round:{round_no}",
            progress={
                "source_groups_attempted": len([x for x in refresh_results if x.get("status") == "ATTEMPTED"]),
                "problem_source_refreshed": bool(problem_refreshed),
                "problem_records_changed": int(problem_records_changed),
                "source_records_changed": int(source_records_changed),
            },
        )

        # Problem discovery is a first-class part of the same cycle, but runs at
        # most once. It is stale/corpus-change aware and consumes the same global
        # AI allowance as recurrence/buyer/solution research. Running after the
        # first source probe means newly collected community posts can become
        # ProblemCandidates/RadarCases today instead of waiting for tomorrow.
        if round_no == 1 and discovery_result is None:
            discovery_allowance = min(4, cycle_ai_remaining)
            discovery_result = await run_problem_discovery_refresh(
                ai_call_allowance=discovery_allowance,
                force=False,
            )
            discovery_calls = int(discovery_result.get("llm_calls", 0) or 0)
            cycle_ai_calls += discovery_calls
            cycle_ai_remaining = max(0, cycle_ai_remaining - discovery_calls)
            cycle_ai_tokens += int(discovery_result.get("llm_tokens", 0) or 0)
            cycle_ai_cost_twd += float(discovery_result.get("llm_cost_twd", 0) or 0)

            if int(discovery_result.get("new_cases", 0) or 0) > 0:
                raw_reality_refresh_required = True
                materialization_runs.append({
                    "round": round_no,
                    "phase": "problem_discovery_materialization",
                    "status": "BATCHED_WITH_RECURRENCE_MATERIALITY",
                    "evidence_created": 0,
                    "claim_links_created": 0,
                    "new_cases": int(discovery_result.get("new_cases", 0) or 0),
                })
                discovery_result["recurrence_after_new_cases"] = {
                    "status": "DEFERRED_TO_SINGLE_CYCLE_PASS"
                }

        # Discovery may have admitted new RadarCases. Reload once before C02 so
        # the bounded workload sees them in the same cycle. SEARCH_EXHAUSTED /
        # coverage-gap cases are only reopened when the problem corpus changed.
        problem_corpus_changed = bool(problem_records_changed > 0)
        current = await _load_fast_cycle_state(limit=50)
        current = _annotate_current_workload(
            current,
            brain_advisory=brain_advisory,
            corpus_changed=problem_corpus_changed,
        )

        # One bounded C02 pass per cycle, after source refresh + discovery.
        # Candidate backlog no longer implies recurrence work for every RadarCase.
        if not recurrence_has_run:
            recurrence_ids = _recurrence_case_ids(current)
            materiality_ids = _materiality_case_ids(current)
            execution_phase_counts["recurrence_selected"] = len(recurrence_ids)
            execution_phase_counts["materiality_selected"] = len(materiality_ids)
            runtime_progress.update(
                "c02_recurrence",
                detail="bounded active workload",
                progress={
                    "eligible_cases": len(recurrence_ids),
                    "materiality_cases": len(materiality_ids),
                    "total_cases": len(current.get("rows", []) or []),
                },
            )
            recurrence_t0 = time.perf_counter()
            recurrence_allowance = min(3, cycle_ai_remaining)
            if recurrence_ids:
                recurrence_result = await run_problem_recurrence_multi(
                    ai_call_allowance=recurrence_allowance,
                    case_ids=recurrence_ids,
                )
            else:
                recurrence_result = {
                    "status": "SKIPPED_NO_DECISION_CRITICAL_RECURRENCE_WORK",
                    "cases": 0,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                    "llm_cost_twd": 0.0,
                    "truth_boundary": "ZERO_ACTIVE_RECURRENCE_IS_LEGAL",
                }
            recurrence_calls = int(recurrence_result.get("llm_calls", 0) or 0)
            cycle_ai_calls += recurrence_calls
            cycle_ai_remaining = max(0, cycle_ai_remaining - recurrence_calls)
            cycle_ai_tokens += int(recurrence_result.get("llm_tokens", 0) or 0)
            cycle_ai_cost_twd += float(recurrence_result.get("llm_cost_twd", 0) or 0)
            recurrence_has_run = True
            phase_seconds["c02_recurrence"] += time.perf_counter() - recurrence_t0
            phase_value["c02_recurrence"] = {
                "selected_cases": len(recurrence_ids),
                "llm_calls": recurrence_calls,
                "support_links": int(recurrence_result.get("support_links_created", recurrence_result.get("support_links", 0)) or 0),
                "retrieval_cache": recurrence_result.get("retrieval_cache") or {},
                "truth_boundary": "YIELD_TELEMETRY_ONLY_THRESHOLDS_UNCHANGED",
            }

            runtime_progress.update(
                "c03_materiality",
                detail="bounded active workload",
                progress={"eligible_cases": len(materiality_ids)},
            )
            materiality_t0 = time.perf_counter()
            if materiality_ids:
                materiality_result = await run_materiality_research(
                    limit=min(100, len(materiality_ids)),
                    case_ids=materiality_ids,
                )
            else:
                materiality_result = {
                    "status": "SKIPPED_NO_DECISION_CRITICAL_MATERIALITY_WORK",
                    "cases": 0,
                    "llm_calls": 0,
                }
            phase_seconds["c03_materiality"] += time.perf_counter() - materiality_t0
            phase_value["c03_materiality"] = {
                "selected_cases": len(materiality_ids),
                "support_links": int(materiality_result.get("support_links_created", 0) or 0),
                "material_documents": int(materiality_result.get("material_documents", 0) or 0),
                "truth_boundary": "YIELD_TELEMETRY_ONLY_THRESHOLDS_UNCHANGED",
            }

            current = await _load_fast_cycle_state(limit=50)
            current = _annotate_current_workload(
                current, brain_advisory=brain_advisory, corpus_changed=False
            )
            quality_after_recurrence = await audit_quality(decision=current)
            if quality_after_recurrence.get("status") != "PASS":
                await rollback_quality_snapshot(rollback_snapshot)
                raise RuntimeError(
                    "QUALITY_GUARD_RECURRENCE_MATERIALITY_FAILED: "
                    + json.dumps(
                        quality_after_recurrence.get("critical", [])[:8],
                        ensure_ascii=False,
                        default=str,
                    )
                )

        targets = _select_focused_targets(
            current.get("rows", []),
            state=state,
            force_refresh=force_refresh,
            groups_attempted_this_cycle=groups_attempted_this_cycle,
            groups_refreshed_this_cycle=groups_refreshed_this_cycle,
            limit=8,
        )
        parallel_targets = _parallel_reality_targets(current, limit=18)

        post_discovery_active_rows = _active_workload_rows(list(current.get("rows", []) or []))
        execution_phase_counts["focused_selected_max"] = max(
            execution_phase_counts["focused_selected_max"], len(targets)
        )
        execution_phase_counts["parallel_selected_max"] = max(
            execution_phase_counts["parallel_selected_max"], len(parallel_targets)
        )
        if not post_discovery_active_rows:
            runtime_progress.update(
                "zero_active_projection",
                detail="no expensive research admitted; rebuilding persisted Founder decision projection only",
                progress={
                    "total_cases": len(current.get("rows", []) or []),
                    "active_cases": 0,
                    "new_candidates": int((discovery_result or {}).get("new_candidates", 0) or 0),
                    "new_cases": int((discovery_result or {}).get("new_cases", 0) or 0),
                    "candidates_deferred": int((discovery_result or {}).get("candidates_deferred_before_radar", 0) or 0),
                    "pre_enrichment_deferred": int((discovery_result or {}).get("pre_enrichment_deferred", 0) or 0),
                },
            )
            decision_t0 = time.perf_counter()
            # Explicit [] means zero reducer work, never full-universe work. This
            # keeps the R2 zero-active contract while still using the canonical
            # persisted Founder projection path. None remains the only full scope.
            projected = await run_opportunity_decision(
                limit=50,
                reality_mode="persisted",
                case_ids=[],
            )
            projected["reality_mode"] = "persisted_noop_zero_active"
            projected["decision_scope"] = {
                **(projected.get("decision_scope") or {}),
                "mode": "ZERO_ACTIVE_NOOP",
                "case_ids": [],
                "unscoped_case_mutations": 0,
                "truth_boundary": "NO_EXECUTION_WORK_NO_DECISION_REDUCER_RERUN",
            }
            phase_seconds["zero_active_persisted_projection"] += time.perf_counter() - decision_t0
            phase_value["zero_active_persisted_projection"] = {
                "selected_cases": 0, "truth_changes": 0, "reason": "NO_ACTIVE_EXECUTION_WORK",
                "truth_boundary": "PERFORMANCE_ROUTING_ONLY_NO_EVIDENCE_THRESHOLD_CHANGE",
            }
            projected = _merge_workload_admission(projected, current)
            changes = _changes(before_round, _snapshot(projected))
            cycle_rounds.append({
                "round": round_no,
                "reason": "ZERO_ACTIVE_AFTER_DISCOVERY_LEGAL",
                "source_refresh": refresh_results,
                "problem_discovery": discovery_result if round_no == 1 else None,
                "production_admission": production_admission,
                "research_portfolio": portfolio,
                "brain_research_advisory": brain_advisory,
                "brain_research_execution": brain_research_execution,
                "final_reality_mode": "persisted",
                "changes": changes,
            })
            current = projected
            break

        # Do not wait for every earlier gate before preparing later evidence.
        # Prefetching can create evidence, but Decision still enforces gate
        # order. This prevents the old 55x PAIN_MATERIALITY wall from starving
        # C05/C06 research for entire days.
        buyer_prefetch = _claim_prefetch_rows(
            post_discovery_active_rows,
            claim_code="C05",
            forced_gate="BUYER_REALITY",
            limit=4,
        )
        solution_prefetch = _claim_prefetch_rows(
            sorted(
                post_discovery_active_rows,
                key=lambda row: (
                    0 if str((row.get("claims") or {}).get("C03", "")).upper() == "SUPPORTED" else 1,
                    0 if str((row.get("claims") or {}).get("C05", "")).upper() == "SUPPORTED" else 1,
                    -float(row.get("attention_score", 0) or 0),
                    int(row.get("case_id", 0) or 0),
                ),
            ),
            claim_code="C06",
            forced_gate="CURRENT_SOLUTION",
            limit=5,
        )
        gap_prefetch = [
            {
                **row,
                "current_gate": "UNRESOLVED_GAP",
            }
            for row in post_discovery_active_rows
            if str((row.get("claims") or {}).get("C06", "")).upper() == "SUPPORTED"
            and str((row.get("claims") or {}).get("C07", "UNKNOWN")).upper()
            not in {"SUPPORTED", "REFUTED"}
        ][:3]

        buyer_by_case = {
            int(row.get("case_id") or 0): row
            for row in targets
            if row.get("current_gate") in {"BUYER_REALITY", "BUYER_REALITY_RECHECK"}
        }
        for row in buyer_prefetch:
            buyer_by_case.setdefault(int(row.get("case_id") or 0), row)
        buyer_targets = list(buyer_by_case.values())

        solution_by_case = {
            int(row.get("case_id") or 0): row
            for row in _normalize_solution_targets(targets)
        }
        for row in solution_prefetch:
            solution_by_case.setdefault(int(row.get("case_id") or 0), row)
        for row in gap_prefetch:
            solution_by_case.setdefault(int(row.get("case_id") or 0), row)
        solution_targets = list(solution_by_case.values())

        advanced_count = len(solution_targets)
        buyer_count = len(buyer_targets)
        execution_phase_counts["solution_selected_max"] = max(
            execution_phase_counts["solution_selected_max"], advanced_count
        )
        execution_phase_counts["buyer_selected_max"] = max(
            execution_phase_counts["buyer_selected_max"], buyer_count
        )

        # C06/C07 require two independent SAME_PROBLEM families. M17 spread
        # one call across many targets, which made a fresh two-family closure
        # impossible by construction. Reserve Buyer budget, then give solution
        # research enough depth to close the highest-VOI near-complete case.
        buyer_reserve = min(3, buyer_count, cycle_ai_remaining)
        solution_allowance = min(
            max(0, cycle_ai_remaining - buyer_reserve),
            5 if advanced_count else 0,
        )

        runtime_progress.update(
            "c06_c07_solution_research",
            detail="focused active workload",
            progress={"targets": advanced_count, "ai_allowance": solution_allowance},
        )
        solution_cache_before = retrieval_cache_diagnostics()
        solution_t0 = time.perf_counter()
        solution_result = await run_solution_gap_research(
            solution_targets,
            ai_call_allowance=solution_allowance,
        )
        phase_seconds["c06_c07_solution_research"] += time.perf_counter() - solution_t0
        solution_cache_after = retrieval_cache_diagnostics()
        phase_value["c06_c07_solution_research"] = {
            "selected_cases": len(solution_targets),
            "llm_calls": int(solution_result.get("ai_calls", solution_result.get("llm_calls", 0)) or 0),
            "support_links": int(solution_result.get("support_links", solution_result.get("links_created", 0)) or 0),
            "retrieval_cache_delta": {
                key: int(solution_cache_after.get(key, 0) or 0) - int(solution_cache_before.get(key, 0) or 0)
                for key in ("hits", "misses", "writes", "errors")
            },
            "truth_boundary": "YIELD_TELEMETRY_ONLY_THRESHOLDS_UNCHANGED",
        }
        round_solution_ai_calls = int(
            solution_result.get("ai_calls", 0) or 0
        )
        cycle_ai_calls += round_solution_ai_calls
        cycle_ai_remaining = max(
            0,
            cycle_ai_remaining - round_solution_ai_calls,
        )
        cycle_ai_tokens += int(
            solution_result.get("ai_tokens", 0) or 0
        )
        cycle_ai_cost_twd += float(
            solution_result.get("ai_cost_twd", 0) or 0
        )

        buyer_allowance = min(
            cycle_ai_remaining,
            buyer_count,
            MAX_BUYER_AI_CALLS_PER_ROUND,
        )

        runtime_progress.update(
            "c05_buyer_research",
            detail="focused active workload",
            progress={"targets": buyer_count, "ai_allowance": buyer_allowance},
        )
        buyer_cache_before = retrieval_cache_diagnostics()
        buyer_t0 = time.perf_counter()
        buyer_result = await _focused_buyer_research(
            buyer_targets,
            ai_call_allowance=buyer_allowance,
            force_structured_refresh=any(
                item.get("group") == "buyer"
                and item.get("status") == "ATTEMPTED"
                for item in refresh_results
            ),
        )
        phase_seconds["c05_buyer_research"] += time.perf_counter() - buyer_t0
        buyer_cache_after = retrieval_cache_diagnostics()
        phase_value["c05_buyer_research"] = {
            "selected_cases": len(buyer_targets),
            "llm_calls": int(buyer_result.get("ai_calls", 0) or 0),
            "support_links": int(buyer_result.get("support_links", 0) or 0),
            "retrieval_cache_delta": {
                key: int(buyer_cache_after.get(key, 0) or 0) - int(buyer_cache_before.get(key, 0) or 0)
                for key in ("hits", "misses", "writes", "errors")
            },
            "truth_boundary": "YIELD_TELEMETRY_ONLY_THRESHOLDS_UNCHANGED",
        }
        buyer_diag = buyer_result.get("corpus_diagnostics") or {}
        buyer_source_status = buyer_diag.get("structured_status") or {}
        buyer_structured_fresh_pass = bool(
            buyer_diag.get("structured_forced_refresh")
            and not buyer_diag.get("structured_cache_hit")
            and any(
                str((detail or {}).get("status") or "").upper()
                in {"PASS", "SUCCESS_ZERO"}
                for detail in buyer_source_status.values()
                if isinstance(detail, dict)
            )
        )
        if buyer_structured_fresh_pass:
            # Structured named-buyer sources are first-class buyer evidence. A
            # legacy generic job scraper failure must not make the entire buyer
            # source group stale when Remotive/Arbeitnow/HN refreshed cleanly.
            state.setdefault("last_refresh", {})["buyer"] = (
                datetime.utcnow().isoformat(timespec="seconds")
            )
            groups_refreshed_this_cycle.add("buyer")
            _save_state(state)

        round_buyer_ai_calls = int(
            buyer_result.get("ai_calls", 0) or 0
        )
        cycle_ai_calls += round_buyer_ai_calls
        cycle_ai_remaining = max(
            0,
            cycle_ai_remaining - round_buyer_ai_calls,
        )
        cycle_ai_tokens += int(
            buyer_result.get("ai_tokens", 0) or 0
        )
        cycle_ai_cost_twd += float(
            buyer_result.get("ai_cost_twd", 0) or 0
        )

        # Focused evidence and C08-C14 context are independent writes. Batch
        # both, then rebuild Decision once at the end of the round.
        materialization_runs.append({
            "round": round_no,
            "phase": "focused_research_materialization",
            "status": "BATCHED_WITH_ROUND_FINAL_DECISION",
            "evidence_created": 0,
            "claim_links_created": 0,
        })
        runtime_progress.update(
            "c08_c14_parallel_reality",
            detail="active decision context",
            progress={"targets": len(parallel_targets)},
        )
        parallel_t0 = time.perf_counter()
        parallel_result = await run_parallel_reality_bundle(
            parallel_targets,
            max_cases=16,
        )
        phase_seconds["c08_c14_parallel_reality"] += time.perf_counter() - parallel_t0
        phase_value["c08_c14_parallel_reality"] = {
            "selected_cases": len(parallel_targets),
            "support_links": int(parallel_result.get("links_created", 0) or 0),
            "truth_boundary": "YIELD_TELEMETRY_ONLY_THRESHOLDS_UNCHANGED",
        }

        ai_allocation = {
            "cycle_remaining_before": (
                cycle_ai_remaining
                + round_buyer_ai_calls
                + round_solution_ai_calls
            ),
            "advanced_targets": advanced_count,
            "buyer_targets": buyer_count,
            "solution_allowance": solution_allowance,
            "solution_calls": round_solution_ai_calls,
            "buyer_allowance": buyer_allowance,
            "buyer_calls": round_buyer_ai_calls,
            "cycle_remaining_after": cycle_ai_remaining,
        }

        runtime_progress.update(
            "round_final_decision",
            detail=f"round:{round_no}",
            progress={"active_cases": len(_active_workload_rows(list(current.get("rows", []) or [])))},
        )
        decision_t0 = time.perf_counter()
        final_reality_mode = (
            "materialize" if raw_reality_refresh_required else "persisted"
        )
        decision_scope = _incremental_decision_scope(
            current,
            before_round,
            raw_reality_refresh_required=(final_reality_mode != "persisted"),
        )
        decision_scope_ids = list(decision_scope or [])
        scope_is_explicit = decision_scope is not None
        runtime_progress.update(
            "round_final_decision",
            detail=("scoped raw-reality materialization" if final_reality_mode == "materialize" else "scoped persisted reduction"),
            progress={"current": 0, "total": len(decision_scope_ids), "unit": "cases"},
            complete_previous=False,
        )
        updated = await run_opportunity_decision(
            limit=50,
            reality_mode=final_reality_mode,
            case_ids=decision_scope_ids,
            emit_runtime_progress=True,
        )
        phase_seconds["round_final_decision"] += time.perf_counter() - decision_t0
        phase_value["round_final_decision"] = {
            "selected_cases": len(decision_scope_ids) if scope_is_explicit else len(updated.get("rows", []) or []),
            "scope_mode": ((updated.get("decision_scope") or {}).get("mode") or "FULL"),
            "raw_reality_refresh_required": bool(raw_reality_refresh_required),
            "materialization_scope": ((updated.get("decision_scope") or {}).get("materialization_scope") or {}),
            "subphase_ms": updated.get("phase_ms") or {},
            "truth_boundary": "SCOPING_PRESERVES_UNSCOPED_DURABLE_CASE_DISPOSITION_NO_GATE_WEAKENING",
        }
        fast_after_decision = await _load_fast_cycle_state(limit=50)
        fast_after_decision = _annotate_current_workload(
            fast_after_decision, brain_advisory=brain_advisory, corpus_changed=False
        )
        updated = _merge_workload_admission(updated, fast_after_decision)
        materialization_runs.append({
            "round": round_no,
            "phase": "round_final_decision_materialization",
            "reality_mode": final_reality_mode,
            "evidence_created": int((updated.get("reality") or {}).get("evidence_created", 0) or 0),
            "claim_links_created": int((updated.get("reality") or {}).get("claim_links_created", 0) or 0),
        })
        after_round = _snapshot(updated)
        changes = _changes(before_round, after_round)

        cycle_rounds.append({
            "round": round_no,
            "target_count": len(targets),
            "gates": gates,
            "source_refresh": refresh_results,
            "source_materialized_same_round": bool(any_source_changed),
            "recurrence_refresh": recurrence_refresh_result,
            "problem_discovery": discovery_result if round_no == 1 else None,
            "ai_allocation": ai_allocation,
            "focused_buyer": buyer_result,
            "solution_gap": solution_result,
            "parallel_reality": parallel_result,
            "parallel_target_count": len(parallel_targets),
            "research_portfolio": portfolio,
            "brain_research_advisory": brain_advisory,
            "brain_research_execution": brain_research_execution,
            "final_reality_mode": final_reality_mode,
            "changes": changes,
        })

        current = updated

        # If nothing changed and all planned source work was skipped by
        # cooldown, another identical round has no value.
        attempted_source = any(
            item.get("status") == "ATTEMPTED"
            for item in refresh_results
        )
        parallel_progress = bool(
            int(parallel_result.get("links_created", 0) or 0)
        )
        if not changes and not attempted_source and not parallel_progress:
            break

    _save_state(state)

    quality_after = await audit_quality(decision=current)
    quality_rollback = None

    if quality_after.get("status") != "PASS":
        quality_rollback = await rollback_quality_snapshot(
            rollback_snapshot
        )
        current = await run_opportunity_decision(limit=50)
        quality_restored = await audit_quality(decision=current)
        if quality_restored.get("status") != "PASS":
            raise RuntimeError(
                "QUALITY_GUARD_ROLLBACK_FAILED: "
                + json.dumps(
                    quality_restored.get("critical", [])[:8],
                    ensure_ascii=False,
                    default=str,
                )
            )
        quality_after = {
            **quality_restored,
            "rolled_back_regression": True,
            "original_critical": quality_after.get("critical", []),
        }

    final_snapshot = _snapshot(current)
    total_changes = _changes(initial_snapshot, final_snapshot)

    scraper_statuses: dict[str, int] = defaultdict(int)
    groups_passed = set()
    groups_failed = set()
    for rd in cycle_rounds:
        for refresh in rd.get("source_refresh", []) or []:
            group = str(refresh.get("group") or "")
            if int(refresh.get("pass_count", 0) or 0) > 0:
                groups_passed.add(group)
            elif refresh.get("status") == "ATTEMPTED":
                groups_failed.add(group)
            for item in refresh.get("scrapers", []) or []:
                scraper_statuses[str(item.get("status") or "UNKNOWN").upper()] += 1
    buyer_structured_runs = [
        (rd.get("focused_buyer") or {}).get("corpus_diagnostics") or {}
        for rd in cycle_rounds
        if (rd.get("focused_buyer") or {}).get("corpus_diagnostics")
    ]
    structured_buyer_effective_pass = any(
        row.get("structured_forced_refresh")
        and not row.get("structured_cache_hit")
        and any(
            str((detail or {}).get("status") or "").upper()
            in {"PASS", "SUCCESS_ZERO"}
            for detail in (row.get("structured_status") or {}).values()
            if isinstance(detail, dict)
        )
        for row in buyer_structured_runs
    )
    if structured_buyer_effective_pass:
        groups_passed.add("buyer")
        groups_failed.discard("buyer")

    parallel_context_gaps: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rd in cycle_rounds:
        gap_map = (rd.get("parallel_reality") or {}).get("context_gap_counts") or {}
        for code, counts in gap_map.items():
            if not isinstance(counts, dict):
                continue
            for reason, count in counts.items():
                parallel_context_gaps[str(code)][str(reason)] += int(count or 0)

    source_health = {
        "contract": "scraper_run_db_v1+structured_buyer_v1",
        "groups_attempted": sorted(groups_attempted_this_cycle),
        "groups_refreshed": sorted(groups_refreshed_this_cycle),
        "groups_passed": sorted(groups_passed),
        "groups_failed": sorted(groups_failed - groups_passed),
        "scraper_status_counts": dict(scraper_statuses),
        "legacy_backoff_reprobe_enabled": True,
        "max_groups_per_cycle": MAX_SOURCE_GROUPS_PER_CYCLE,
        "same_round_source_materialization": any(
            bool(rd.get("source_materialized_same_round"))
            for rd in cycle_rounds
        ),
        "parallel_context_gaps": {
            code: dict(counts)
            for code, counts in parallel_context_gaps.items()
        },
        "materialization": {
            "runs": materialization_runs,
            "evidence_created": sum(int(row.get("evidence_created", 0) or 0) for row in materialization_runs),
            "claim_links_created": sum(int(row.get("claim_links_created", 0) or 0) for row in materialization_runs),
        },
        "problem_discovery": {
            "status": (discovery_result or {}).get("status"),
            "reason": (discovery_result or {}).get("reason"),
            "new_candidates": int((discovery_result or {}).get("new_candidates", 0) or 0),
            "new_cases": int((discovery_result or {}).get("new_cases", 0) or 0),
            "pre_enrichment_deferred": int((discovery_result or {}).get("pre_enrichment_deferred", 0) or 0),
            "pre_enrichment_deferred_reasons": (discovery_result or {}).get("pre_enrichment_deferred_reasons") or {},
            "discovery_portfolio": (discovery_result or {}).get("discovery_portfolio") or {},
            "llm_calls": int((discovery_result or {}).get("llm_calls", 0) or 0),
        },
        "structured_buyer": {
            "effective_refresh_passed": structured_buyer_effective_pass,
            "runs": len(buyer_structured_runs),
            "fresh_runs": sum(
                1 for row in buyer_structured_runs
                if row.get("structured_forced_refresh")
                and not row.get("structured_cache_hit")
            ),
            "latest_named": int(
                (buyer_structured_runs[-1] if buyer_structured_runs else {}).get("structured_named", 0) or 0
            ),
            "latest_status": (
                (buyer_structured_runs[-1] if buyer_structured_runs else {}).get("structured_status") or {}
            ),
        },
    }

    phase_seconds["total_cycle"] = time.perf_counter() - cycle_started_perf
    runtime_progress.update(
        "cycle_finalize",
        detail="quality + source + workload diagnostics",
        progress={
            "rounds": len(cycle_rounds),
            "machine_eligible_total": int((current.get("production_admission") or {}).get("active_machine_research", 0) or 0),
            "bounded_active_cases": len(_active_workload_rows(list(current.get("rows", []) or []))),
            "bounded_active_limit": MAX_ACTIVE_RESEARCH_CASES,
        },
        metrics={
            "phase_seconds": {k: round(v, 3) for k, v in phase_seconds.items()},
            "phase_value": phase_value,
            "execution_governor": current.get("execution_governor") or {},
        },
    )

    production_admission = dict(current.get("production_admission") or {})
    bounded_final_rows = _active_workload_rows(list(current.get("rows", []) or []))
    production_admission.update({
        "machine_research_eligible_total": int(production_admission.get("active_machine_research", 0) or 0),
        "active_machine_research_semantics": "ELIGIBLE_TOTAL_NOT_EXECUTION_SET",
        "bounded_active_workload": len(bounded_final_rows),
        "bounded_active_workload_limit": MAX_ACTIVE_RESEARCH_CASES,
        "bounded_active_case_ids": [
            int(row.get("case_id") or 0) for row in bounded_final_rows if int(row.get("case_id") or 0) > 0
        ],
        "execution_truth_boundary": "BOUNDED_WORKLOAD_IS_SCHEDULING_ONLY_NO_MARKET_TRUTH_AUTHORITY",
    })

    return {
        "engine_version": ENGINE_VERSION,

        "integrity": integrity_result,
        "ledger_repair": ledger_repair,
        "recurrence": recurrence_result,
        "materiality": materiality_result,
        "problem_discovery": discovery_result or {},
        "phase_seconds": {k: round(v, 3) for k, v in phase_seconds.items()},
        "final_reality_mode": str((current or {}).get("reality_mode") or ""),
        "materialization_runs": materialization_runs,
        "source_health": source_health,
        "production_admission": production_admission,
        "execution_governor": current.get("execution_governor") or {},
        "operating_queue": current.get("operating_queue") or {},
        "phase_value": {
            key: {**value, "wall_seconds": round(float(phase_seconds.get(key, 0.0)), 3)}
            for key, value in phase_value.items()
        },
        "cycle_profile": {
            "comparison_class": (
                "COLD_CORPUS_OR_DISCOVERY_CHANGE"
                if raw_reality_refresh_required
                else "WARM_PERSISTED_DECISION"
            ),
            "raw_reality_refresh_required": bool(raw_reality_refresh_required),
            "source_groups_attempted": sorted(groups_attempted_this_cycle),
            "source_groups_refreshed": sorted(groups_refreshed_this_cycle),
            "problem_discovery_status": (discovery_result or {}).get("status"),
            "problem_discovery_reason": (discovery_result or {}).get("reason"),
            "decision_scope": (phase_value.get("round_final_decision") or {}).get("materialization_scope") or {},
            "retrieval_cache": retrieval_cache_diagnostics(),
            "truth_boundary": "CYCLE_PROFILE_IS_PERFORMANCE_CONTEXT_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        },
        "discovery_portfolio": (discovery_result or {}).get("discovery_portfolio") or {},
        "execution_workload": {
            "machine_eligible_total": int(production_admission.get("machine_research_eligible_total", 0) or 0),
            "bounded_active_workload": int(production_admission.get("bounded_active_workload", 0) or 0),
            "bounded_active_workload_limit": MAX_ACTIVE_RESEARCH_CASES,
            "recurrence_selected": int(execution_phase_counts.get("recurrence_selected", 0) or 0),
            "materiality_selected": int(execution_phase_counts.get("materiality_selected", 0) or 0),
            "focused_selected_max": int(execution_phase_counts.get("focused_selected_max", 0) or 0),
            "buyer_selected_max": int(execution_phase_counts.get("buyer_selected_max", 0) or 0),
            "solution_selected_max": int(execution_phase_counts.get("solution_selected_max", 0) or 0),
            "parallel_selected_max": int(execution_phase_counts.get("parallel_selected_max", 0) or 0),
            "all_expensive_lanes_bounded": True,
            "truth_boundary": "EXECUTION_COUNTS_ARE_SCHEDULING_TELEMETRY_ONLY_NO_MARKET_TRUTH_AUTHORITY",
        },
        "brain_research_advisory": brain_advisory,
        "quality_before": quality_before,
        "quality_after": quality_after,
        "quality_rollback": quality_rollback,
        "initial": initial,
        "final": current,
        "rounds": cycle_rounds,
        "changes": total_changes,
        "state": state,
        "llm_calls": cycle_ai_calls,
        "llm_tokens": cycle_ai_tokens,
        "llm_cost_twd": round(cycle_ai_cost_twd, 6),
    }


async def print_research_cycle(
    *,
    rounds: int = 2,
    force_refresh: bool = False,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    result = await run_research_cycle(
        rounds=rounds,
        force_refresh=force_refresh,
        timeout_seconds=timeout_seconds,
    )

    before = result["initial"]
    after = result["final"]

    print("\n" + "=" * 118)
    print("RADAR AUTO RESEARCH CYCLE R2 — THESIS-CONTROLLED PRODUCTION WORKLOAD")
    print("=" * 118)
    print("Machine researches blocking gates while preparing precise desk-research and market-test evidence in parallel.")
    integrity = result.get("integrity", {}) or {}
    print(
        "Evidence integrity: "
        f"support_seen={integrity.get('support_rows_seen', 0)} "
        f"affected_claims={integrity.get('affected_claims', 0)} "
        f"quarantined={integrity.get('quarantined', {})} "
        f"preserved={integrity.get('preserved', {})}"
    )
    ledger_repair = result.get("ledger_repair", {}) or {}
    print(
        "Ledger state repair: "
        f"changed={ledger_repair.get('changed_claims', 0)} "
        f"by_code={ledger_repair.get('changed_by_code', {})} "
        "thresholds_weakened=NO"
    )
    q_before = result.get("quality_before", {}) or {}
    q_after = result.get("quality_after", {}) or {}
    print(
        "Quality gate: "
        f"before={q_before.get('status', 'UNKNOWN')} "
        f"critical={q_before.get('critical_count', 0)} | "
        f"after={q_after.get('status', 'UNKNOWN')} "
        f"critical={q_after.get('critical_count', 0)} | "
        f"rollback={'YES' if result.get('quality_rollback') else 'NO'}"
    )
    print(
        "Before lanes: "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(before.get("verdict_counts", {}).items())
        )
    )
    recurrence = result.get("recurrence", {}) or {}
    print(
        "C02 recurrence pass: "
        f"docs={recurrence.get('direct_problem_documents', 0)} "
        f"cases={recurrence.get('cases_evaluated', 0)} "
        f"supported={recurrence.get('c02_supported', 0)} "
        f"coverage_gap={recurrence.get('coverage_gap_actions', 0)} "
        f"new_strict_evidence={recurrence.get('lexical_support_evidence_created', 0)} "
        f"AI_calls={recurrence.get('llm_calls', 0)}"
    )
    materiality = result.get("materiality", {}) or {}
    print(
        "C03 materiality miner: "
        f"material_docs={materiality.get('material_documents', 0)} "
        f"structural_candidates={materiality.get('structural_candidates', 0)} "
        f"new_support_links={materiality.get('support_links_created', 0)} "
        f"supported_after={materiality.get('cases_supported_after', 0)} "
        "thresholds_weakened=NO"
    )
    discovery = result.get("problem_discovery", {}) or {}
    print(
        "Problem discovery: "
        f"status={discovery.get('status', 'NOT_RUN')} "
        f"reason={discovery.get('reason')} "
        f"new_candidates={discovery.get('new_candidates', 0)} "
        f"new_cases={discovery.get('new_cases', 0)} "
        f"AI_calls={discovery.get('llm_calls', 0)}"
    )

    for rd in result["rounds"]:
        print("\n" + "-" * 118)
        print(f"ROUND {rd.get('round')}")
        if rd.get("reason"):
            print("Result:", rd["reason"])
            continue
        print("Blocking-gate targets:", rd.get("target_count", 0))
        print(
            "Parallel reality targets:",
            rd.get("parallel_target_count", 0),
        )
        print("Gates:", ", ".join(rd.get("gates", [])) or "none")

        portfolio = rd.get("research_portfolio", {}) or {}
        ranked_groups = portfolio.get("ranked_groups", []) or []
        if ranked_groups:
            print(
                "Research portfolio: "
                + " | ".join(
                    f"{item.get('group')} voi={item.get('voi')} cases={item.get('case_count')}"
                    for item in ranked_groups[:4]
                )
            )

        for refresh in rd.get("source_refresh", []):
            suffix = ""
            if refresh.get("status") == "ATTEMPTED":
                suffix = (
                    f" pass={refresh.get('pass_count', 0)}/"
                    f"{refresh.get('success_target', 0)}"
                )
            print(
                f"Source group {refresh.get('group')}: "
                f"{refresh.get('status')}{suffix}"
            )
            for scraper in refresh.get("scrapers", []):
                print(
                    "  "
                    + str(scraper.get("name"))
                    + " -> "
                    + str(scraper.get("status"))
                )

        recurrence_refresh = rd.get("recurrence_refresh") or {}
        if recurrence_refresh:
            print(
                "  Fresh-problem recurrence refresh: "
                f"docs={recurrence_refresh.get('direct_problem_documents', 0)} "
                f"supported={recurrence_refresh.get('c02_supported', 0)} "
                f"new_strict_evidence={recurrence_refresh.get('lexical_support_evidence_created', 0)} "
                "AI_calls=0"
            )

        alloc = rd.get("ai_allocation", {}) or {}
        print(
            "AI allocation: "
            f"advanced_targets={alloc.get('advanced_targets', 0)} "
            f"solution_allowance={alloc.get('solution_allowance', 0)} "
            f"solution_calls={alloc.get('solution_calls', 0)} | "
            f"buyer_targets={alloc.get('buyer_targets', 0)} "
            f"buyer_allowance={alloc.get('buyer_allowance', 0)} "
            f"buyer_calls={alloc.get('buyer_calls', 0)} | "
            f"remaining={alloc.get('cycle_remaining_after', 0)}"
        )

        buyer = rd.get("focused_buyer", {})
        if buyer.get("cases", 0):
            print(
                "Focused buyer research: "
                f"cases={buyer.get('cases')} "
                f"jobs={buyer.get('job_corpus_size', 0)} "
                f"matches_reviewed={buyer.get('reviewed_matches', 0)} "
                f"new_support_links={buyer.get('support_links', 0)}"
            )
            diag = buyer.get("corpus_diagnostics", {}) or {}
            if diag:
                print(
                    "  Job corpus truth: "
                    f"db_loaded={diag.get('db_rows_loaded', 0)} "
                    f"recent={diag.get('recent_rows', 0)} "
                    f"with_company={diag.get('with_company', 0)} "
                    f"without_company={diag.get('without_company', 0)} "
                    f"usable={diag.get('usable_docs', 0)}"
                )
                if diag.get("company_sources"):
                    print(
                        "  Legacy company identity sources: "
                        + ", ".join(
                            f"{k}={v}"
                            for k, v in sorted(
                                diag.get("company_sources", {}).items()
                            )
                        )
                    )
                print(
                    "  Structured buyer network: "
                    f"named={diag.get('structured_named', 0)} "
                    f"requests={diag.get('structured_requests', 0)} "
                    f"cache_hit={diag.get('structured_cache_hit', False)}"
                )
                if diag.get("structured_by_source"):
                    print(
                        "  Structured rows: "
                        + ", ".join(
                            f"{k}={v}"
                            for k, v in sorted(
                                diag.get("structured_by_source", {}).items()
                            )
                        )
                    )
                for source, status in sorted(
                    (diag.get("structured_status") or {}).items()
                ):
                    print(
                        f"  Structured source {source}: "
                        f"{status.get('status')} rows={status.get('rows', 0)}"
                    )

            print(
                "  AI candidate stage: "
                f"eligible_cases={buyer.get('ai_candidate_cases', 0)}"
            )
            if buyer.get("ai_prefilter_rejects"):
                print(
                    "  AI prefilter rejects: "
                    + ", ".join(
                        f"{k}={v}"
                        for k, v in sorted(
                            buyer.get(
                                "ai_prefilter_rejects", {}
                            ).items()
                        )
                    )
                )
            for case_id, selected in (
                buyer.get("ai_selected", {}) or {}
            ).items():
                print(
                    f"  AI selected case {case_id}: "
                    f"{selected.get('company')} | "
                    f"{selected.get('title')} | "
                    f"reason={selected.get('reason')} | "
                    f"shortlist={selected.get('shortlist_size', 0)} | "
                    f"sem={float(selected.get('semantic_score', 0) or 0):.3f}"
                )

            print(
                "  Narrow buyer AI: "
                f"calls={buyer.get('ai_calls', 0)} "
                f"cache_hits={buyer.get('ai_cache_hits', 0)} "
                f"SUPPORT={buyer.get('ai_support', 0)} "
                f"INSUFFICIENT={buyer.get('ai_insufficient', 0)} "
                f"gate_denied={buyer.get('ai_gate_denied', 0)} "
                f"deferred={buyer.get('ai_deferred', 0)} "
                f"errors={buyer.get('ai_errors', 0)} "
                f"tokens={buyer.get('ai_tokens', 0)} "
                f"cost=NT${buyer.get('ai_cost_twd', 0):.4f}"
            )
            for case_id, companies in buyer.get("companies", {}).items():
                if companies:
                    print(
                        f"  case {case_id} buyer evidence: "
                        + ", ".join(companies)
                    )

        solution = rd.get("solution_gap", {}) or {}
        if solution.get("cases", 0):
            corpus = solution.get("corpus", {}) or {}
            print(
                "Solution/Gap research: "
                f"cases={solution.get('cases', 0)} "
                f"C06={solution.get('c06_targets', 0)} "
                f"C07={solution.get('c07_targets', 0)} "
                f"docs={corpus.get('docs', 0)} "
                f"support_links={solution.get('support_links', 0)}"
            )
            print(
                "  Same-problem AI: "
                f"calls={solution.get('ai_calls', 0)} "
                f"cache_hits={solution.get('ai_cache_hits', 0)} "
                f"SAME={solution.get('same_problem', 0)} "
                f"DIFFERENT={solution.get('different_problem', 0)} "
                f"INSUFFICIENT={solution.get('same_problem_insufficient', 0)} "
                f"case_SUPPORT={solution.get('ai_support', 0)} "
                f"case_INSUFFICIENT={solution.get('ai_insufficient', 0)} "
                f"errors={solution.get('ai_errors', 0)} "
                f"dimension_rejects={solution.get('dimension_rejects', 0)} "
                f"tokens={solution.get('ai_tokens', 0)} "
                f"cost=NT${float(solution.get('ai_cost_twd', 0) or 0):.4f}"
            )
            if solution.get("ai_validation_failures"):
                print(
                    "  Solution AI validation failures: "
                    + ", ".join(
                        f"{k}={v}"
                        for k, v in sorted(
                            solution.get("ai_validation_failures", {}).items()
                        )
                    )
                )
            if solution.get("ai_exception_types"):
                print(
                    "  Solution AI exceptions: "
                    + ", ".join(
                        f"{k}={v}"
                        for k, v in sorted(
                            solution.get("ai_exception_types", {}).items()
                        )
                    )
                )
            for case_id, detail in (
                solution.get("details", {}) or {}
            ).items():
                print(
                    f"  case {case_id} {detail.get('claim_code')}: "
                    f"state={detail.get('claim_state')} "
                    f"research={detail.get('research_status')} "
                    f"required_dims={detail.get('required_dimensions', [])} "
                    f"ranked={detail.get('ranked_candidates', 0)} "
                    f"checked={detail.get('adjudicated_pairs', 0)} "
                    f"same_families={detail.get('same_problem_families', 0)} "
                    f"dimension_rejects={detail.get('dimension_rejects', 0)}"
                )
                for pair in detail.get("pairs", [])[:4]:
                    print(
                        "    "
                        f"{pair.get('verdict')} | "
                        f"{pair.get('source_type')} | "
                        f"{pair.get('solution') or 'unnamed'} | "
                        f"{str(pair.get('title') or '')[:90]}"
                    )
                for rejected in detail.get(
                    "identity_gate_rejected_examples", []
                )[:3]:
                    print(
                        "    REJECTED | "
                        f"reason={rejected.get('reason')} | "
                        f"{rejected.get('solution') or 'unnamed'} | "
                        f"{str(rejected.get('title') or '')[:85]}"
                    )

        parallel = rd.get("parallel_reality", {}) or {}
        if parallel.get("cases", 0):
            print(
                "Parallel reality bundle: "
                f"cases={parallel.get('cases', 0)} "
                f"claim_contexts={parallel.get('claim_contexts', 0)} "
                f"links_created={parallel.get('links_created', 0)} "
                f"legacy_quarantined={parallel.get('legacy_links_quarantined', 0)} "
                f"needs={','.join(parallel.get('needed_source_groups', []) or []) or 'none'} "
                "LLM=0"
            )
            ready = parallel.get("validation_ready_counts", {}) or {}
            if ready:
                print(
                    "  Prebuilt validation plans: "
                    + " | ".join(
                        f"{k}={v}"
                        for k, v in sorted(ready.items())
                    )
                )
            counts = parallel.get("claim_status_counts", {}) or {}
            if counts:
                compact = []
                for key, value in sorted(counts.items()):
                    compact.append(f"{key}={value}")
                    if len(compact) >= 12:
                        break
                print("  Reality statuses:", " | ".join(compact))

        changes = rd.get("changes", [])
        decision_changes = [
            x for x in changes
            if (
                x.get("before_verdict") != x.get("after_verdict")
                or x.get("before_gate") != x.get("after_gate")
            )
        ]
        claim_only = len(changes) - len(decision_changes)
        print(
            "State changes: "
            f"decision/gate={len(decision_changes)} "
            f"claim_only={claim_only}"
        )
        for change in decision_changes[:10]:
            print(
                f"  case {change['case_id']} "
                f"{change.get('before_verdict')}->{change.get('after_verdict')} "
                f"gate {change.get('before_gate')}->{change.get('after_gate')}"
            )

    print("\n" + "-" * 118)
    print(
        "After lanes:  "
        + " | ".join(
            f"{k}={v}"
            for k, v in sorted(after.get("verdict_counts", {}).items())
        )
    )
    print("Net decision/gate changes:", len(result["changes"]))

    top = after.get("top", [])[:10]
    print("\nCURRENT FOUNDER RADAR")
    for i, row in enumerate(top, 1):
        buyers = list(row.get("buyer_organizations", []) or [])
        print(
            f"  #{i:02d} [{row.get('decision_verdict')}] "
            f"{row.get('title')} | "
            f"gate={row.get('current_gate')} | "
            f"buyers={','.join(buyers) if buyers else 'none'}"
        )

    validation_now = [
        row for row in after.get("rows", [])
        if row.get("market_validation_boundary") == "FOUNDER_ACTION_NOW"
    ]
    validation_prebuilt = [
        row for row in after.get("rows", [])
        if row.get("market_validation_boundary")
        == "PREBUILT_WAITING_FOR_VALIDATE"
    ]
    print(
        "\nVALIDATION BOUNDARY: "
        f"FOUNDER_ACTION_NOW={len(validation_now)} | "
        f"PREBUILT_WAITING={len(validation_prebuilt)} | "
        f"MACHINE_FIRST={max(0, len(after.get('rows', [])) - len(validation_now) - len(validation_prebuilt))}"
    )
    for row in validation_now[:5]:
        print(
            f"  ACTION case {row.get('case_id')}: "
            f"{row.get('title')} | "
            f"plans={','.join(row.get('prepared_validation_claims', []) or []) or 'generic'}"
        )

    timing = result.get("phase_seconds", {}) or {}
    if result.get("final_reality_mode"):
        print(f"FINAL REALITY MODE: {result.get('final_reality_mode')}")
    if timing:
        print("\nPHASE TIMING")
        ordered = sorted(
            ((k, v) for k, v in timing.items() if k != "total_cycle"),
            key=lambda kv: kv[1], reverse=True,
        )
        for name, seconds in ordered:
            print(f"  {name}: {float(seconds):.1f}s")
        print(f"  TOTAL: {float(timing.get('total_cycle', 0)):.1f}s")
    print(f"\nLLM calls: {result.get('llm_calls', 0)}")
    print(f"Tracked AI tokens: {result.get('llm_tokens', 0)}")
    print(
        f"AI cost: NT${float(result.get('llm_cost_twd', 0) or 0):.4f}"
    )
    print("Source monetary cost: NT$0 (public/project-configured collectors)")
    print("BUILD threshold changed: NO")
    print("=" * 118)

    return result


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Radar automated research cycle"
    )
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="ignore source-group cooldown for this run",
    )
    parser.add_argument(
        "--source-timeout",
        type=int,
        default=600,
        help="seconds allowed per scraper",
    )
    args = parser.parse_args()

    await print_research_cycle(
        rounds=args.rounds,
        force_refresh=args.force_refresh,
        timeout_seconds=max(60, min(args.source_timeout, 1800)),
    )


if __name__ == "__main__":
    asyncio.run(_main())
