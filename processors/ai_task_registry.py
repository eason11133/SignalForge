
"""Approved AI tasks for Radar.

AI is not a general research agent here.
Every AI call must be one of these narrow tasks.

This module contains policy only; it does not call an LLM.
"""

from __future__ import annotations

AI_TASKS = {
    "problem_fingerprint_extract": {
        "purpose": "Extract structured problem fields from raw first-hand text.",
        "model_tier": "mini",
        "max_tokens": 900,
        "evidence_bound": True,
        "allowed_when": "raw language cannot be parsed reliably with deterministic extraction",
        "forbidden": [
            "judge market attractiveness",
            "invent missing actor/task/failure/consequence",
            "assign opportunity score",
        ],
        "output_fields": [
            "actor",
            "task",
            "object",
            "failure_mode",
            "consequence",
            "workaround",
            "buyer_context",
            "is_actionable_problem",
        ],
    },
    "same_problem_verify": {
        "purpose": "Judge whether two already-retrieved problem fingerprints describe the same underlying problem.",
        "model_tier": "mini",
        "max_tokens": 500,
        "evidence_bound": True,
        "allowed_when": "deterministic similarity/rules remain ambiguous",
        "forbidden": [
            "use outside knowledge",
            "judge business value",
            "create new evidence",
        ],
        "output_fields": [
            "verdict",
            "matching_dimensions",
            "conflicting_dimensions",
            "evidence_ids",
        ],
        "allowed_verdicts": [
            "SAME_PROBLEM",
            "DIFFERENT_PROBLEM",
            "INSUFFICIENT",
        ],
    },
    "claim_stance_classify": {
        "purpose": "Classify already-retrieved evidence against one atomic claim.",
        "model_tier": "mini",
        "max_tokens": 600,
        "evidence_bound": True,
        "allowed_when": "rules cannot determine SUPPORT/REFUTE/INSUFFICIENT",
        "forbidden": [
            "search the web",
            "add facts not present in supplied evidence",
            "assign system verdict",
        ],
        "output_fields": [
            "stance",
            "evidence_ids",
            "rationale",
        ],
        "allowed_stances": [
            "SUPPORT",
            "REFUTE",
            "INSUFFICIENT",
        ],
    },
    "workaround_extract": {
        "purpose": "Extract explicit user workarounds from supplied text.",
        "model_tier": "mini",
        "max_tokens": 400,
        "evidence_bound": True,
        "allowed_when": "workaround cannot be extracted deterministically",
        "forbidden": [
            "suggest a new workaround",
            "invent missing workaround",
        ],
        "output_fields": [
            "workaround",
            "evidence_ids",
        ],
    },
    "solution_scope_extract": {
        "purpose": "Extract what an existing product/project explicitly solves.",
        "model_tier": "mini",
        "max_tokens": 700,
        "evidence_bound": True,
        "allowed_when": "product documentation is semantically complex",
        "forbidden": [
            "infer unlisted capabilities",
            "declare market gap",
            "score competitor quality",
        ],
        "output_fields": [
            "target_user",
            "solved_job",
            "explicit_capabilities",
            "explicit_limitations",
            "pricing_if_explicit",
            "evidence_ids",
        ],
    },
    "customer_complaint_extract": {
        "purpose": "Extract explicit complaints about an existing solution.",
        "model_tier": "mini",
        "max_tokens": 600,
        "evidence_bound": True,
        "allowed_when": "review/complaint text is semantically ambiguous",
        "forbidden": [
            "infer dissatisfaction not present in text",
            "generalize one complaint to the market",
        ],
        "output_fields": [
            "complaint",
            "affected_job",
            "severity_language",
            "evidence_ids",
        ],
    },
    "query_expansion": {
        "purpose": "Generate source-specific search wording for an already-defined information need.",
        "model_tier": "mini",
        "max_tokens": 400,
        "evidence_bound": False,
        "allowed_when": "free deterministic query templates have insufficient lexical coverage",
        "forbidden": [
            "answer the research question",
            "invent evidence",
            "judge opportunity",
        ],
        "output_fields": [
            "queries",
        ],
    },
    "chinese_quickread": {
        "purpose": "Translate/summarize an already-validated system result for fast founder reading.",
        "model_tier": "mini",
        "max_tokens": 500,
        "evidence_bound": True,
        "allowed_when": "Founder-facing Chinese display is missing",
        "forbidden": [
            "change system verdict",
            "add unsupported rationale",
            "upgrade confidence",
        ],
        "output_fields": [
            "title_zh",
            "summary_zh",
        ],
    },
}


def get_ai_task(name: str) -> dict:
    if name not in AI_TASKS:
        raise KeyError(f"AI task is not approved: {name}")
    return AI_TASKS[name]


def is_ai_task_approved(name: str) -> bool:
    return name in AI_TASKS
