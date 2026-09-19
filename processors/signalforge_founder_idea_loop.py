from __future__ import annotations

import asyncio
import concurrent.futures
import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from processors.signalforge_founder_query_contracts import (
    canonical_source_family,
    compile_source_query,
    semantic_profile,
    source_fit_for_problem_class,
    source_profile_queries,
)
from processors.signalforge_founder_hypothesis_registry import record_founder_hypothesis_probe
from processors.signalforge_source_expansion import run_source_expansion, run_source_expansion_queries
from processors.signalforge_source_registry import observation_families_for_source

ENGINE_VERSION = "signalforge-r8-idea-research-final-v1"
TRUTH_BOUNDARY = (
    "FAST_PROBE_EXTERNAL_RESULTS_ARE_READ_ONLY_UNVALIDATED_SEARCH_TRACES;_"
    "THEY_NEVER_WRITE_C01_C14,_RADAR_CLAIMS,_PUBLISHED_EVIDENCE,_OR_MARKET_TRUTH"
)

DEFAULT_TIMEOUT_SECONDS = 4.0
MAX_RESULTS_PER_SOURCE = 12

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]{1,}|[\u4e00-\u9fff]{2,}")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_MONEY_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:US\$|USD\s*|NT\$|TWD\s*|€|EUR\s*|£|GBP\s*|\$)\s?"
    r"[0-9][0-9,]*(?:\.[0-9]+)?(?:\s*(?:/|per\s+)?(?:user|seat|month|mo|year|yr|delivery|project|hour|hr))?",
    re.IGNORECASE,
)

# Small deterministic bilingual bridge. It is intentionally bounded: no model,
# no translation service, and no pretending an unmapped Chinese phrase was
# understood. The raw Founder wording is always searched too.
_ZH_BRIDGE: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("忘記", "遺忘", "記不住"), ("forget", "memory", "remember", "persistent memory")),
    (("規則", "設定", "指令"), ("rules", "instructions", "settings", "preferences")),
    (("上下文", "脈絡"), ("context", "context window", "conversation context")),
    (("驗收", "交付"), ("acceptance", "delivery", "handoff", "verification")),
    (("完成", "做完", "完成工作", "完成度"), ("completion", "finish", "finished", "done", "task completion")),
    (("確認", "驗證", "核對", "做對", "正確"), ("verification", "verify", "correct", "correctness", "validate")),
    (("使用者", "用戶", "使用的人"), ("user", "users")),
    (("快速", "很快", "效率"), ("quickly", "efficient", "fast")),
    (("困難", "很難", "難以"), ("difficult", "hard", "struggle")),
    (("測試", "品質"), ("testing", "QA", "quality assurance")),
    (("人工", "手動"), ("manual", "manually", "human review")),
    (("代理", "智能體"), ("AI agent", "agentic", "agents")),
    (("程式", "程式碼", "開發"), ("software", "code", "developer", "engineering")),
    (("付費", "訂閱", "價格"), ("paid", "subscription", "pricing", "pay for")),
    (("不準", "錯誤", "失敗", "不可靠"), ("unreliable", "fails", "failure", "incorrect")),
    (("預約", "候補", "空位", "取消", "爽約"), ("appointment", "waitlist", "empty slot", "cancellation", "no show")),
    (("理髮", "髮廊", "美容", "美甲", "按摩"), ("barbershop", "salon", "beauty service", "local service")),
    (("發票", "對帳", "結算"), ("invoice", "reconciliation", "settlement")),
    (("報價", "詢價", "採購"), ("quote", "RFQ", "procurement", "purchasing")),
)

_PAIN_CUES = (
    "problem", "issue", "pain", "frustrat", "annoy", "broken", "fails", "failure",
    "unreliable", "can't", "cannot", "doesn't", "does not", "bug", "forget", "forgot",
    "manual", "manually", "workaround", "missing", "slow", "rework", "redo",
)
_WORKAROUND_CUES = (
    "workaround", "we use", "i use", "instead", "manually", "manual", "script", "custom",
    "hack", "copy paste", "spreadsheet", "checklist", "review by", "fallback",
)
_PAID_CUES = (
    "we pay", "i pay", "pay for", "paid", "paid for", "paying for", "subscription", "pricing",
    "price", "license", "licence", "bought", "purchased", "per month", "monthly", "annual plan",
)
_DISSAT_CUES = (
    "but still", "still have to", "still need", "doesn't", "does not", "can't", "cannot",
    "manual", "manually", "workaround", "switched", "not enough", "fails", "unreliable",
    "missing", "frustrat", "rework", "redo",
)


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _WORD_RE.findall(text or ""):
        low = token.lower()
        if low in seen or len(low) < 2:
            continue
        seen.add(low)
        out.append(token)
    return out


def _cue_present(text: str, cue: str) -> bool:
    """Phrase-aware lexical match. Avoids `custom` matching `customer`, etc."""
    low = (text or "").lower()
    cue_low = cue.lower()
    # A few cues are intentional stems rather than whole words.
    if cue_low in {"frustrat"} or cue_low.endswith("*"):
        stem = cue_low.removesuffix("*")
        return stem in low
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(cue_low) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, low) is not None


def _cue_hits(text: str, cues: Sequence[str]) -> list[str]:
    return [cue for cue in cues if _cue_present(text, cue)]


def _paid_signal_hits(text: str) -> list[str]:
    hits = _cue_hits(text, _PAID_CUES)
    amounts = [m.group(0).strip() for m in _MONEY_AMOUNT_RE.finditer(text or "")]
    if amounts:
        hits.append("currency_amount")
    return list(dict.fromkeys(hits))


def _is_firsthand_trace(trace: Mapping[str, Any]) -> bool:
    text = _clean_text(f"{trace.get('title')} {trace.get('excerpt')}").lower()
    return bool(re.search(r"\b(?:i|i'm|i’ve|i've|my|mine|we|we're|we’ve|we've|our|ours|us)\b", text))


def _looks_like_solution_pitch(trace: Mapping[str, Any]) -> bool:
    """Detect a creator/vendor launch post that should not masquerade as user pain.

    The key distinction is authorship intent, not platform. A Hacker News comment can
    be genuine market conversation, while a ``Show HN`` root post is normally the
    maker presenting a product/project. Keep the rule deliberately narrow.
    """
    title = _clean_text(trace.get("title")).lower()
    source = str(trace.get("source") or "").upper()
    md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
    content_unit = str(trace.get("content_unit") or (md or {}).get("content_unit") or "").upper()
    if source in {"HACKER_NEWS_ALGOLIA", "HACKER_NEWS"} and (
        title.startswith("show hn:") or title.startswith("launch hn:")
    ):
        # Prefer explicit adapter shape, but also repair historical/Algolia rows
        # where a root story was mislabeled COMMENT merely because story_id was
        # present. A true child has a distinct comment/object id or an explicit
        # parent/comment id.
        story_id = str((md or {}).get("story_id") or "")
        object_id = str((md or {}).get("object_id") or "")
        comment_id = str((md or {}).get("comment_id") or "")
        parent_id = str((md or {}).get("parent_id") or "")
        explicit_child = bool(comment_id or parent_id or (story_id and object_id and story_id != object_id))
        if explicit_child:
            return False
        if content_unit in {"POST", "STORY", "TOPIC", "", "COMMENT"}:
            return True
    if content_unit and content_unit not in {"POST", "STORY", "TOPIC"}:
        return False
    return False


def _looks_like_existing_solution(trace: Mapping[str, Any]) -> bool:
    """Identify product/solution pages without requiring a price to be visible.

    Adapter-provided kinds remain the strongest signal. Generic web pages need
    explicit product-page cues so articles that merely mention a tool do not get
    promoted into the similar-products section. Creator launch posts are also
    solutions, but they are classified separately from user conversations.
    """
    if _looks_like_solution_pitch(trace):
        return True
    kind = str(trace.get("kind") or "").upper()
    if kind in {"SOLUTION", "REPOSITORY", "PRODUCT", "TOOL"}:
        return True
    if kind in {"NEWS", "ARTICLE", "JOB", "JOB_POST", "REVIEW", "DISCUSSION", "ISSUE", "COMMENT", "REPLY"}:
        return False

    text = _clean_text(f"{trace.get('title')} {trace.get('excerpt')}").lower()
    signals = trace.get("signals") if isinstance(trace.get("signals"), Mapping) else {}
    if (signals or {}).get("paid") and any(
        _cue_present(text, cue)
        for cue in ("vendor", "tool", "app", "software", "platform", "service", "subscription", "plan")
    ):
        return True

    if kind not in {"WEB_PAGE", "FEED_ITEM", "PAGE", "UNKNOWN", ""}:
        return False
    editorial_cues = ("review of", "best tools", "top tools", "news", "article", "guide", "how to", "comparison of")
    if any(cue in text for cue in editorial_cues):
        return False
    strong_cta = ("free trial", "book a demo", "request a demo", "start free", "get started", "view pricing", "pricing plans")
    product_cues = ("pricing", "features", "integrations", "platform", "software", "app", "solution", "product")
    if any(cue in text for cue in strong_cta):
        return True
    return sum(1 for cue in product_cues if _cue_present(text, cue)) >= 2


def _solution_type(trace: Mapping[str, Any]) -> str | None:
    """Founder-facing solution bucket; avoids presenting every GitHub repo as a product."""
    if not _looks_like_existing_solution(trace):
        return None
    source = str(trace.get("source") or "").upper()
    kind = str(trace.get("kind") or "").upper()
    url = str(trace.get("url") or "").lower()
    if source in {"GITHUB_SEARCH", "GITHUB_REPOSITORIES"} or kind == "REPOSITORY" or "github.com/" in url:
        return "OPEN_SOURCE_OR_REPO"
    if _looks_like_solution_pitch(trace):
        return "PRODUCT_OR_PROJECT_PITCH"
    return "PRODUCT_OR_SERVICE"


def _is_automated_operational_output(trace: Mapping[str, Any]) -> bool:
    """Return True only for explicit bot/agent-authored operational artifacts.

    SignalForge is a market-conversation radar. A coding-agent status comment can
    be inspectable workflow evidence, but it must not be counted as a human
    problem discussion merely because the agent says DONE / verified / shipped.
    The detector is deliberately narrow: explicit bot author metadata or an
    end-of-message generation footer. Human discussion that merely mentions
    generated reports (for example AgentTeams) must remain eligible.
    """
    author = str(trace.get("author") or "").strip().lower()
    if author.endswith("[bot]") or re.fullmatch(r"(?:github-actions|dependabot|renovate)\[bot\]", author):
        return True

    raw = f"{trace.get('excerpt') or ''}".strip()
    if not raw:
        return False
    # Explicit footer/signature shapes only. Do not match ordinary prose such as
    # "a completion report is generated automatically".
    footer_patterns = (
        r"(?:^|\n|---\s*)_?generated by \[?(?:claude code|codex|github actions|automation bot|ai agent)\]?[^\n]*_?\s*$",
        r"(?:^|\n|---\s*)generated by (?:claude code|codex|github actions|automation bot|ai agent)[^\n]*$",
    )
    return any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in footer_patterns)

# Relevance is a search-cleanup gate. Search retrieval and lexical pain cues are not
# enough by themselves; obviously adjacent or mismatched traces should not crowd
# the Founder-facing research brief.
_RELEVANCE_WEAK_TERMS = {
    "tool", "tools", "app", "apps", "software", "platform", "service", "services",
    "issue", "issues", "problem", "problems", "manual", "workflow", "automation",
    "english", "output", "trainer", "tracking", "facebook", "github", "gpt", "gpts",
}

def _distinctive_terms(profile: Mapping[str, Any]) -> set[str]:
    return {
        str(x).lower() for x in (profile.get("terms") or [])
        if str(x).lower() not in _RELEVANCE_WEAK_TERMS and len(str(x)) >= 3
    }

def _specific_problem_terms(profile: Mapping[str, Any]) -> set[str]:
    values = profile.get("specific_problem_terms") or profile.get("terms") or []
    return {
        str(x).lower() for x in values
        if str(x).lower() not in _RELEVANCE_WEAK_TERMS and len(str(x)) >= 3
    }


_GENERALIZED_EXACT_JOB_DIMENSIONS = {
    "MULTI_AGENT_COLLISION", "CODEBASE_UNDERSTANDING_LOSS",
    "LANGUAGE_PRODUCTION_GAP", "VOCABULARY_RETENTION_GAP",
    "REPETITIVE_INQUIRY_TOIL", "LEAD_RESPONSE_LOSS",
    "CLIENT_REPORTING_TOIL", "ECOMMERCE_SUPPORT_TOIL",
    "CONTENT_REPURPOSING_TOIL", "SECURITY_QUESTIONNAIRE_TOIL",
    "INSPECTION_DIAGNOSTICS_JOB", "DOWNTIME_MAINTENANCE_JOB",
    "PROCUREMENT_SOURCING_JOB", "CLAIM_RECOVERY_EVIDENCE_JOB",
    "COST_AUDIT_RECOVERY_JOB", "PROCESS_OPTIMIZATION_JOB",
    "MARKET_PRICE_DISCOVERY_JOB", "RESIDUAL_VALUE_ASSESSMENT_JOB",
}

def classify_trace_relevance(*, hypothesis_text: str, trace: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed relevance gate with workflow/object identity.

    For exact AI-coding-agent hypotheses, problem-dimension overlap is necessary
    but no longer sufficient. The trace must also describe an AI coding/development
    agent acting on software implementation work. Build/CI agents, deployment
    permissions and documentation QA remain inspectable but cannot become exact
    Founder evidence merely because they contain words such as agent/test/review.
    """
    title_text = _clean_text(trace.get("title"))
    trace_text = _clean_text(f"{trace.get('title')} {trace.get('excerpt')}")
    hp = semantic_profile(hypothesis_text)
    tp = semantic_profile(trace_text)
    title_profile = semantic_profile(title_text)

    h_domains, t_domains = set(hp.get("domains") or []), set(tp.get("domains") or [])
    title_domains = set(title_profile.get("domains") or [])
    h_workflows, t_workflows = set(hp.get("workflows") or []), set(tp.get("workflows") or [])
    h_actors, t_actors = set(hp.get("actors") or []), set(tp.get("actors") or [])
    h_problem, t_problem = set(hp.get("problem_dimensions") or []), set(tp.get("problem_dimensions") or [])
    h_agent_roles, t_agent_roles = set(hp.get("agent_roles") or []), set(tp.get("agent_roles") or [])
    h_objects, t_objects = set(hp.get("target_objects") or []), set(tp.get("target_objects") or [])
    h_relationships, t_relationships = set(hp.get("workflow_relationships") or []), set(tp.get("workflow_relationships") or [])
    t_dominant_object = tp.get("dominant_object")
    t_documentation_dominant = bool(tp.get("documentation_dominant"))
    t_explicit_implementation_evidence = bool(tp.get("explicit_implementation_evidence"))
    t_automated_operational_output = _is_automated_operational_output(trace)

    lexical_overlap = sorted(_distinctive_terms(hp) & _distinctive_terms(tp))
    specific_overlap = sorted(_specific_problem_terms(hp) & _specific_problem_terms(tp))
    domain_overlap = sorted(h_domains & t_domains)
    workflow_overlap = sorted(h_workflows & t_workflows)
    actor_overlap = sorted(h_actors & t_actors)
    problem_overlap = sorted(h_problem & t_problem)

    supporting_only = {"HUMAN_REVIEW_BURDEN"}
    target_generalized_jobs = h_problem & _GENERALIZED_EXACT_JOB_DIMENSIONS
    if target_generalized_jobs:
        # Once a hypothesis has an explicit generalized job dimension, old broad
        # dimensions such as scheduling/value cannot substitute for that job.
        # This prevents a clinic appointment or "budget" story from becoming
        # repetitive-inquiry evidence merely because the domain is adjacent.
        core_problem_overlap = sorted(set(problem_overlap) & target_generalized_jobs)
    else:
        core_problem_overlap = sorted(set(problem_overlap) - supporting_only)

    domain_conflict = bool(h_domains and t_domains and not domain_overlap)
    actor_conflict = bool(h_actors and t_actors and not actor_overlap)
    title_domain_conflict = bool(h_domains and title_domains and not (h_domains & title_domains))

    exact_ai_coding_hypothesis = (
        "AI_CODING_AGENT" in h_agent_roles
        and "AI_CODING_IMPLEMENTATION" in h_relationships
    )
    implementation_objects = {"SOFTWARE_IMPLEMENTATION", "CODE_CHANGE", "REFACTOR", "FEATURE", "BUG_FIX"}
    trace_has_ai_coding_workflow = (
        "AI_CODING_AGENT" in t_agent_roles
        and bool(t_objects & implementation_objects)
        and "AI_CODING_IMPLEMENTATION" in t_relationships
    )
    trace_has_foreign_workflow = bool(
        ((t_agent_roles & {"BUILD_AGENT", "CHAT_AGENT"}) and "AI_CODING_AGENT" not in t_agent_roles)
        or ((t_objects & {"BUILD_INFRASTRUCTURE", "DEPLOYMENT_PERMISSION"}) and not (t_objects & implementation_objects))
    )
    documentation_only = bool(
        t_documentation_dominant
        or ("DOCUMENTATION" in t_objects and not (t_objects & implementation_objects))
    )
    workflow_identity_compatible = (
        trace_has_ai_coding_workflow
        and not trace_has_foreign_workflow
        and not documentation_only
        and t_dominant_object != "DOCUMENTATION"
    ) if exact_ai_coding_hypothesis else True

    # R8 System Reset: every non-specialized domain uses the same fail-closed
    # identity contract. If the Founder hypothesis names an actor or workflow,
    # an R0 trace must actually match it; broad domain similarity is not enough.
    generic_actor_identity_compatible = (not h_actors) or bool(actor_overlap)
    generic_workflow_identity_compatible = (not h_workflows) or bool(workflow_overlap)
    generic_identity_compatible = generic_actor_identity_compatible and generic_workflow_identity_compatible

    explicit_context = sum(bool(x) for x in (domain_overlap, workflow_overlap, actor_overlap))
    relevant = False
    gate = "FAIL_CLOSED"

    if t_automated_operational_output and str(trace.get("kind") or "").upper() in {"DISCUSSION", "ISSUE"}:
        gate = "AUTOMATED_OUTPUT_NOT_HUMAN_MARKET_CONVERSATION"
    elif exact_ai_coding_hypothesis and not workflow_identity_compatible:
        if trace_has_foreign_workflow:
            gate = "INCOMPATIBLE_AGENT_WORKFLOW"
        elif documentation_only:
            gate = "DOCUMENTATION_OBJECT_NOT_IMPLEMENTATION"
        else:
            gate = "MISSING_AI_CODING_IMPLEMENTATION_IDENTITY"
    elif h_problem:
        if core_problem_overlap:
            concrete_anchor = bool(specific_overlap or workflow_overlap or actor_overlap or domain_overlap or workflow_identity_compatible)
            if not exact_ai_coding_hypothesis:
                concrete_anchor = concrete_anchor and generic_identity_compatible
            if domain_conflict or actor_conflict or title_domain_conflict:
                relevant = (
                    len(core_problem_overlap) >= 2
                    and len(specific_overlap) >= 2
                    and not actor_conflict
                    and not title_domain_conflict
                    and workflow_identity_compatible
                    and (generic_identity_compatible if not exact_ai_coding_hypothesis else True)
                )
                gate = "PROBLEM_DIMENSION_OVERRIDE_STRICT" if relevant else "CONFLICTING_CONTEXT"
            else:
                relevant = concrete_anchor and workflow_identity_compatible
                gate = "SPECIFIC_PROBLEM_AND_WORKFLOW_IDENTITY" if relevant else "PROBLEM_DIMENSION_WITHOUT_CONCRETE_ANCHOR"
        elif problem_overlap:
            gate = "SUPPORTING_REVIEW_WITHOUT_TARGET_PROBLEM"
        elif workflow_overlap and len(specific_overlap) >= 2:
            gate = "WORKFLOW_ADJACENCY_WITHOUT_TARGET_PROBLEM"
        else:
            gate = "BROAD_DOMAIN_ONLY_OR_WRONG_PROBLEM"
    else:
        if not domain_conflict and not actor_conflict and not title_domain_conflict:
            if explicit_context >= 3:
                relevant = True
                gate = "SEMANTIC_CONTEXT_TRIANGULATION"
            elif explicit_context >= 2 and len(specific_overlap) >= 1:
                relevant = True
                gate = "MULTI_CONTEXT_PLUS_SPECIFIC_ANCHOR"
            elif domain_overlap and len(specific_overlap) >= 2:
                relevant = True
                gate = "DOMAIN_PLUS_SPECIFIC_ANCHORS"
            elif len(specific_overlap) >= 3:
                relevant = True
                gate = "STRONG_SPECIFIC_LEXICAL_MATCH"

    if relevant:
        state = "RELEVANT"
        grade = "R0"
        reason = "The trace matches both the target workflow/object identity and the specific Founder problem/job."
    elif t_automated_operational_output:
        state = "IRRELEVANT"
        grade = "R3"
        reason = "The trace is an explicit bot/agent-generated operational artifact, not a human market conversation or problem report."
    elif trace_has_foreign_workflow or documentation_only:
        state = "IRRELEVANT"
        grade = "R3"
        reason = "The trace is about a different agent/workflow/object, so generic quality words cannot make it exact Founder evidence."
    elif domain_conflict or actor_conflict or title_domain_conflict:
        state = "IRRELEVANT"
        grade = "R3"
        reason = "The trace has a conflicting buyer/problem context and lacks enough specific-problem compatibility to override it."
    else:
        state = "INSUFFICIENT_RELEVANCE"
        # R1/R2 are inspectable context only. They never affect Founder R0
        # counters. This gives the semantic adjudicator a generic candidate band
        # without treating same-domain similarity as evidence.
        if workflow_overlap or (actor_overlap and problem_overlap):
            grade = "R1"
        elif domain_overlap or problem_overlap or len(lexical_overlap) >= 2:
            grade = "R2"
        else:
            grade = "R3"
        reason = "Broad topic/problem-word similarity is insufficient without compatible workflow/object identity."

    roles: list[str] = []
    if relevant:
        kind = str(trace.get("kind") or "").upper()
        signals = trace.get("signals") if isinstance(trace.get("signals"), Mapping) else {}
        if kind in {"DISCUSSION", "ISSUE"}: roles.append("PROBLEM_DISCUSSION")
        if (signals or {}).get("pain") and _is_firsthand_trace(trace): roles.append("FIRSTHAND_PAIN")
        if (signals or {}).get("workaround"): roles.append("WORKAROUND")
        if (signals or {}).get("paid"): roles.append("PAID_SIGNAL")
        if _looks_like_existing_solution(trace): roles.append("EXISTING_SOLUTION")
    return {
        "state": state,
        "grade": grade,
        "countable": relevant,
        "reason": reason,
        "gate": gate,
        "compatibility": {
            "specific_problem_dimensions": problem_overlap,
            "core_problem_dimensions": core_problem_overlap,
            "specific_problem_terms": specific_overlap,
            "actor": actor_overlap,
            "job_workflow": workflow_overlap,
            "context_domain": domain_overlap,
            "title_domains": sorted(title_domains),
            "distinctive_terms": lexical_overlap,
            "target_agent_roles": sorted(h_agent_roles),
            "trace_agent_roles": sorted(t_agent_roles),
            "target_objects": sorted(h_objects),
            "trace_objects": sorted(t_objects),
            "target_workflow_relationships": sorted(h_relationships),
            "trace_workflow_relationships": sorted(t_relationships),
            "trace_dominant_object": t_dominant_object,
            "trace_documentation_dominant": t_documentation_dominant,
            "trace_explicit_implementation_evidence": t_explicit_implementation_evidence,
            "trace_automated_operational_output": t_automated_operational_output,
            "workflow_identity_compatible": workflow_identity_compatible,
            "generic_actor_identity_compatible": generic_actor_identity_compatible,
            "generic_workflow_identity_compatible": generic_workflow_identity_compatible,
            "generic_identity_compatible": generic_identity_compatible,
            "domain_conflict": domain_conflict,
            "title_domain_conflict": title_domain_conflict,
            "actor_conflict": actor_conflict,
        },
        "problem_roles": roles,
        "truth_status": "UNVALIDATED_SEARCH_TRACE",
    }


def _relevance_llm_enabled() -> bool:
    raw = os.getenv("SIGNALFORGE_RELEVANCE_LLM_ENABLED", "false").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _candidate_priority(rel: Mapping[str, Any]) -> tuple[int, int, int]:
    grade = str(rel.get("grade") or "R3")
    comp = rel.get("compatibility") if isinstance(rel.get("compatibility"), Mapping) else {}
    grade_score = {"R0": 4, "R1": 3, "R2": 2, "R3": 0}.get(grade, 0)
    problem_score = len(comp.get("specific_problem_dimensions") or [])
    identity_score = int(bool(comp.get("generic_identity_compatible") or comp.get("workflow_identity_compatible")))
    return grade_score, problem_score, identity_score


_GRADE_RANK = {"R3": 0, "R2": 1, "R1": 2, "R0": 3}
_LLM_RELEVANCE_CANDIDATE_LIMIT = 24
_LLM_PROMOTION_CONFIDENCE_MIN = 0.80
_LLM_DEMOTION_CONFIDENCE_MIN = 0.60


def _confidence01(value: Any) -> float | None:
    try:
        v = float(value)
    except Exception:
        return None
    if v > 1.0 and v <= 100.0:
        v = v / 100.0
    if v < 0.0 or v > 1.0:
        return None
    return v


def _llm_promotion_ceiling(rel: Mapping[str, Any]) -> str:
    """Structural ceiling for the non-authoritative semantic judge.

    The model may refine an ambiguous deterministic result, but it may never
    bypass hard actor/workflow/object conflicts. In particular, same-domain R2
    and random R3 traces cannot become Founder-countable R0 evidence merely
    because an LLM finds them plausible.
    """
    grade = str(rel.get("grade") or "R3")
    comp = rel.get("compatibility") if isinstance(rel.get("compatibility"), Mapping) else {}
    hard_invalid = bool(
        comp.get("trace_automated_operational_output")
        or comp.get("domain_conflict")
        or comp.get("actor_conflict")
        or comp.get("title_domain_conflict")
        or str(rel.get("gate") or "") in {
            "AUTOMATED_OUTPUT_NOT_HUMAN_MARKET_CONVERSATION",
            "INCOMPATIBLE_AGENT_WORKFLOW",
            "DOCUMENTATION_OBJECT_NOT_IMPLEMENTATION",
        }
    )
    if hard_invalid:
        return "R3"
    if grade == "R0":
        return "R0"
    if grade == "R1":
        identity_ok = bool(comp.get("generic_identity_compatible") or comp.get("workflow_identity_compatible"))
        exact_anchor = bool(comp.get("core_problem_dimensions")) or len(comp.get("specific_problem_terms") or []) >= 2
        return "R0" if identity_ok and exact_anchor else "R1"
    if grade == "R2":
        return "R1"
    return "R3"


def _select_llm_candidates(
    hypothesis_text: str,
    traces: Sequence[Mapping[str, Any]],
    limit: int = _LLM_RELEVANCE_CANDIDATE_LIMIT,
) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    ranked: list[tuple[tuple[int, int, int, int], int, dict[str, Any], dict[str, Any]]] = []
    for idx, raw in enumerate(traces):
        trace = dict(raw)
        rel = classify_trace_relevance(hypothesis_text=hypothesis_text, trace=trace)
        if rel.get("gate") == "AUTOMATED_OUTPUT_NOT_HUMAN_MARKET_CONVERSATION":
            continue
        pr = _candidate_priority(rel)
        grade = str(rel.get("grade") or "R3")
        comp = rel.get("compatibility") if isinstance(rel.get("compatibility"), Mapping) else {}
        hard_invalid = (
            bool(comp.get("trace_automated_operational_output"))
            or str(rel.get("gate") or "") in {
                "AUTOMATED_OUTPUT_NOT_HUMAN_MARKET_CONVERSATION",
                "INCOMPATIBLE_AGENT_WORKFLOW",
                "DOCUMENTATION_OBJECT_NOT_IMPLEMENTATION",
            }
        )
        if hard_invalid:
            continue
        # The model is a bounded ambiguity judge, not an unrestricted rescue
        # mechanism. R3 is never sent for promotion; R2 can only become R1.
        if grade == "R3":
            continue
        ranked.append(((pr[0], pr[1], pr[2], len(_clean_text(trace.get("excerpt")))), idx, trace, rel))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [(idx, trace, rel) for _, idx, trace, rel in ranked[:max(1, int(limit))]]


async def adjudicate_fresh_relevance(fresh: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bounded R0/R1/R2/R3 semantic review with structural promotion limits.

    The mini LLM is not an authority layer. Deterministic identity/conflict gates
    remain the ceiling. The model may demote suspicious R0/R1 traces and may
    promote only structurally eligible R1 ambiguity to R0. R2 can become at most
    R1; R3 can never be rescued. This prevents the semantic fallback from undoing
    the exact source/workflow repairs that protect Founder evidence quality.
    """
    out = dict(fresh)
    traces = [dict(x) for x in (fresh.get("traces") or []) if isinstance(x, Mapping)]
    hypothesis_text = _clean_text(fresh.get("relevance_query") or fresh.get("founder_query") or "")
    meta = {
        "enabled": _relevance_llm_enabled(),
        "attempted": False,
        "status": "DETERMINISTIC_ONLY",
        "candidate_limit": _LLM_RELEVANCE_CANDIDATE_LIMIT,
        "candidate_count": 0,
        "judged_count": 0,
        "api_calls": 0,
        "promotion_count": 0,
        "demotion_count": 0,
        "promotion_blocked_count": 0,
        "r0_overflow_quarantined": 0,
        "r0_missing_judgment_quarantined": 0,
        "r0_judge_failure_quarantined": 0,
        "r0_incomplete_review_quarantined": 0,
        "judge_policy": "DETERMINISTIC_HARD_GATES_ARE_CEILING;_WHEN_LLM_REVIEW_IS_ENABLED_EVERY_SELECTED_R0_MUST_RECEIVE_A_VALID_JUDGMENT_OR_FAIL_CLOSED;_R1_MAY_RESCUE_TO_R0_ONLY_WITH_IDENTITY_AND_EXACT_ANCHOR;_R2_MAX_R1;_R3_NEVER_RESCUED",
        "market_truth_writes": 0,
    }
    if not hypothesis_text or not traces or not meta["enabled"]:
        out["traces"] = traces
        return out, meta

    deterministic = [classify_trace_relevance(hypothesis_text=hypothesis_text, trace=t) for t in traces]
    candidates = _select_llm_candidates(hypothesis_text, traces)
    meta["candidate_count"] = len(candidates)
    candidate_indexes = {idx for idx, _, _ in candidates}

    def quarantine_r0(trace_index: int, det: Mapping[str, Any], *, gate: str, reason: str, adjudicator: str) -> None:
        if str(det.get("grade") or "") != "R0":
            return
        quarantined = dict(det)
        quarantined["deterministic_grade"] = "R0"
        quarantined["grade"] = "R1"
        quarantined["state"] = "ADJACENT"
        quarantined["countable"] = False
        quarantined["problem_roles"] = []
        quarantined["gate"] = gate
        quarantined["reason"] = reason
        quarantined["adjudicator"] = adjudicator
        trace2 = dict(traces[trace_index])
        trace2["adjudicated_relevance"] = quarantined
        traces[trace_index] = trace2

    # Precision-first overflow behavior: if the deterministic layer produced more
    # R0 traces than the bounded semantic budget can review, excess R0 traces are
    # quarantined from Founder counters rather than silently passing unreviewed.
    for idx, det in enumerate(deterministic):
        if str(det.get("grade") or "") != "R0" or idx in candidate_indexes:
            continue
        quarantine_r0(
            idx, det,
            gate="R0_OVERFLOW_PENDING_SEMANTIC_REVIEW",
            reason="Deterministic R0 exceeded the bounded semantic review budget and is quarantined from Founder counters until reviewed.",
            adjudicator="BOUNDED_REVIEW_OVERFLOW_GUARD",
        )
        meta["r0_overflow_quarantined"] += 1
        meta["r0_incomplete_review_quarantined"] += 1

    if not candidates:
        out["traces"] = traces
        out["relevance_adjudication"] = meta
        return out, meta

    payload = []
    for local_index, (trace_index, trace, det) in enumerate(candidates):
        payload.append({
            "index": local_index,
            "trace_index": trace_index,
            "source": trace.get("source"),
            "kind": trace.get("kind"),
            "title": _clean_text(trace.get("title"))[:240],
            "excerpt": _clean_text(trace.get("excerpt"))[:900],
            "deterministic_grade": det.get("grade"),
            "promotion_ceiling": _llm_promotion_ceiling(det),
        })

    prompt = {
        "task": "Judge relevance only. Do not judge market size, opportunity, willingness to pay, or business value.",
        "founder_hypothesis": hypothesis_text,
        "labels": {
            "R0": "Same specific problem/job AND compatible actor/workflow/object relationship. Exact core evidence.",
            "R1": "Same workflow or actor but adjacent problem/job. Useful context, not exact evidence.",
            "R2": "Same broad domain/topic only. Not core evidence.",
            "R3": "Different problem/workflow/object, automated artifact, accidental lexical overlap, or irrelevant.",
        },
        "rules": [
            "Prefer R1/R2/R3 when the exact job is not explicit.",
            "A solution description may be R0 only if the product directly exists to solve the same specific job.",
            "Do not infer an actor/workflow from generic words.",
            "Documentation about software is not software implementation.",
            "Build/CI agents are not AI coding agents.",
            "The supplied promotion_ceiling is a hard maximum label; never exceed it.",
            "Return JSON only: {items:[{index,label,confidence,reason}]}.",
        ],
        "traces": payload,
    }

    try:
        from processors.llm_client import call_llm
        meta["attempted"] = True
        response = await call_llm(
            json.dumps(prompt, ensure_ascii=False),
            system_message="You are SignalForge's strict relevance adjudicator. Fail closed. Return JSON only.",
            model="mini",
            temperature=0.0,
            max_tokens=2200,
            parse_json=True,
        )
        meta["api_calls"] = 1
        rows = response.get("items") if isinstance(response, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("relevance adjudicator response missing items list")
        by_local: dict[int, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                key = int(row.get("index"))
            except Exception:
                continue
            if str(row.get("label") or "") in {"R0", "R1", "R2", "R3"}:
                by_local[key] = row

        judged = 0
        for local_index, (trace_index, trace, det) in enumerate(candidates):
            row = by_local.get(local_index)
            if not row:
                if str(det.get("grade") or "") == "R0":
                    quarantine_r0(
                        trace_index, det,
                        gate="R0_MISSING_SEMANTIC_JUDGMENT",
                        reason="Semantic review was enabled but this deterministic R0 did not receive a valid judgment, so it is quarantined from Founder counters.",
                        adjudicator="BOUNDED_REVIEW_COMPLETENESS_GUARD",
                    )
                    meta["r0_missing_judgment_quarantined"] += 1
                    meta["r0_incomplete_review_quarantined"] += 1
                continue
            requested = str(row.get("label"))
            confidence = _confidence01(row.get("confidence"))
            det_grade = str(det.get("grade") or "R3")
            ceiling = _llm_promotion_ceiling(det)
            requested_rank = _GRADE_RANK.get(requested, 0)
            ceiling_rank = _GRADE_RANK.get(ceiling, 0)
            det_rank = _GRADE_RANK.get(det_grade, 0)

            applied = requested
            blocked_reason = None
            if requested_rank > ceiling_rank:
                applied = ceiling
                blocked_reason = "STRUCTURAL_PROMOTION_CEILING"
                meta["promotion_blocked_count"] += 1
            applied_rank = _GRADE_RANK.get(applied, 0)
            if applied_rank > det_rank and (confidence is None or confidence < _LLM_PROMOTION_CONFIDENCE_MIN):
                applied = det_grade
                blocked_reason = "LOW_CONFIDENCE_PROMOTION"
                meta["promotion_blocked_count"] += 1
            elif applied_rank < det_rank and confidence is not None and confidence < _LLM_DEMOTION_CONFIDENCE_MIN:
                # Low-confidence demotion is advisory only; preserve deterministic result.
                applied = det_grade
                blocked_reason = "LOW_CONFIDENCE_DEMOTION_IGNORED"

            final = dict(det)
            final["deterministic_grade"] = det_grade
            final["llm_requested_grade"] = requested
            final["promotion_ceiling"] = ceiling
            final["grade"] = applied
            final["countable"] = applied == "R0"
            final["state"] = "RELEVANT" if applied == "R0" else ("ADJACENT" if applied == "R1" else ("SAME_DOMAIN_ONLY" if applied == "R2" else "IRRELEVANT"))
            final["reason"] = _clean_text(row.get("reason"))[:500] or det.get("reason")
            final["adjudicator"] = "MINI_LLM_RELEVANCE_ONLY_WITH_STRUCTURAL_CEILING"
            final["adjudicator_confidence"] = confidence
            final["promotion_blocked_reason"] = blocked_reason

            if _GRADE_RANK.get(applied, 0) > det_rank:
                meta["promotion_count"] += 1
            elif _GRADE_RANK.get(applied, 0) < det_rank:
                meta["demotion_count"] += 1

            if applied != "R0":
                final["problem_roles"] = []
            elif not final.get("problem_roles"):
                roles: list[str] = []
                kind = str(trace.get("kind") or "").upper()
                signals = trace.get("signals") if isinstance(trace.get("signals"), Mapping) else {}
                if kind in {"DISCUSSION", "ISSUE"}:
                    roles.append("PROBLEM_DISCUSSION")
                if (signals or {}).get("pain") and _is_firsthand_trace(trace):
                    roles.append("FIRSTHAND_PAIN")
                if (signals or {}).get("workaround"):
                    roles.append("WORKAROUND")
                if (signals or {}).get("paid"):
                    roles.append("PAID_SIGNAL")
                if _looks_like_existing_solution(trace):
                    roles.append("EXISTING_SOLUTION")
                final["problem_roles"] = roles
            trace2 = dict(traces[trace_index])
            trace2["adjudicated_relevance"] = final
            traces[trace_index] = trace2
            judged += 1

        meta["judged_count"] = judged
        meta["status"] = "LLM_ADJUDICATED_WITH_STRUCTURAL_CEILING" if judged else "LLM_RESPONSE_NO_VALID_ITEMS"
    except Exception as exc:
        meta["status"] = "LLM_UNAVAILABLE_FAIL_CLOSED"
        meta["error"] = f"{type(exc).__name__}: {exc}"
        for trace_index, _trace, det in candidates:
            if str(det.get("grade") or "") != "R0":
                continue
            existing = traces[trace_index].get("adjudicated_relevance") if isinstance(traces[trace_index], Mapping) else None
            if isinstance(existing, Mapping) and existing.get("countable") is False:
                continue
            quarantine_r0(
                trace_index, det,
                gate="R0_SEMANTIC_JUDGE_FAILED",
                reason="Semantic review was enabled but the judge failed before this deterministic R0 was safely reviewed, so it is quarantined from Founder counters.",
                adjudicator="BOUNDED_REVIEW_FAILURE_GUARD",
            )
            meta["r0_judge_failure_quarantined"] += 1
            meta["r0_incomplete_review_quarantined"] += 1

    out["traces"] = traces
    out["relevance_adjudication"] = meta
    return out, meta



def _bridged_founder_query(raw: str) -> str:
    """Build a compact English-heavy query for mixed Chinese/English Founder ideas.

    Retrieval wants one strong term per concept, not a thesaurus dump. HN in
    particular effectively narrows on every query word, so emitting ``completion
    finish finished done`` can make a good idea impossible to retrieve. The raw
    Founder wording is still searched separately by expansion/web sources.
    """
    text = _clean_text(raw)
    if not text:
        return ""
    low = text.lower()
    concept_terms: list[str] = []
    for zh_terms, en_terms in _ZH_BRIDGE:
        if any(term.lower() in low for term in zh_terms) and en_terms:
            # First term is the canonical retrieval term for this concept.
            concept_terms.append(str(en_terms[0]))
    latin = [x for x in _tokens(text) if re.search(r"[A-Za-z]", x)]
    # Modifiers help prose but often hurt exact source search. Keep them only when
    # they are all we have; otherwise center the object + job.
    weak_concepts = {"user", "users", "quickly", "efficient", "fast", "difficult", "hard", "struggle"}
    strong_concepts = [x for x in concept_terms if x.lower() not in weak_concepts]
    chosen_concepts = strong_concepts or concept_terms
    terms = list(dict.fromkeys([*latin[:6], *chosen_concepts]))
    return " ".join(terms[:10])[:180].strip()


def _bridged_relevance_query(raw: str, retrieval_bridge: str = "") -> str:
    """Preserve the Founder job for relevance without over-constraining search.

    Search engines want short terms; relevance needs the full semantic neighborhood.
    In mixed Chinese/English ideas, phrases such as ``確認做對做完`` imply review,
    requirement adherence and completion even if the compact retrieval bridge only
    says ``completion verification``. Keep these roles separate.
    """
    text = _clean_text(raw)
    low = text.lower()
    terms = list(_tokens(retrieval_bridge or _bridged_founder_query(text)))

    def add(*values: str) -> None:
        lowered = {x.lower() for x in terms}
        for value in values:
            if value.lower() not in lowered:
                terms.append(value)
                lowered.add(value.lower())

    if any(x in low for x in ("確認", "驗證", "核對")):
        add("review", "check")
    if any(x in low for x in ("做對", "正確", "符合需求", "需求")):
        add("requirements", "correctness")
    if any(x in low for x in ("完成", "做完", "完成度")):
        add("completion")
    if any(x in low for x in ("人工", "手動")):
        add("human review", "manual")
    if any(x in low for x in ("測試", "品質")):
        add("testing", "QA")

    return " ".join(terms[:16])[:260].strip()



def _bridge_is_searchable(query: str) -> bool:
    terms = [x.lower() for x in _tokens(query) if re.search(r"[A-Za-z]", x)]
    weak = {"user", "users", "manual", "manually", "quickly", "efficient", "fast", "hard", "difficult", "problem", "issue"}
    strong = [x for x in terms if x not in weak]
    return len(terms) >= 3 and len(strong) >= 2


async def _prepare_query_bridge(raw: str) -> dict[str, Any]:
    """Return bounded English retrieval/relevance semantics for one Founder idea.

    The deterministic bridge remains the zero-cost default.  Pure-Chinese or
    under-specified ideas fall back to one mini-model normalization call so the
    product can generalize beyond a hand-written dictionary.  This call creates no
    market truth; it only rewrites the Founder's own idea into search vocabulary.
    """
    text = _clean_text(raw)
    deterministic = _bridged_founder_query(text)
    deterministic_relevance = _bridged_relevance_query(text, deterministic)
    has_han = bool(_HAN_RE.search(text))
    if not has_han or _bridge_is_searchable(deterministic):
        return {
            "status": "DETERMINISTIC",
            "retrieval_query": deterministic or text,
            "relevance_query": deterministic_relevance or deterministic or text,
            "api_calls": 0,
            "error": None,
        }

    try:
        from processors.llm_client import call_llm

        prompt = (
            "Founder idea:\n" + text + "\n\n"
            "Return JSON with exactly two string fields:\n"
            "retrieval_query: 3-8 concise English search terms preserving the actor, workflow/object, and pain/job. "
            "Do not add business claims or solutions.\n"
            "relevance_query: one concise English sentence describing the same user/workflow/problem, suitable for judging whether a result is closely related. "
            "Preserve the original meaning; do not invent facts.\n"
        )
        row = await call_llm(
            prompt,
            system_message=(
                "You normalize product-research ideas into English search semantics. "
                "Translate only what the user said. Return strict JSON only."
            ),
            model="mini",
            temperature=0.0,
            max_tokens=180,
            parse_json=True,
        )
        if not isinstance(row, Mapping):
            raise ValueError("query bridge LLM did not return a JSON object")
        retrieval = _clean_text(row.get("retrieval_query"))
        relevance = _clean_text(row.get("relevance_query"))
        if not _bridge_is_searchable(retrieval):
            raise ValueError(f"query bridge LLM returned an unusable retrieval query: {retrieval!r}")
        if len(_tokens(relevance)) < 4:
            raise ValueError("query bridge LLM returned an unusable relevance query")
        return {
            "status": "LLM_FALLBACK",
            "retrieval_query": retrieval[:220],
            "relevance_query": relevance[:360],
            "api_calls": 1,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "LIMITED_FALLBACK",
            "retrieval_query": deterministic or text,
            "relevance_query": deterministic_relevance or deterministic or text,
            "api_calls": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }

def expand_founder_query(title: str, description: str = "") -> list[str]:
    raw = _clean_text(f"{title} {description}")
    if not raw:
        return []
    queries: list[str] = [raw]
    low = raw.lower()

    mapped = _bridged_founder_query(raw)
    if mapped and mapped.lower() != raw.lower():
        queries.append(mapped)

    # Source-profile grammar is routing guidance only. It improves the bounded
    # query vocabulary, but never upgrades the returned traces above UNVALIDATED.
    for profile_query in source_profile_queries(raw)[:1]:
        if profile_query and profile_query.lower() not in {q.lower() for q in queries}:
            queries.append(profile_query)

    # A compact lexical form is often better for GitHub / Stack Overflow than a full sentence.
    # Preserve decision-critical counter-search terms even when they appear late
    # in a long Part-3 falsification query.
    tokens = _tokens(raw)
    compact_tokens = tokens[:8]
    lens_terms = (
        "good enough", "already solved", "no budget", "would not pay", "not worth paying",
        "switching cost", "migration", "security", "procurement", "discontinued",
        "no traction", "failed product", "rare problem", "free enough",
    )
    for phrase in lens_terms:
        if phrase in low:
            for token in _tokens(phrase):
                if token.lower() not in {x.lower() for x in compact_tokens}:
                    compact_tokens.append(token)
    compact = " ".join(compact_tokens[:14])
    if compact and compact.lower() not in {q.lower() for q in queries}:
        queries.append(compact)

    # Keep this deliberately small so one Founder click cannot fan out into a crawler job.
    return queries[:3]


class FetchError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: str | None = None, rate_reset: str | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.rate_reset = rate_reset
        self.response_body = response_body


def _request_json(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[dict[str, Any], dict[str, Any]]:
    base_headers = {
        "Accept": "application/json",
        "User-Agent": "SignalForge-Founder-Idea-Loop/1.0",
    }
    if headers:
        base_headers.update(dict(headers))
    req = Request(url, headers=base_headers, method="GET")
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            meta = {
                "status_code": int(getattr(response, "status", 200) or 200),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "rate_remaining": response.headers.get("x-ratelimit-remaining"),
                "rate_reset": response.headers.get("x-ratelimit-reset"),
                "backoff": response.headers.get("backoff"),
            }
            return payload if isinstance(payload, dict) else {"items": payload}, meta
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            body = None
        raise FetchError(
            f"HTTP {exc.code}" + (f": {body}" if body else ""),
            status_code=int(exc.code),
            retry_after=exc.headers.get("retry-after") if exc.headers else None,
            rate_reset=exc.headers.get("x-ratelimit-reset") if exc.headers else None,
            response_body=body,
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc


def _make_trace(*, source: str, kind: str, title: str, excerpt: str = "", url: str | None = None, author: str | None = None, created_at: str | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    text = _clean_text(f"{title} {excerpt}")
    low = text.lower()
    pain = _cue_hits(low, _PAIN_CUES)
    workaround = _cue_hits(low, _WORKAROUND_CUES)
    paid = _paid_signal_hits(low)
    dissatisfied = _cue_hits(low, _DISSAT_CUES)
    md = dict(metadata or {})
    # Native thread / issue identifiers are the only automatic recurrence authority
    # granted by the legacy fast adapters. A URL or similar text alone is not enough.
    native_thread_identity = bool(
        md.get("independence_group_key")
        and any(md.get(k) not in {None, ""} for k in ("story_id", "question_id", "issue_number", "thread_id", "discussion_id"))
    )
    if native_thread_identity and not md.get("recurrence_authority"):
        md["recurrence_authority"] = "SOURCE_NATIVE_THREAD_ID"
    row = {
        "source": source,
        "kind": kind,
        "title": _clean_text(title)[:280],
        "excerpt": _clean_text(excerpt)[:900],
        "url": url,
        "author": author,
        "created_at": created_at,
        "signals": {
            "pain": pain[:6],
            "workaround": workaround[:6],
            "paid": paid[:6],
            "dissatisfaction": dissatisfied[:6],
        },
        "metadata": md,
        "truth_status": "UNVALIDATED_SEARCH_TRACE",
    }
    if md.get("content_unit"):
        row["content_unit"] = str(md.get("content_unit"))
    return row


def _walk_hn_children(
    node: Mapping[str, Any],
    *,
    story_id: str,
    out: list[dict[str, Any]],
    remaining: list[int],
    story_title: str = "",
) -> None:
    """Expand HN replies while preserving the parent topic for relevance.

    Many useful replies are context-dependent (for example, ``same here`` or
    ``we still verify manually``) and do not repeat every keyword from the root
    post. Throwing away the story title made those real human comments look
    unrelated after retrieval.
    """
    if remaining[0] <= 0:
        return
    parent_title = _clean_text(story_title or node.get("title") or "")
    for child in node.get("children") or []:
        if remaining[0] <= 0:
            return
        if not isinstance(child, Mapping):
            continue
        cid = str(child.get("id") or "")
        text = child.get("text") or ""
        if text:
            comment_title = f"Comment on {parent_title}" if parent_title else "Hacker News comment"
            out.append(_make_trace(
                source="HACKER_NEWS_ALGOLIA", kind="DISCUSSION", title=comment_title, excerpt=text,
                url=f"https://news.ycombinator.com/item?id={cid}" if cid else f"https://news.ycombinator.com/item?id={story_id}",
                author=child.get("author"), created_at=child.get("created_at"),
                metadata={
                    "story_id": story_id, "comment_id": cid or None, "parent_id": child.get("parent_id"),
                    "content_unit": "COMMENT", "independence_group_key": f"hn:{story_id}",
                    "parent_story_title": parent_title or None,
                },
            ))
            remaining[0] -= 1
        _walk_hn_children(
            child, story_id=story_id, out=out, remaining=remaining, story_title=parent_title
        )


def _hn_comment_recall_query(query: str) -> str:
    """Build one short HN comment-recall query from the Founder job.

    Algolia requires every query word by default. A precise product query such as
    ``ai coding agents completion verification`` is excellent for repos/pitches but
    too restrictive for human comments, where people usually say ``review``,
    ``check`` or ``requirements`` instead of ``completion verification``. Keep the
    recall query bounded and source-specific rather than broadening relevance rules.
    """
    profile = semantic_profile(query)
    dims = set(profile.get("problem_dimensions") or [])
    roles = set(profile.get("agent_roles") or [])
    domains = set(profile.get("domains") or [])

    identity: list[str] = []
    if "AI_CODING_AGENT" in roles:
        identity = ["ai", "code"]
    elif "SOFTWARE_ENGINEERING" in domains:
        identity = ["software"]
    else:
        identity = [x for x in (profile.get("terms") or []) if x not in {"tool", "product", "workflow"}][:2]

    # Use the language people naturally use in discussions, not ontology labels.
    cue = None
    if dims & {"HUMAN_REVIEW_BURDEN", "COMPLETION_VERIFICATION"}:
        cue = "review"
    elif "REQUIREMENT_ADHERENCE" in dims:
        cue = "requirements"
    elif "TEST_EVIDENCE" in dims:
        cue = "testing"
    elif "TRUSTED_RESULT" in dims:
        cue = "trust"
    elif dims:
        cue = str(next(iter(sorted(dims)))).lower().replace("_", "-")

    parts = [*identity, cue] if cue else identity
    return _clean_text(" ".join(x for x in parts if x))


def _search_hn(query: str) -> dict[str, Any]:
    compiled = compile_source_query(query, "HACKER_NEWS_ALGOLIA")
    final_query = str(compiled.get("final_query") or "")
    if not final_query:
        raise FetchError("HN source query compiled to empty query", status_code=400)
    params = urlencode({"query": final_query, "hitsPerPage": MAX_RESULTS_PER_SOURCE})
    url = f"https://hn.algolia.com/api/v1/search?{params}"
    data, meta = _request_json(url)
    meta["query_contract"] = compiled.get("contract")
    traces: list[dict[str, Any]] = []
    story_ids: list[str] = []
    seen_object_ids: set[str] = set()

    def add_hit(hit: Mapping[str, Any], *, force_comment: bool = False) -> None:
        title = hit.get("title") or hit.get("story_title") or "Hacker News discussion"
        excerpt = hit.get("comment_text") or hit.get("story_text") or ""
        object_id = str(hit.get("objectID") or "")
        story_id = str(hit.get("story_id") or object_id)
        if object_id and object_id in seen_object_ids:
            return
        if object_id:
            seen_object_ids.add(object_id)
        if story_id and story_id not in story_ids:
            story_ids.append(story_id)
        # Algolia can expose ``story_id`` on root story-shaped hits as well as
        # comments. Treat a row as a comment only when it actually has comment
        # text, when its object id differs from the parent story id, or when it
        # came from the explicit ``tags=comment`` recall endpoint.
        has_comment_text = bool(_clean_text(hit.get("comment_text") or ""))
        has_distinct_parent = bool(hit.get("story_id")) and bool(object_id) and str(hit.get("story_id")) != object_id
        is_comment = bool(force_comment or has_comment_text or has_distinct_parent)
        md = {
            "points": hit.get("points"), "num_comments": hit.get("num_comments"), "object_id": object_id,
            "story_id": story_id, "content_unit": "COMMENT" if is_comment else "POST",
            "independence_group_key": f"hn:{story_id}" if story_id else None,
        }
        if is_comment:
            md["comment_id"] = object_id or None
            md["parent_story_title"] = _clean_text(hit.get("story_title") or hit.get("title") or "") or None
        traces.append(_make_trace(
            source="HACKER_NEWS_ALGOLIA", kind="DISCUSSION", title=title, excerpt=excerpt,
            url=f"https://news.ycombinator.com/item?id={object_id or story_id}" if (object_id or story_id) else None,
            author=hit.get("author"), created_at=hit.get("created_at"), metadata=md,
        ))

    for hit in list(data.get("hits") or [])[:MAX_RESULTS_PER_SOURCE]:
        if isinstance(hit, Mapping):
            add_hit(hit)

    # Human comments use looser vocabulary than product pages/repositories. Search
    # the HN comment index once with a short source-specific recall query. This
    # increases recall without weakening the downstream thesis relevance gate.
    recall_query = _hn_comment_recall_query(query)
    if recall_query and recall_query.lower() != final_query.lower():
        recall_params = urlencode({"query": recall_query, "tags": "comment", "hitsPerPage": MAX_RESULTS_PER_SOURCE})
        recall_url = f"https://hn.algolia.com/api/v1/search?{recall_params}"
        try:
            recall_data, recall_meta = _request_json(recall_url)
            recall_hits = [x for x in (recall_data.get("hits") or []) if isinstance(x, Mapping)][:MAX_RESULTS_PER_SOURCE]
            for hit in recall_hits:
                add_hit(hit, force_comment=True)
            meta["comment_recall"] = {
                "status": "SUCCESS", "query": recall_query, "hit_count": len(recall_hits), **recall_meta,
            }
        except Exception as exc:
            # The primary HN query may still be useful; expose this as partial depth
            # metadata instead of erasing already-retrieved evidence.
            meta["comment_recall"] = {
                "status": "PARTIAL", "query": recall_query, "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        meta["comment_recall"] = {"status": "SKIPPED", "query": recall_query, "reason": "SAME_AS_PRIMARY_QUERY"}

    depth_meta: list[dict[str, Any]] = []
    # Expand only a few matched story roots. A depth failure is fail-visible metadata,
    # not a failure of the already-successful search transport.
    hn_remaining = [24]
    for story_id in story_ids[:4]:
        if hn_remaining[0] <= 0:
            break
        try:
            item, imeta = _request_json(f"https://hn.algolia.com/api/v1/items/{story_id}")
            depth_meta.append({"story_id": story_id, "status": "SUCCESS", **imeta})
            before = len(traces)
            _walk_hn_children(
                item, story_id=story_id, out=traces, remaining=hn_remaining,
                story_title=_clean_text(item.get("title") or ""),
            )
            # Direct comment-search hits and depth expansion can overlap. Keep one
            # card per HN object id so ranking is not inflated by the same comment.
            if len(traces) > before:
                deduped: list[dict[str, Any]] = []
                seen_urls: set[str] = set()
                for row in traces:
                    row_url = str(row.get("url") or "")
                    if row_url and row_url in seen_urls:
                        continue
                    if row_url:
                        seen_urls.add(row_url)
                    deduped.append(row)
                traces[:] = deduped
        except Exception as exc:
            depth_meta.append({"story_id": story_id, "status": "PARTIAL", "error": f"{type(exc).__name__}: {exc}"})
    meta["depth"] = depth_meta
    return {"source": "HACKER_NEWS_ALGOLIA", "status": "SUCCESS", "query": query, "final_search_query_used": final_query, "query_contract": compiled, "count": len(traces), "traces": traces, "transport": meta}

def _stack_created_at(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat() if value else None
    except Exception:
        return None


def _search_stackoverflow(query: str) -> dict[str, Any]:
    compiled = compile_source_query(query, "STACK_OVERFLOW_API")
    final_query = str(compiled.get("final_query") or "")
    if not final_query:
        raise FetchError("Stack Overflow source query compiled to empty query", status_code=400)
    params = urlencode({"site": "stackoverflow", "q": final_query, "pagesize": MAX_RESULTS_PER_SOURCE, "sort": "relevance", "order": "desc"})
    url = f"https://api.stackexchange.com/2.3/search/advanced?{params}"
    data, meta = _request_json(url)
    traces: list[dict[str, Any]] = []
    qids: list[str] = []
    for item in list(data.get("items") or [])[:MAX_RESULTS_PER_SOURCE]:
        qid = str(item.get("question_id") or "")
        if qid:
            qids.append(qid)
        traces.append(_make_trace(
            source="STACK_OVERFLOW_API", kind="DISCUSSION", title=item.get("title") or "Stack Overflow question",
            excerpt=item.get("body") or " ".join(str(x) for x in (item.get("tags") or [])), url=item.get("link"),
            author=((item.get("owner") or {}).get("display_name") if isinstance(item.get("owner"), Mapping) else None),
            created_at=_stack_created_at(item.get("creation_date")),
            metadata={"question_id": qid or None, "score": item.get("score"), "answer_count": item.get("answer_count"), "is_answered": item.get("is_answered"), "content_unit": "QUESTION", "independence_group_key": f"stackoverflow:{qid}" if qid else None},
        ))
    depth_meta: list[dict[str, Any]] = []
    answer_ids: list[str] = []
    answer_to_qid: dict[str, str] = {}
    if qids:
        ids = ";".join(qids[:12])
        # Answers
        try:
            aparams = urlencode({"site": "stackoverflow", "pagesize": 60, "sort": "votes", "order": "desc", "filter": "withbody"})
            adata, ameta = _request_json(f"https://api.stackexchange.com/2.3/questions/{ids}/answers?{aparams}")
            depth_meta.append({"endpoint": "answers", "status": "SUCCESS", **ameta})
            for ans in list(adata.get("items") or [])[:60]:
                if not isinstance(ans, Mapping):
                    continue
                aid = str(ans.get("answer_id") or "")
                qid = str(ans.get("question_id") or "")
                if aid:
                    answer_ids.append(aid)
                    if qid:
                        answer_to_qid[aid] = qid
                traces.append(_make_trace(
                    source="STACK_OVERFLOW_API", kind="DISCUSSION", title="Stack Overflow answer", excerpt=ans.get("body") or "",
                    url=f"https://stackoverflow.com/a/{aid}" if aid else None,
                    author=((ans.get("owner") or {}).get("display_name") if isinstance(ans.get("owner"), Mapping) else None), created_at=_stack_created_at(ans.get("creation_date")),
                    metadata={"question_id": qid or None, "answer_id": aid or None, "score": ans.get("score"), "is_accepted": ans.get("is_accepted"), "content_unit": "ANSWER", "independence_group_key": f"stackoverflow:{qid}" if qid else None},
                ))
        except Exception as exc:
            depth_meta.append({"endpoint": "answers", "status": "PARTIAL", "error": f"{type(exc).__name__}: {exc}"})
        # Question comments
        try:
            cparams = urlencode({"site": "stackoverflow", "pagesize": 100, "sort": "votes", "order": "desc", "filter": "withbody"})
            cdata, cmeta = _request_json(f"https://api.stackexchange.com/2.3/questions/{ids}/comments?{cparams}")
            depth_meta.append({"endpoint": "question_comments", "status": "SUCCESS", **cmeta})
            for com in list(cdata.get("items") or [])[:100]:
                if not isinstance(com, Mapping):
                    continue
                pid = str(com.get("post_id") or "")
                traces.append(_make_trace(
                    source="STACK_OVERFLOW_API", kind="DISCUSSION", title="Stack Overflow comment", excerpt=com.get("body") or "",
                    url=f"https://stackoverflow.com/questions/{pid}#comment-{com.get('comment_id')}_{pid}" if pid else None,
                    author=((com.get("owner") or {}).get("display_name") if isinstance(com.get("owner"), Mapping) else None), created_at=_stack_created_at(com.get("creation_date")),
                    metadata={"question_id": pid or None, "comment_id": com.get("comment_id"), "score": com.get("score"), "content_unit": "COMMENT", "independence_group_key": f"stackoverflow:{pid}" if pid else None},
                ))
        except Exception as exc:
            depth_meta.append({"endpoint": "question_comments", "status": "PARTIAL", "error": f"{type(exc).__name__}: {exc}"})
        # Answer comments
        if answer_ids:
            aids = ";".join(answer_ids[:60])
            try:
                cparams = urlencode({"site": "stackoverflow", "pagesize": 100, "sort": "votes", "order": "desc", "filter": "withbody"})
                cdata, cmeta = _request_json(f"https://api.stackexchange.com/2.3/answers/{aids}/comments?{cparams}")
                depth_meta.append({"endpoint": "answer_comments", "status": "SUCCESS", **cmeta})
                for com in list(cdata.get("items") or [])[:100]:
                    if not isinstance(com, Mapping):
                        continue
                    aid = str(com.get("post_id") or "")
                    qid = answer_to_qid.get(aid, "")
                    traces.append(_make_trace(
                        source="STACK_OVERFLOW_API", kind="DISCUSSION", title="Stack Overflow answer comment", excerpt=com.get("body") or "",
                        url=f"https://stackoverflow.com/a/{aid}" if aid else None,
                        author=((com.get("owner") or {}).get("display_name") if isinstance(com.get("owner"), Mapping) else None), created_at=_stack_created_at(com.get("creation_date")),
                        metadata={"question_id": qid or None, "answer_id": aid or None, "comment_id": com.get("comment_id"), "score": com.get("score"), "content_unit": "COMMENT", "independence_group_key": f"stackoverflow:{qid}" if qid else (f"stackoverflow-answer:{aid}" if aid else None)},
                    ))
            except Exception as exc:
                depth_meta.append({"endpoint": "answer_comments", "status": "PARTIAL", "error": f"{type(exc).__name__}: {exc}"})
    meta["quota_remaining"] = data.get("quota_remaining")
    meta["backoff"] = data.get("backoff") or meta.get("backoff")
    meta["query_contract"] = compiled.get("contract")
    meta["depth"] = depth_meta
    return {"source": "STACK_OVERFLOW_API", "status": "SUCCESS", "query": query, "final_search_query_used": final_query, "query_contract": compiled, "count": len(traces), "traces": traces, "transport": meta}

def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _search_github_issues(query: str) -> dict[str, Any]:
    compiled = compile_source_query(query, "GITHUB_ISSUES")
    final_query = str(compiled.get("final_query") or "")
    if not final_query:
        raise FetchError("GitHub issue query compiled to empty query", status_code=422)
    q = f"{final_query} is:issue"
    params = urlencode({"q": q, "sort": "comments", "order": "desc", "per_page": MAX_RESULTS_PER_SOURCE})
    url = f"https://api.github.com/search/issues?{params}"
    data, meta = _request_json(url, headers=_github_headers())
    meta["query_contract"] = compiled.get("contract")
    traces: list[dict[str, Any]] = []
    depth_meta: list[dict[str, Any]] = []
    comment_budget = 48
    for item in list(data.get("items") or [])[:MAX_RESULTS_PER_SOURCE]:
        repo_api = str(item.get("repository_url") or "")
        number = item.get("number")
        repo_path = repo_api.split("/repos/", 1)[1] if "/repos/" in repo_api else ""
        group = f"github-issue:{repo_path.lower()}:{number}" if repo_path and number else None
        traces.append(_make_trace(
            source="GITHUB_SEARCH", kind="ISSUE", title=item.get("title") or "GitHub issue", excerpt=item.get("body") or "",
            url=item.get("html_url"), author=((item.get("user") or {}).get("login") if isinstance(item.get("user"), Mapping) else None),
            created_at=item.get("created_at"), metadata={"comments": item.get("comments"), "state": item.get("state"), "repository_url": repo_api, "issue_number": number, "content_unit": "ISSUE", "independence_group_key": group},
        ))
        if repo_path and number and int(item.get("comments") or 0) > 0 and comment_budget > 0:
            cparams = urlencode({"per_page": min(30, comment_budget), "sort": "created", "direction": "asc"})
            curl = f"https://api.github.com/repos/{repo_path}/issues/{number}/comments?{cparams}"
            try:
                cdata, cmeta = _request_json(curl, headers=_github_headers())
                depth_meta.append({"repository": repo_path, "issue_number": number, "status": "SUCCESS", **cmeta})
                for comment in list(cdata.get("items") or [])[:comment_budget]:
                    if not isinstance(comment, Mapping):
                        continue
                    # _request_json normalizes top-level arrays to {items:[...]}; real GitHub endpoint is an array.
                    traces.append(_make_trace(
                        source="GITHUB_SEARCH", kind="DISCUSSION", title=f"Comment on {item.get('title') or 'GitHub issue'}", excerpt=comment.get("body") or "",
                        url=comment.get("html_url") or item.get("html_url"), author=((comment.get("user") or {}).get("login") if isinstance(comment.get("user"), Mapping) else None),
                        created_at=comment.get("created_at"), metadata={"repository": repo_path, "issue_number": number, "comment_id": comment.get("id"), "author_association": comment.get("author_association"), "content_unit": "ISSUE_COMMENT", "independence_group_key": group},
                    ))
                    comment_budget -= 1
                    if comment_budget <= 0:
                        break
            except Exception as exc:
                depth_meta.append({"repository": repo_path, "issue_number": number, "status": "PARTIAL", "error": f"{type(exc).__name__}: {exc}"})
    meta["depth"] = depth_meta
    return {"source": "GITHUB_ISSUES", "status": "SUCCESS", "query": query, "final_search_query_used": final_query, "query_contract": compiled, "count": len(traces), "traces": traces, "transport": meta}

def _search_github_repositories(query: str) -> dict[str, Any]:
    compiled = compile_source_query(query, "GITHUB_REPOSITORIES")
    final_query = str(compiled.get("final_query") or "")
    if not final_query:
        raise FetchError("GitHub repository query compiled to empty query", status_code=422)
    params = urlencode({"q": final_query, "sort": "stars", "order": "desc", "per_page": 8})
    url = f"https://api.github.com/search/repositories?{params}"
    data, meta = _request_json(url, headers=_github_headers())
    meta["query_contract"] = compiled.get("contract")
    traces: list[dict[str, Any]] = []
    for item in list(data.get("items") or [])[:8]:
        traces.append(_make_trace(
            source="GITHUB_SEARCH", kind="SOLUTION", title=item.get("full_name") or item.get("name") or "GitHub repository",
            excerpt=item.get("description") or "", url=item.get("html_url"),
            author=((item.get("owner") or {}).get("login") if isinstance(item.get("owner"), Mapping) else None), created_at=item.get("created_at"),
            metadata={"stars": item.get("stargazers_count"), "forks": item.get("forks_count"), "language": item.get("language"), "license": (item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), Mapping) else None},
        ))
    return {"source": "GITHUB_REPOSITORIES", "status": "SUCCESS", "query": query, "final_search_query_used": final_query, "query_contract": compiled, "count": len(traces), "traces": traces, "transport": meta}


def _enrich_expansion_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an adapter trace through the same lexical signal extraction as legacy fast sources."""
    metadata = dict(trace.get("metadata") or {}) if isinstance(trace.get("metadata"), Mapping) else {}
    if trace.get("content_unit"):
        metadata["content_unit"] = trace.get("content_unit")
    if trace.get("source_family"):
        metadata["source_family"] = trace.get("source_family")
    made = _make_trace(
        source=str(trace.get("source") or "EXPANSION_SOURCE"),
        kind=str(trace.get("kind") or "DISCUSSION"),
        title=str(trace.get("title") or "Source result"),
        excerpt=str(trace.get("excerpt") or ""),
        url=trace.get("url"),
        author=trace.get("author"),
        created_at=trace.get("created_at"),
        metadata=metadata,
    )
    made["content_unit"] = str(trace.get("content_unit") or trace.get("kind") or "UNKNOWN")
    made["source_family"] = str(trace.get("source_family") or canonical_source_family(str(trace.get("source") or "")))
    obs = list(trace.get("observation_source_families") or metadata.get("observation_source_families") or observation_families_for_source(str(trace.get("source") or "")))
    made["observation_source_families"] = list(dict.fromkeys(str(x).upper() for x in obs if str(x).strip()))
    return made


def merge_expansion_into_fresh(base: Mapping[str, Any], expansion: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    base_sources = [dict(x) for x in (base.get("sources") or []) if isinstance(x, Mapping)]
    expansion_sources: list[dict[str, Any]] = []
    for row in expansion.get("sources") or []:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        source_id = str(item.get("source") or "")
        item["source_family"] = str(item.get("source_family") or canonical_source_family(source_id))
        item["observation_source_families"] = list(dict.fromkeys(
            str(x).upper() for x in (item.get("observation_source_families") or observation_families_for_source(source_id)) if str(x).strip()
        ))
        enriched = [_enrich_expansion_trace(x) for x in (item.get("traces") or []) if isinstance(x, Mapping)]
        item["traces"] = enriched
        item["count"] = len(enriched)
        expansion_sources.append(item)

    combined_sources = [*base_sources, *expansion_sources]
    traces: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in combined_sources:
        source_id = str(source.get("source") or "")
        for trace in source.get("traces") or []:
            if not isinstance(trace, Mapping):
                continue
            t = dict(trace)
            if "source_family" not in t:
                t["source_family"] = str(source.get("source_family") or canonical_source_family(source_id))
            if "observation_source_families" not in t:
                t["observation_source_families"] = list(source.get("observation_source_families") or [])
            key = (str(t.get("url") or ""), str(t.get("title") or "").lower(), str(t.get("content_unit") or t.get("kind") or ""))
            if key in seen:
                continue
            seen.add(key)
            traces.append(t)

    statuses = [str(x.get("status") or "FAILED") for x in combined_sources]
    successful = sum(1 for x in statuses if x == "SUCCESS")
    out["sources"] = combined_sources
    out["traces"] = traces[:160]
    out["expansion"] = {
        "status": expansion.get("status"),
        "plan": expansion.get("plan") or {},
        "elapsed_ms": expansion.get("elapsed_ms"),
        "source_count": len(expansion_sources),
        "trace_count": sum(int(x.get("count") or 0) for x in expansion_sources),
        "market_truth_writes": 0,
    }
    if expansion_sources:
        failed = len(statuses) - successful
        out["status"] = "PASS" if successful and not failed else ("PARTIAL" if successful else "FAILED")
    return out


def run_founder_observation_probe(
    title: str,
    description: str = "",
    *,
    search_query_override: str | None = None,
    relevance_query_override: str | None = None,
    semantic_hypothesis_override: str | None = None,
) -> dict[str, Any]:
    """Bounded research retrieval for one Founder idea.

    Use a small set of query lenses so the same click can retrieve actual problem
    discussions as well as existing alternatives. This is retrieval only; the
    lenses do not score or accept/reject the idea.
    """
    base = run_fresh_fast_probe(
        title, description,
        search_query_override=search_query_override,
        relevance_query_override=relevance_query_override,
        semantic_hypothesis_override=semantic_hypothesis_override,
    )
    hypothesis = _clean_text(semantic_hypothesis_override) or _clean_text(f"{title} {description}")
    fallback_query = str(base.get("search_query_used") or hypothesis).strip()
    raw_query = str(base.get("founder_query") or hypothesis).strip()
    relevance_query = str(base.get("relevance_query") or fallback_query).strip()
    retrieval_query = str(base.get("search_query_used") or fallback_query).strip()

    # Search vocabulary and relevance semantics are intentionally separate. The
    # retrieval bridge stays short for source recall; the richer relevance query
    # is used only after traces return.
    expansion_queries = list(dict.fromkeys([
        raw_query,
        retrieval_query,
        f"{retrieval_query} alternative competitor tool product".strip(),
    ]))[:3]
    expansion = run_source_expansion_queries(hypothesis, expansion_queries, max_queries=3)
    merged = merge_expansion_into_fresh(base, expansion)
    merged["source_profile_queries_used"] = expansion_queries
    return merged


_SEARCHERS: tuple[Callable[[str], dict[str, Any]], ...] = (
    _search_hn,
    _search_stackoverflow,
    _search_github_issues,
    _search_github_repositories,
)


def _base_searchers_for_hypothesis(hypothesis_text: str) -> tuple[Callable[[str], dict[str, Any]], ...]:
    """Return only base sources that are structurally suitable for the hypothesis.

    R7 always fired developer-heavy sources. R8 stops that behavior. Non-developer
    problems rely on Source Expansion / configured domain sources; if those are not
    configured, the correct output is SOURCE_FIT_INSUFFICIENT rather than GitHub/HN
    filler. This is routing metadata only and creates no market truth.
    """
    profile = source_fit_for_problem_class(hypothesis_text).get("source_profile")
    if profile == "DEVELOPER_TOOLING":
        return _SEARCHERS
    return ()


def _run_searcher(searcher: Callable[[str], dict[str, Any]], query: str) -> dict[str, Any]:
    source_name = searcher.__name__.removeprefix("_search_").upper()
    try:
        return searcher(query)
    except FetchError as exc:
        status = "RATE_LIMITED" if exc.status_code in {403, 429} else "FAILED"
        return {
            "source": source_name,
            "status": status,
            "query": query,
            "count": 0,
            "traces": [],
            "error": str(exc),
            "transport": {"status_code": exc.status_code, "retry_after": exc.retry_after, "rate_reset": exc.rate_reset, "response_body": exc.response_body},
        }
    except Exception as exc:
        return {"source": source_name, "status": "FAILED", "query": query, "count": 0, "traces": [], "error": f"{type(exc).__name__}: {exc}", "transport": {}}


def run_fresh_fast_probe(
    title: str,
    description: str = "",
    *,
    search_query_override: str | None = None,
    relevance_query_override: str | None = None,
    semantic_hypothesis_override: str | None = None,
) -> dict[str, Any]:
    queries = expand_founder_query(title, description)
    if not queries:
        return {"status": "INVALID_QUERY", "queries": [], "sources": [], "traces": [], "truth_boundary": TRUTH_BOUNDARY}

    # Prefer the hypothesis-specific bilingual bridge for English-heavy sources.
    # A generic source-profile query (for example ``developer workflow``) must
    # never replace a more specific Founder job merely because it is English.
    raw_query = _clean_text(f"{title} {description}")
    bridged_query = _bridged_founder_query(raw_query)
    if search_query_override:
        search_query = _clean_text(search_query_override)
    elif bridged_query and len(_tokens(bridged_query)) >= 3:
        search_query = bridged_query
    else:
        search_query = next((q for q in queries[1:] if re.search(r"[A-Za-z]", q) and len(_tokens(q)) >= 3), queries[0])
    has_han = bool(_HAN_RE.search(raw_query))
    effective_relevance = _clean_text(relevance_query_override) or _bridged_relevance_query(raw_query, bridged_query) or bridged_query or raw_query
    semantic_hypothesis = _clean_text(semantic_hypothesis_override) or effective_relevance or raw_query
    language_limited = has_han and not _bridge_is_searchable(search_query)
    started = time.perf_counter()
    base_searchers = _base_searchers_for_hypothesis(semantic_hypothesis)
    if base_searchers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(base_searchers)) as pool:
            futures = [pool.submit(_run_searcher, searcher, search_query) for searcher in base_searchers]
            sources = [f.result() for f in futures]
    else:
        sources = []

    traces: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for trace in source.get("traces") or []:
            key = (str(trace.get("url") or ""), str(trace.get("title") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            traces.append(trace)

    successful = [x for x in sources if x.get("status") == "SUCCESS"]
    failed = [x for x in sources if x.get("status") != "SUCCESS"]
    status = "PASS" if successful and not failed else ("PARTIAL" if successful else "FAILED")
    return {
        "engine_version": ENGINE_VERSION,
        "status": status,
        "founder_query": raw_query,
        "relevance_query": effective_relevance,
        "queries": queries,
        "search_query_used": search_query,
        "base_source_policy": {
            "source_profile": source_fit_for_problem_class(semantic_hypothesis).get("source_profile"),
            "base_sources": [fn.__name__.removeprefix("_search_").upper() for fn in base_searchers],
            "developer_heavy_sources_suppressed": not bool(base_searchers),
            "market_truth_writes": 0,
        },
        "language_coverage": "LIMITED_FOR_ENGLISH_HEAVY_SOURCES" if language_limited else "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "sources": sources,
        "traces": traces[:160],
        "truth_boundary": TRUTH_BOUNDARY,
    }



_RECURRENCE_COUNTABLE_AUTHORITIES = {
    "SOURCE_NATIVE_THREAD_ID",
    "EXPLICIT_SOURCE_INDEPENDENCE_VALIDATED",
    "FOUNDER_VALIDATED_INDEPENDENT",
}

def _recurrence_authority(trace: Mapping[str, Any]) -> str:
    md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
    return str((md or {}).get("recurrence_authority") or "UNVALIDATED").upper()

def _recurrence_is_countable(trace: Mapping[str, Any]) -> bool:
    return _recurrence_authority(trace) in _RECURRENCE_COUNTABLE_AUTHORITIES

def _evidence_lane(trace: Mapping[str, Any], relevance: Mapping[str, Any]) -> str:
    """Separate human conversations from solution/catalog/supporting artifacts.

    SignalForge's core product promise is market conversation retrieval. A repo,
    job post or news/article can still be useful R0 supporting evidence, but it
    must not masquerade as an independent human discussion or inflate author
    recurrence.
    """
    if bool((relevance.get("compatibility") or {}).get("trace_automated_operational_output")):
        return "AUTOMATED_ARTIFACT"
    kind = str(trace.get("kind") or "").upper()
    roles = set(relevance.get("problem_roles") or [])
    # Solution intent outranks platform/kind. A Show HN root post is a maker pitch,
    # not a user comment, even though the HN adapter represents both as DISCUSSION.
    if "EXISTING_SOLUTION" in roles or _looks_like_existing_solution(trace):
        return "EXISTING_SOLUTION"

    # Hacker News mixes link/story roots and actual comments under the same
    # DISCUSSION adapter kind. A normal root story is useful published material,
    # not a human comment. Ask HN is the exception because the root itself is the
    # user's question/problem statement. Direct child comments remain conversations.
    source = str(trace.get("source") or "").upper()
    md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
    content_unit = str(trace.get("content_unit") or (md or {}).get("content_unit") or "").upper()
    title = _clean_text(trace.get("title")).lower()
    if source in {"HACKER_NEWS_ALGOLIA", "HACKER_NEWS"} and content_unit in {"POST", "STORY"}:
        if title.startswith("ask hn:"):
            return "HUMAN_CONVERSATION"
        return "PUBLISHED_OR_MARKET_ARTIFACT"

    conversation_kinds = {
        "DISCUSSION", "ISSUE", "COMMENT", "REPLY", "POST", "STATUS", "TOPIC",
        "QUESTION", "ANSWER", "REVIEW", "MESSAGE",
    }
    if kind in conversation_kinds:
        return "HUMAN_CONVERSATION"
    if kind in {"NEWS", "ARTICLE", "JOB", "JOB_POST", "WEB_PAGE", "FEED_ITEM", "VIDEO"}:
        return "PUBLISHED_OR_MARKET_ARTIFACT"
    return "SUPPORTING_ARTIFACT"

def summarize_fresh_probe(fresh: Mapping[str, Any]) -> dict[str, Any]:
    hypothesis_text = _clean_text(fresh.get("founder_query") or "")
    raw_traces = [x for x in (fresh.get("traces") or []) if isinstance(x, Mapping)]
    annotated: list[dict[str, Any]] = []
    relevant_traces: list[dict[str, Any]] = []
    irrelevant_traces: list[dict[str, Any]] = []
    for raw in raw_traces:
        trace = dict(raw)
        if hypothesis_text:
            adjudicated = trace.get("adjudicated_relevance") if isinstance(trace.get("adjudicated_relevance"), Mapping) else None
            relevance = dict(adjudicated) if adjudicated else classify_trace_relevance(hypothesis_text=hypothesis_text, trace=trace)
        else:
            # Compatibility path for old deterministic fixtures that exercise lexical
            # cue behavior without a Founder hypothesis. Live Founder probes always
            # carry founder_query and therefore always pass through the relevance gate.
            roles: list[str] = []
            kind = str(trace.get("kind") or "").upper()
            signals = trace.get("signals") if isinstance(trace.get("signals"), Mapping) else {}
            if kind in {"DISCUSSION", "ISSUE"}: roles.append("PROBLEM_DISCUSSION")
            if (signals or {}).get("pain") and _is_firsthand_trace(trace): roles.append("FIRSTHAND_PAIN")
            if (signals or {}).get("workaround"): roles.append("WORKAROUND")
            if (signals or {}).get("paid"): roles.append("PAID_SIGNAL")
            if _looks_like_existing_solution(trace): roles.append("EXISTING_SOLUTION")
            relevance = {
                "state": "LEGACY_FIXTURE_NO_HYPOTHESIS", "countable": True,
                "reason": "No Founder hypothesis was supplied; lexical fixture compatibility path only.",
                "compatibility": {}, "problem_roles": roles, "truth_status": "UNVALIDATED_SEARCH_TRACE",
            }
        trace["thesis_relevance"] = relevance
        trace["evidence_lane"] = _evidence_lane(trace, relevance)
        if trace["evidence_lane"] == "EXISTING_SOLUTION":
            trace["solution_type"] = _solution_type(trace) or "PRODUCT_OR_SERVICE"
        annotated.append(trace)
        if relevance.get("countable"):
            relevant_traces.append(trace)
        else:
            irrelevant_traces.append(trace)

    relevance_grade_counts = {"R0": 0, "R1": 0, "R2": 0, "R3": 0, "OTHER": 0}
    for trace in annotated:
        rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
        grade = str(rel.get("grade") or "OTHER").upper()
        if grade not in relevance_grade_counts:
            grade = "OTHER"
        relevance_grade_counts[grade] += 1

    def has_role(trace: Mapping[str, Any], role: str) -> bool:
        rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
        return role in set(rel.get("problem_roles") or [])

    pain = [x for x in relevant_traces if has_role(x, "FIRSTHAND_PAIN")]
    workarounds = [x for x in relevant_traces if has_role(x, "WORKAROUND")]
    solutions = [x for x in relevant_traces if has_role(x, "EXISTING_SOLUTION")]
    paid = [x for x in relevant_traces if has_role(x, "PAID_SIGNAL")]
    paid_dissat = [x for x in paid if (x.get("signals") or {}).get("dissatisfaction")]

    # R8 Idea Research no longer runs Money Trail / paid-dissatisfaction analysis
    # in the normal idea scan. Those were product-decision heuristics, not required
    # for the current job: retrieve useful comments, market material and similar
    # products. Keep legacy fields empty for old callers that still deserialize them.
    spend_observations: list[dict[str, Any]] = []
    money_pd: list[dict[str, Any]] = []

    source_health = [
        {
            "source": x.get("source"),
            "source_family": str(x.get("source_family") or canonical_source_family(str(x.get("source") or ""))),
            "observation_source_families": list(dict.fromkeys(
                str(v).upper() for v in (x.get("observation_source_families") or observation_families_for_source(str(x.get("source") or ""))) if str(v).strip()
            )),
            "status": x.get("status"),
            "count": int(x.get("count") or 0),
            "error": x.get("error"),
            "transport": x.get("transport") or {},
            "final_search_query_used": x.get("final_search_query_used"),
            "query_contract": x.get("query_contract") or {},
            "discovery_scope": x.get("discovery_scope") or "STRUCTURED_SEARCH",
            "absence_adequacy": x.get("absence_adequacy") or "FULL",
        }
        for x in (fresh.get("sources") or [])
    ]
    success_count = sum(1 for x in source_health if x.get("status") == "SUCCESS")
    language_coverage = str(fresh.get("language_coverage") or "SUPPORTED_BY_CURRENT_QUERY_BRIDGE")
    if language_coverage == "LIMITED_FOR_ENGLISH_HEAVY_SOURCES" and success_count:
        coverage = "PARTIAL_LANGUAGE_COVERAGE"
    else:
        if success_count == len(source_health) and source_health:
            coverage = "COMPLETE_FOR_CONFIGURED_FAST_SOURCES" if len(source_health) == 4 else "COMPLETE_FOR_CONFIGURED_SOURCES"
        else:
            coverage = "PARTIAL" if success_count else "FAILED"

    conversation_r0 = [x for x in relevant_traces if x.get("evidence_lane") == "HUMAN_CONVERSATION"]
    solution_r0 = [x for x in relevant_traces if x.get("evidence_lane") == "EXISTING_SOLUTION"]
    supporting_r0 = [x for x in relevant_traces if x.get("evidence_lane") not in {"HUMAN_CONVERSATION", "EXISTING_SOLUTION"}]
    problem_discussion_traces = [x for x in conversation_r0 if has_role(x, "PROBLEM_DISCUSSION")]
    conversation_paid = [x for x in conversation_r0 if has_role(x, "PAID_SIGNAL")]
    solution_paid = [x for x in solution_r0 if has_role(x, "PAID_SIGNAL")]
    supporting_paid = [x for x in supporting_r0 if has_role(x, "PAID_SIGNAL")]
    conversation_paid_dissat = [x for x in conversation_paid if (x.get("signals") or {}).get("dissatisfaction")]

    def independence_key(trace: Mapping[str, Any], index: int) -> str:
        md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
        explicit = str((md or {}).get("independence_group_key") or "").strip()
        if explicit:
            return explicit
        source = str(trace.get("source") or "UNKNOWN")
        canonical = str((md or {}).get("canonical_url") or trace.get("url") or "").strip()
        if canonical:
            return f"{source}:url:{canonical}"
        # Missing thread identity must never collapse unrelated observations.
        return f"{source}:unresolved:{index}"

    # Keep observed conversation groups separate from *independent recurrence*.
    # Source Expansion may provide useful human-looking conversations while still
    # explicitly marking recurrence_authority=NONE. Those traces remain reviewable
    # but cannot inflate the independent-discussion or author recurrence metrics.
    observed_conversation_groups: dict[str, list[dict[str, Any]]] = {}
    authoritative_observed_group_keys: set[str] = set()
    independent_groups: dict[str, list[dict[str, Any]]] = {}
    recurrence_authority_counts: dict[str, int] = {}
    for idx, trace in enumerate(problem_discussion_traces):
        observed_key = independence_key(trace, idx)
        observed_conversation_groups.setdefault(observed_key, []).append(trace)
        authority = _recurrence_authority(trace)
        recurrence_authority_counts[authority] = recurrence_authority_counts.get(authority, 0) + 1
        if not _recurrence_is_countable(trace):
            continue
        authoritative_observed_group_keys.add(observed_key)
        md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
        # Near-duplicate/mirror clusters created by Source Expansion collapse to one
        # recurrence unit even if they arrived through different URLs or adapters.
        cluster_id = str((md or {}).get("observation_cluster_id") or "").strip()
        count_key = f"cluster:{cluster_id}" if cluster_id else observed_key
        independent_groups.setdefault(count_key, []).append(trace)

    authoritative_conversations = [x for x in conversation_r0 if _recurrence_is_countable(x)]
    conversation_authors = {
        str(x.get("author") or "").strip().lower()
        for x in authoritative_conversations if str(x.get("author") or "").strip()
    }
    observed_conversation_authors = {
        str(x.get("author") or "").strip().lower()
        for x in conversation_r0 if str(x.get("author") or "").strip()
    }
    all_r0_authors = {
        str(x.get("author") or "").strip().lower()
        for x in relevant_traces if str(x.get("author") or "").strip()
    }

    def contribution_source_id(trace: Mapping[str, Any]) -> str:
        # Legacy Part-1 GitHub adapters emitted both issue and repository traces as
        # GITHUB_SEARCH while source health correctly distinguished the transport.
        # Observation metrics must attribute a trace to the same source bucket used
        # by source health; this is metrics-only metadata and changes no evidence authority.
        sid = str(trace.get("source") or "UNKNOWN")
        if sid == "GITHUB_SEARCH":
            md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
            kind = str(trace.get("kind") or "").upper()
            if kind in {"ISSUE", "DISCUSSION"} or (md or {}).get("issue_number") is not None:
                return "GITHUB_ISSUES"
            if kind == "SOLUTION":
                return "GITHUB_REPOSITORIES"
        return sid

    per_source: dict[str, dict[str, Any]] = {}
    for row in source_health:
        sid = str(row.get("source") or "UNKNOWN")
        per_source[sid] = {
            "source": sid,
            "raw": int(row.get("count") or 0),
            "relevant": 0,
            "conversation_r0": 0,
            "solution_r0": 0,
            "supporting_r0": 0,
            "independent_discussions": 0,
            "unique_authors": 0,
        }
    rel_authors_by_source: dict[str, set[str]] = {}
    for trace in relevant_traces:
        sid = contribution_source_id(trace)
        per_source.setdefault(sid, {
            "source": sid, "raw": 0, "relevant": 0,
            "conversation_r0": 0, "solution_r0": 0, "supporting_r0": 0,
            "independent_discussions": 0, "unique_authors": 0,
        })
        per_source[sid]["relevant"] += 1
        lane = str(trace.get("evidence_lane") or "SUPPORTING_ARTIFACT")
        if lane == "HUMAN_CONVERSATION":
            per_source[sid]["conversation_r0"] += 1
            author = str(trace.get("author") or "").strip().lower()
            if author and _recurrence_is_countable(trace):
                rel_authors_by_source.setdefault(sid, set()).add(author)
        elif lane == "EXISTING_SOLUTION":
            per_source[sid]["solution_r0"] += 1
        else:
            per_source[sid]["supporting_r0"] += 1
    for members in independent_groups.values():
        source_ids = {contribution_source_id(x) for x in members}
        for sid in source_ids:
            per_source.setdefault(sid, {
                "source": sid, "raw": 0, "relevant": 0,
                "conversation_r0": 0, "solution_r0": 0, "supporting_r0": 0,
                "independent_discussions": 0, "unique_authors": 0,
            })
            per_source[sid]["independent_discussions"] += 1
    for sid, authors in rel_authors_by_source.items():
        per_source[sid]["unique_authors"] = len(authors)

    raw_trace_count = sum(int(x.get("count") or 0) for x in source_health) if source_health else len(raw_traces)

    # Founder primary evidence is conversation-first. Solution/catalog and
    # published/supporting artifacts remain visible in separate lanes instead of
    # impersonating human market conversations.
    def primary_score(trace: Mapping[str, Any]) -> tuple[int, int]:
        rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
        comp = rel.get("compatibility") if isinstance(rel.get("compatibility"), Mapping) else {}
        core = set(comp.get("core_problem_dimensions") or [])
        objects = set(comp.get("trace_objects") or [])
        roles = set(rel.get("problem_roles") or [])
        score = 0
        score += 8 * len(core)
        score += 5 if comp.get("workflow_identity_compatible") else 0
        score += 3 * len(objects & {"SOFTWARE_IMPLEMENTATION","CODE_CHANGE","REFACTOR","FEATURE","BUG_FIX"})
        score += 2 if "FIRSTHAND_PAIN" in roles else 0
        score += 2 if "WORKAROUND" in roles else 0
        score += 1 if "PAID_SIGNAL" in roles else 0
        return score, len(_clean_text(trace.get("excerpt")))

    primary_groups: dict[str, tuple[int, dict[str, Any]]] = {}
    group_order: list[str] = []
    for idx, trace in enumerate(conversation_r0):
        key = independence_key(trace, idx)
        if key not in primary_groups:
            primary_groups[key] = (idx, trace)
            group_order.append(key)
            continue
        _, current = primary_groups[key]
        if primary_score(trace) > primary_score(current):
            primary_groups[key] = (idx, trace)

    founder_primary_conversations = [primary_groups[key][1] for key in group_order][:12]
    founder_recurrence_conversations = [
        x for x in founder_primary_conversations if _recurrence_is_countable(x)
    ]
    founder_unvalidated_conversations = [
        x for x in founder_primary_conversations if not _recurrence_is_countable(x)
    ]

    def unique_artifacts(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        seen_keys: set[str] = set()
        out_rows: list[dict[str, Any]] = []
        for idx, trace in enumerate(sorted(rows, key=primary_score, reverse=True)):
            md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
            key = str((md or {}).get("canonical_url") or trace.get("url") or f"artifact:{idx}")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out_rows.append(trace)
            if len(out_rows) >= limit:
                break
        return out_rows

    founder_solution_traces = unique_artifacts(solution_r0, 6)
    founder_supporting_traces = unique_artifacts(supporting_r0, 6)
    founder_primary_traces = [
        *founder_primary_conversations,
        *founder_solution_traces,
        *founder_supporting_traces,
    ][:18]
    evidence_lane_counts = {
        "HUMAN_CONVERSATION": len(conversation_r0),
        "EXISTING_SOLUTION": len(solution_r0),
        "SUPPORTING_ARTIFACT": len(supporting_r0),
    }
    return {
        "founder_query": hypothesis_text,
        "problem_discussions": len(problem_discussion_traces),
        "problem_discussion_trace_count": len(problem_discussion_traces),
        "firsthand_pain": len(pain),
        "workarounds": len(workarounds),
        "existing_solutions": len(solutions),
        # Founder money counters require a human-conversation lane. Product pricing,
        # catalog pages and articles remain visible separately and cannot impersonate
        # buyer spend / post-purchase dissatisfaction.
        "paid_signals": len(conversation_paid),
        "post_purchase_complaints": len(conversation_paid_dissat),
        "all_r0_paid_signal_count": len(paid),
        "all_r0_post_purchase_complaint_count": len(paid_dissat),
        "conversation_paid_signal_count": len(conversation_paid),
        "solution_paid_signal_count": len(solution_paid),
        "supporting_paid_signal_count": len(supporting_paid),
        "raw_trace_count": raw_trace_count,
        "merged_trace_count": len(raw_traces),
        "relevant_trace_count": len(relevant_traces),
        "irrelevant_trace_count": len(irrelevant_traces),
        "relevance_grade_counts": relevance_grade_counts,
        "evidence_lane_counts": evidence_lane_counts,
        "conversation_r0_count": len(conversation_r0),
        "solution_r0_count": len(solution_r0),
        "supporting_r0_count": len(supporting_r0),
        "observed_conversation_group_count": len(observed_conversation_groups),
        "independent_discussion_count": len(independent_groups),
        "unvalidated_conversation_group_count": max(0, len(observed_conversation_groups) - len(authoritative_observed_group_keys)),
        "cluster_collapsed_authoritative_group_count": max(0, len(authoritative_observed_group_keys) - len(independent_groups)),
        "recurrence_authority_counts": recurrence_authority_counts,
        "unique_author_count": len(conversation_authors),
        "observed_conversation_author_count": len(observed_conversation_authors),
        "all_r0_author_count": len(all_r0_authors),
        "source_contribution": [per_source[k] for k in sorted(per_source)],
        "founder_primary_conversations": founder_primary_conversations,
        "founder_recurrence_conversations": founder_recurrence_conversations,
        "founder_unvalidated_conversations": founder_unvalidated_conversations,
        "founder_solution_traces": founder_solution_traces,
        "founder_supporting_traces": founder_supporting_traces,
        "founder_primary_traces": founder_primary_traces,
        "trace_relevance": [
            {
                "source": x.get("source"), "title": x.get("title"), "url": x.get("url"),
                "evidence_lane": x.get("evidence_lane"),
                "relevance": x.get("thesis_relevance"),
            } for x in annotated[:40]
        ],
        "inspectable_irrelevant_traces": [
            {
                "source": x.get("source"), "title": x.get("title"), "excerpt": x.get("excerpt"),
                "url": x.get("url"), "evidence_lane": x.get("evidence_lane"),
                "thesis_relevance": x.get("thesis_relevance"),
                "truth_status": "UNVALIDATED_SEARCH_TRACE",
            } for x in irrelevant_traces[:20]
        ],
        "spend_observations": spend_observations[:16],
        "paid_dissatisfaction_observations": money_pd[:12],
        "source_health": source_health,
        "coverage": coverage,
        "language_coverage": language_coverage,
        "truth_boundary": "SEARCH_HIT_MUST_PASS_SPECIFIC_PROBLEM_RELEVANCE_BEFORE_ANY_FOUNDER_COUNTER;_INDEPENDENT_DISCUSSION_AND_AUTHOR_RECURRENCE_REQUIRE_EXPLICIT_RECURRENCE_AUTHORITY;_NON_CONVERSATION_PRICING_CANNOT_IMPERSONATE_BUYER_SPEND;_IRRELEVANT_TRACES_REMAIN_INSPECTABLE_BUT_CANNOT_AFFECT_MARKET_TRUTH",
    }



def summarize_idea_research_probe(fresh: Mapping[str, Any]) -> dict[str, Any]:
    """Lightweight summary used by the actual Idea Research product path.

    The old ``summarize_fresh_probe`` is intentionally left in this module for
    compatibility with older engineering tools. Normal Founder scans no longer
    calculate recurrence authority, paid-signal economics, source-absence
    adequacy, Money Trail inputs, or opportunity-decision counters.
    """
    hypothesis_text = _clean_text(fresh.get("relevance_query") or fresh.get("founder_query") or "")
    raw_traces = [dict(x) for x in (fresh.get("traces") or []) if isinstance(x, Mapping)]

    relevant: list[dict[str, Any]] = []
    irrelevant: list[dict[str, Any]] = []
    annotated: list[dict[str, Any]] = []
    for trace in raw_traces:
        adjudicated = trace.get("adjudicated_relevance") if isinstance(trace.get("adjudicated_relevance"), Mapping) else None
        relevance = dict(adjudicated) if adjudicated else classify_trace_relevance(
            hypothesis_text=hypothesis_text,
            trace=trace,
        )
        trace["thesis_relevance"] = relevance
        trace["evidence_lane"] = _evidence_lane(trace, relevance)
        if trace["evidence_lane"] == "EXISTING_SOLUTION":
            trace["solution_type"] = _solution_type(trace) or "PRODUCT_OR_SERVICE"

        # Idea Research is deliberately broader than the old Market Truth gate.
        # R0 is an exact match; R1 is a close same-workflow/problem neighbor that
        # is still useful research material. R2/R3 remain inspectable only. This
        # avoids throwing away real user comments merely because they say
        # ``review this AI-generated PR`` instead of the ontology phrase
        # ``completion verification``. No market-truth authority is created here.
        grade = str(relevance.get("grade") or "R3").upper()
        research_usable = bool(relevance.get("countable")) or grade == "R1"
        trace["research_match"] = "EXACT" if bool(relevance.get("countable")) else ("RELATED" if grade == "R1" else "EXCLUDED")
        annotated.append(trace)
        (relevant if research_usable else irrelevant).append(trace)

    def source_health_row(row: Mapping[str, Any]) -> dict[str, Any]:
        source_id = str(row.get("source") or "")
        return {
            "source": source_id,
            "source_family": str(row.get("source_family") or canonical_source_family(source_id)),
            "status": row.get("status"),
            "count": int(row.get("count") or 0),
            "error": row.get("error"),
            "query_variants": list(row.get("query_variants") or []),
            "final_search_query_used": row.get("final_search_query_used"),
        }

    source_health = [source_health_row(x) for x in (fresh.get("sources") or []) if isinstance(x, Mapping)]

    def trace_key(trace: Mapping[str, Any], index: int) -> str:
        md = trace.get("metadata") if isinstance(trace.get("metadata"), Mapping) else {}
        canonical = str((md or {}).get("canonical_url") or trace.get("url") or "").strip().lower()
        author = str(trace.get("author") or "").strip().lower()
        title = _clean_text(trace.get("title")).lower()
        excerpt = _clean_text(trace.get("excerpt")).lower()[:240]
        if canonical:
            return f"url:{canonical}|author:{author}|excerpt:{excerpt}"
        return f"fallback:{trace.get('source')}|{title}|{author}|{excerpt}|{index}"

    def research_score(trace: Mapping[str, Any]) -> tuple[int, int, int]:
        rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
        roles = set((rel or {}).get("problem_roles") or [])
        score = 0
        match_level = str(trace.get("research_match") or "")
        score += 12 if match_level == "EXACT" else (4 if match_level == "RELATED" else 0)
        score += 6 if "FIRSTHAND_PAIN" in roles else 0
        score += 3 if "WORKAROUND" in roles else 0
        score += 2 if "PROBLEM_DISCUSSION" in roles else 0
        score += 1 if "PAID_SIGNAL" in roles else 0
        kind = str(trace.get("kind") or "").upper()
        score += 2 if kind in {"REVIEW", "COMMENT", "REPLY", "ANSWER"} else 0
        return score, bool(str(trace.get("author") or "").strip()), len(_clean_text(trace.get("excerpt")))

    def unique_ranked(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, trace in enumerate(sorted(rows, key=research_score, reverse=True)):
            key = trace_key(trace, idx)
            if key in seen:
                continue
            seen.add(key)
            out.append(trace)
            if len(out) >= limit:
                break
        return out

    conversations = unique_ranked(
        [x for x in relevant if x.get("evidence_lane") == "HUMAN_CONVERSATION"],
        12,
    )
    solution_rows = [x for x in relevant if x.get("evidence_lane") == "EXISTING_SOLUTION"]
    products = unique_ranked(
        [x for x in solution_rows if str(x.get("solution_type") or "") != "OPEN_SOURCE_OR_REPO"],
        8,
    )
    repo_solutions = unique_ranked(
        [x for x in solution_rows if str(x.get("solution_type") or "") == "OPEN_SOURCE_OR_REPO"],
        10,
    )
    supporting = unique_ranked(
        [x for x in relevant if x.get("evidence_lane") not in {"HUMAN_CONVERSATION", "EXISTING_SOLUTION", "AUTOMATED_ARTIFACT"}],
        10,
    )

    return {
        "founder_query": hypothesis_text,
        "raw_trace_count": len(raw_traces),
        "relevant_trace_count": len(relevant),
        "irrelevant_trace_count": len(irrelevant),
        "founder_primary_conversations": conversations,
        "founder_solution_traces": products,
        "founder_repo_solution_traces": repo_solutions,
        "founder_supporting_traces": supporting,
        "inspectable_irrelevant_traces": irrelevant[:20],
        "source_health": source_health,
        "language_coverage": fresh.get("language_coverage") or "SUPPORTED_BY_CURRENT_QUERY_BRIDGE",
        "trace_relevance": [
            {
                "source": x.get("source"),
                "kind": x.get("kind"),
                "title": x.get("title"),
                "url": x.get("url"),
                "evidence_lane": x.get("evidence_lane"),
                "relevance": x.get("thesis_relevance"),
            }
            for x in annotated[:40]
        ],
        "market_truth_writes": 0,
        "diagnostic_mode": "LIGHTWEIGHT_IDEA_RESEARCH",
    }


_COUNTER_EVIDENCE_CUES = (
    "works fine", "works well", "good enough", "already solved", "already handles",
    "built in", "built-in", "native support", "no need", "would not pay",
    "wouldn't pay", "not worth paying", "not worth", "no budget", "free enough", "rare problem",
    "not a problem", "not an issue", "not useful", "pointless", "poor results",
    "too much noise", "so much noise", "doesn't catch", "does not catch", "don't catch", "do not catch",
    "solved for us", "we stopped using",
    "已經解決", "已經有了", "夠用了", "就夠了", "不需要", "不會付費",
    "不值得付費", "沒有預算", "沒預算", "不是問題", "不算問題", "免費就夠",
)


def _research_trace_card(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Small Founder-facing card. Hide internal adjudication machinery by default."""
    rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
    return {
        "source": trace.get("source"),
        "kind": trace.get("kind"),
        "title": _clean_text(trace.get("title"))[:280],
        "excerpt": _clean_text(trace.get("excerpt"))[:1200],
        "url": trace.get("url"),
        "author": trace.get("author"),
        "created_at": trace.get("created_at"),
        "solution_type": trace.get("solution_type"),
        "match_level": trace.get("research_match"),
        "why_relevant": _clean_text((rel or {}).get("reason"))[:420] or None,
    }


def _looks_like_counter_evidence(trace: Mapping[str, Any]) -> bool:
    # Counter evidence still has to be about the idea. Allow exact matches and
    # close R1/R2 adjacency, but never let a totally unrelated R3 page become
    # "counter evidence" merely because it contains words like good enough.
    rel = trace.get("thesis_relevance") if isinstance(trace.get("thesis_relevance"), Mapping) else {}
    if rel:
        grade = str((rel or {}).get("grade") or "").upper()
        if not bool((rel or {}).get("countable")) and grade not in {"R1", "R2"}:
            return False
    text = _clean_text(f"{trace.get('title')} {trace.get('excerpt')}").lower()
    return any(_cue_present(text, cue) for cue in _COUNTER_EVIDENCE_CUES)


def build_founder_research_brief(
    *,
    title: str,
    description: str,
    fresh: Mapping[str, Any],
    fresh_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Founder-facing product contract for the simplified SignalForge.

    SignalForge is an idea research agent, not an opportunity judge. It retrieves
    and organizes material that helps the Founder decide: human comments, similar
    products, supporting material and evidence that pushes against the idea.
    """
    conversations = [dict(x) for x in (fresh_summary.get("founder_primary_conversations") or []) if isinstance(x, Mapping)]
    products = [dict(x) for x in (fresh_summary.get("founder_solution_traces") or []) if isinstance(x, Mapping)]
    repo_solutions = [dict(x) for x in (fresh_summary.get("founder_repo_solution_traces") or []) if isinstance(x, Mapping)]
    supporting = [dict(x) for x in (fresh_summary.get("founder_supporting_traces") or []) if isinstance(x, Mapping)]

    # Counter-evidence can live in any useful lane. Do not require it to be R0;
    # a close adjacent result saying the problem is already solved is worth showing.
    counter_pool: list[dict[str, Any]] = []
    seen_counter: set[str] = set()
    for row in [*conversations, *products, *repo_solutions, *supporting, *[
        dict(x) for x in (fresh_summary.get("inspectable_irrelevant_traces") or []) if isinstance(x, Mapping)
    ]]:
        if not _looks_like_counter_evidence(row):
            continue
        key = str(row.get("url") or "") + "|" + _clean_text(row.get("title")).lower()
        if key in seen_counter:
            continue
        seen_counter.add(key)
        counter_pool.append(row)
        if len(counter_pool) >= 8:
            break

    source_health = [dict(x) for x in (fresh_summary.get("source_health") or []) if isinstance(x, Mapping)]
    successful_sources = [x for x in source_health if str(x.get("status") or "").upper() == "SUCCESS"]
    failed_sources = [x for x in source_health if str(x.get("status") or "").upper() != "SUCCESS"]

    gaps: list[str] = []
    if not conversations:
        gaps.append("目前沒有找到夠相關的真人留言。")
    if not products and not repo_solutions:
        gaps.append("目前沒有找到夠相近的現有產品／替代方案。")
    elif not products and repo_solutions:
        gaps.append("目前找到的是 repo／開源方案，還沒有找到明確的正式產品或服務。")
    if not supporting:
        gaps.append("目前沒有找到額外的市場／技術／新聞／職缺等旁證。")
    if failed_sources:
        gaps.append("部分資料來源這次搜尋失敗或受限，結果可能不完整。")
    if str(fresh_summary.get("language_coverage") or "").upper() == "LIMITED_FOR_ENGLISH_HEAVY_SOURCES":
        gaps.append("這次英文來源的查詢轉換有限，可能漏掉部分英文討論。")

    useful_count = len(conversations) + len(products) + len(repo_solutions) + len(supporting)
    return {
        "mode": "IDEA_RESEARCH",
        "idea": {"title": title, "description": description},
        "summary": {
            "useful_result_count": useful_count,
            "human_comment_count": len(conversations),
            # Compatibility total plus explicit Founder-facing split.
            "similar_product_count": len(products) + len(repo_solutions),
            "product_or_service_count": len(products),
            "repo_solution_count": len(repo_solutions),
            "supporting_evidence_count": len(supporting),
            "counter_evidence_count": len(counter_pool),
        },
        "human_comments": [_research_trace_card(x) for x in conversations[:12]],
        "similar_products": [_research_trace_card(x) for x in products[:8]],
        "repo_solutions": [_research_trace_card(x) for x in repo_solutions[:10]],
        "supporting_evidence": [_research_trace_card(x) for x in supporting[:10]],
        "counter_evidence": [_research_trace_card(x) for x in counter_pool[:8]],
        "gaps": gaps,
        "search": {
            "queries": list(fresh.get("queries") or []),
            "source_profile_queries": list(fresh.get("source_profile_queries_used") or []),
            "successful_sources": [str(x.get("source") or "") for x in successful_sources],
            "failed_sources": [
                {"source": x.get("source"), "status": x.get("status"), "error": x.get("error")}
                for x in failed_sources
            ],
            "elapsed_ms": fresh.get("elapsed_ms"),
            "query_bridge": dict(fresh.get("query_bridge") or {}) if isinstance(fresh.get("query_bridge"), Mapping) else {},
        },
        "note": "SignalForge 整理資料，不替 Founder 判定這個 idea 值不值得做。",
    }


def _research_status(*, collection_status: str, research_brief: Mapping[str, Any]) -> str:
    summary = research_brief.get("summary") if isinstance(research_brief.get("summary"), Mapping) else {}
    useful = int((summary or {}).get("useful_result_count") or 0)
    successful = list(((research_brief.get("search") or {}) if isinstance(research_brief.get("search"), Mapping) else {}).get("successful_sources") or [])
    failed = list(((research_brief.get("search") or {}) if isinstance(research_brief.get("search"), Mapping) else {}).get("failed_sources") or [])
    if not successful and str(collection_status or "").upper() == "FAILED":
        return "SEARCH_FAILED"
    # Idea Research is a retrieval product, not a completeness judge. Once there
    # is useful material, return it as ready and keep optional source failures in
    # ``gaps``/diagnostics instead of downgrading the whole scan. A partial status
    # is reserved for the ambiguous case where useful material is still empty.
    if useful > 0:
        return "RESEARCH_READY"
    if successful and failed:
        return "RESEARCH_PARTIAL"
    if successful:
        return "NO_RELEVANT_RESULTS"
    return "SEARCH_PARTIAL"


_CONFIGURED_FAST_SOURCE_COUNT = 4


def build_source_adequacy(*, fresh_summary: Mapping[str, Any], source_fit: Mapping[str, Any]) -> dict[str, Any]:
    """Separate transport health, positive discovery fit, and absence fit.

    R8 WIP4 fixes two important conflations:
      * FAILED/RATE_LIMITED sources do not count as observed source-family coverage;
      * a PARTIAL-absence source may contribute positive evidence, but cannot by
        itself make a zero-result source set sufficient for market-absence logic.

    A redundant optional source failure therefore stays visible as transport PARTIAL
    without erasing useful evidence from successful, source-fit families.
    """
    health = [x for x in (fresh_summary.get("source_health") or []) if isinstance(x, Mapping)]
    coverage = str(fresh_summary.get("coverage") or "").upper()
    language_ok = str(fresh_summary.get("language_coverage") or "").upper() != "LIMITED_FOR_ENGLISH_HEAVY_SOURCES"

    successful_rows = [x for x in health if str(x.get("status") or "").upper() == "SUCCESS"]
    failed_rows = [x for x in health if str(x.get("status") or "").upper() != "SUCCESS"]
    if health:
        if successful_rows and not failed_rows:
            transport_state = "TRANSPORT_COMPLETE"
        elif successful_rows:
            transport_state = "TRANSPORT_PARTIAL"
        else:
            transport_state = "TRANSPORT_FAILED"
    else:
        transport_state = "TRANSPORT_COMPLETE" if coverage in {"COMPLETE_FOR_CONFIGURED_FAST_SOURCES", "COMPLETE_FOR_CONFIGURED_SOURCES"} else "TRANSPORT_EMPTY"
    transport_complete = transport_state == "TRANSPORT_COMPLETE"

    observed_families_list: list[str] = []
    adequate_families_list: list[str] = []
    limited_absence_sources: list[str] = []
    for row in successful_rows:
        family = str(row.get("source_family") or canonical_source_family(str(row.get("source") or ""))).upper()
        row_families = ([family] if family else []) + [
            str(x).upper() for x in (row.get("observation_source_families") or []) if str(x).strip()
        ]
        observed_families_list.extend(row_families)
        if str(row.get("absence_adequacy") or "FULL").upper() == "FULL":
            adequate_families_list.extend(row_families)
        else:
            limited_absence_sources.append(str(row.get("source") or row.get("source_family") or "UNKNOWN"))

    observed_families = list(dict.fromkeys(observed_families_list))
    absence_families = list(dict.fromkeys(adequate_families_list))
    hypothesis_text = str(fresh_summary.get("founder_query") or source_fit.get("hypothesis_text") or "")

    if hypothesis_text:
        positive_fit = source_fit_for_problem_class(hypothesis_text, configured_source_families=observed_families)
        absence_fit = source_fit_for_problem_class(hypothesis_text, configured_source_families=absence_families)
    else:
        positive_fit = dict(source_fit)
        absence_fit = dict(source_fit)

    positive_state = str(positive_fit.get("source_fit_state") or "UNKNOWN").upper()
    absence_state = str(absence_fit.get("source_fit_state") or "UNKNOWN").upper()
    positive_sufficient = positive_state == "SUFFICIENT"
    absence_sufficient = absence_state == "SUFFICIENT"
    source_set_complete = bool(language_ok and absence_sufficient)

    return {
        "transport_state": transport_state,
        "transport_complete": transport_complete,
        "transport_has_success": bool(successful_rows),
        "successful_source_count": len(successful_rows),
        "failed_source_count": len(failed_rows),
        "failed_sources": [str(x.get("source") or x.get("source_family") or "UNKNOWN") for x in failed_rows],
        "source_set_state": "SOURCE_SET_COMPLETE" if source_set_complete else "SOURCE_SET_INCOMPLETE",
        "source_set_complete": source_set_complete,
        "observed_source_families": observed_families,
        "absence_adequate_source_families": absence_families,
        "limited_absence_sources": list(dict.fromkeys(limited_absence_sources)),
        "positive_source_fit_state": "SOURCE_FIT_SUFFICIENT" if positive_sufficient else ("SOURCE_FIT_INSUFFICIENT" if positive_state == "INSUFFICIENT" else "SOURCE_FIT_UNKNOWN"),
        "positive_source_fit_sufficient": positive_sufficient,
        "absence_source_fit_state": "SOURCE_FIT_SUFFICIENT" if absence_sufficient else ("SOURCE_FIT_INSUFFICIENT" if absence_state == "INSUFFICIENT" else "SOURCE_FIT_UNKNOWN"),
        "absence_source_fit_sufficient": absence_sufficient,
        # Compatibility field: zero/absence decisions require FULL-absence fit.
        "source_fit_state": "SOURCE_FIT_SUFFICIENT" if absence_sufficient else ("SOURCE_FIT_INSUFFICIENT" if absence_state == "INSUFFICIENT" else "SOURCE_FIT_UNKNOWN"),
        "source_fit_sufficient": absence_sufficient,
        "source_profile": absence_fit.get("source_profile") or positive_fit.get("source_profile") or source_fit.get("source_profile"),
        "configured_source_profile": "ACTUAL_SUCCESSFUL_SOURCE_FAMILIES",
        "configured_source_count": len(successful_rows),
        "configured_source_families": absence_families,
        "adequate_observation_source_families": list(absence_fit.get("adequate_observation_source_families") or source_fit.get("adequate_observation_source_families") or []),
        "matched_observation_source_families": list(absence_fit.get("matched_observation_source_families") or []),
        "required_observation_dimensions": dict(absence_fit.get("required_observation_dimensions") or {}),
        "matched_observation_dimensions": dict(absence_fit.get("matched_observation_dimensions") or {}),
        "missing_observation_dimensions": [
            str(k) for k, v in (absence_fit.get("matched_observation_dimensions") or {}).items() if not v
        ],
        "positive_matched_observation_dimensions": dict(positive_fit.get("matched_observation_dimensions") or {}),
        "observation_dimensions_complete": bool(absence_fit.get("observation_dimensions_complete", True)),
        "reason": absence_fit.get("source_fit_reason") or source_fit.get("source_fit_reason") or source_fit.get("reason"),
        "recommended_source_families": list(absence_fit.get("recommended_source_families") or source_fit.get("recommended_source_families") or []),
        "market_truth_writes": 0,
        "truth_boundary": "FAILED_SOURCES_DO_NOT_COUNT_AS_COVERAGE;_PARTIAL_ABSENCE_SOURCES_MAY_ADD_POSITIVE_EVIDENCE_BUT_NOT_ZERO_ABSENCE_AUTHORITY;_TRANSPORT_SOURCE_SET_AND_SOURCE_FIT_REMAIN_SEPARATE",
    }


def _attach_fresh_source_fit(*, hypothesis_text: str, fresh_summary: dict[str, Any]) -> dict[str, Any]:
    # Only successfully observed source families may satisfy positive source fit.
    # Failed/rate-limited adapters remain visible in source health but contribute
    # zero source-family coverage.
    successful_families: list[str] = []
    for row in (fresh_summary.get("source_health") or []):
        if not isinstance(row, Mapping) or str(row.get("status") or "").upper() != "SUCCESS":
            continue
        successful_families.append(str(row.get("source_family") or canonical_source_family(str(row.get("source") or ""))))
        successful_families.extend(str(v) for v in (row.get("observation_source_families") or []))
    successful_families = list(dict.fromkeys(v for v in successful_families if v))
    source_fit = source_fit_for_problem_class(hypothesis_text, configured_source_families=successful_families)
    source_fit["hypothesis_text"] = hypothesis_text
    fresh_summary["source_fit"] = source_fit
    fresh_summary["source_adequacy"] = build_source_adequacy(fresh_summary=fresh_summary, source_fit=source_fit)
    return source_fit


def probe_founder_observation_only(*, title: str, description: str = "") -> dict[str, Any]:
    """Synchronous idea research scan for tests/benchmarks and non-async callers."""
    title = _clean_text(title)
    description = _clean_text(description)
    if len(title) < 2:
        return {"engine_version": ENGINE_VERSION, "status": "INVALID_QUERY", "mode": "IDEA_RESEARCH", "market_truth_writes": 0}
    hypothesis_text = f"{title} {description}".strip()
    fresh = run_founder_observation_probe(title, description)
    fresh_summary = summarize_idea_research_probe(fresh)
    brief = build_founder_research_brief(title=title, description=description, fresh=fresh, fresh_summary=fresh_summary)
    status = _research_status(collection_status=str(fresh.get("status") or ""), research_brief=brief)
    return {
        "engine_version": ENGINE_VERSION,
        "mode": "IDEA_RESEARCH",
        "status": status,
        "idea": {"title": title, "description": description},
        "research_brief": brief,
        # Compatibility/debug lane for the existing UI and engineering tools. The
        # product surface should render research_brief, not these internal counters.
        "fast_probe": {"legacy_collection_status": fresh.get("status"), "elapsed_ms": fresh.get("elapsed_ms"), **fresh_summary},
        "market_truth_writes": 0,
        "truth_boundary": "RESEARCH_OUTPUT_ONLY;_NO_AUTOMATIC_OPPORTUNITY_SCORE_OR_PRODUCT_ACCEPTANCE_DECISION;_NO_MARKET_TRUTH_WRITE",
    }

async def probe_founder_idea(*, title: str, description: str = "") -> dict[str, Any]:
    """Canonical SignalForge product path: idea -> research brief.

    The agent searches, filters obvious mismatches, deduplicates, separates human
    conversations from products/supporting material, and returns the evidence for
    Founder judgment. It does not score or accept/reject the business idea.
    """
    title = _clean_text(title)
    description = _clean_text(description)
    if len(title) < 2:
        return {
            "engine_version": ENGINE_VERSION,
            "mode": "IDEA_RESEARCH",
            "status": "INVALID_QUERY",
            "message": "Idea title must contain at least 2 characters.",
            "market_truth_writes": 0,
        }

    hypothesis_text = f"{title} {description}".strip()
    query_bridge = await _prepare_query_bridge(hypothesis_text)
    search_override = _clean_text(query_bridge.get("retrieval_query"))
    relevance_override = _clean_text(query_bridge.get("relevance_query"))
    fresh = await asyncio.to_thread(
        run_founder_observation_probe,
        title,
        description,
        search_query_override=search_override or None,
        relevance_query_override=relevance_override or None,
        semantic_hypothesis_override=relevance_override or search_override or None,
    )
    fresh["query_bridge"] = dict(query_bridge)
    if str(query_bridge.get("status") or "") == "LIMITED_FALLBACK":
        fresh["language_coverage"] = "LIMITED_FOR_ENGLISH_HEAVY_SOURCES"

    # Optional semantic cleanup is off by default. If explicitly enabled it may
    # improve precision, but SignalForge remains useful without an LLM judge.
    fresh, relevance_adjudication = await adjudicate_fresh_relevance(fresh)
    fresh_summary = summarize_idea_research_probe(fresh)
    fresh_summary["relevance_adjudication"] = relevance_adjudication

    brief = build_founder_research_brief(
        title=title,
        description=description,
        fresh=fresh,
        fresh_summary=fresh_summary,
    )
    status = _research_status(collection_status=str(fresh.get("status") or ""), research_brief=brief)

    result = {
        "engine_version": ENGINE_VERSION,
        "mode": "IDEA_RESEARCH",
        "status": status,
        "idea": {"title": title, "description": description},
        "research_brief": brief,
        # Keep this for old callers during the transition. It is diagnostic only.
        "fast_probe": {
            "legacy_collection_status": fresh.get("status"),
            "elapsed_ms": fresh.get("elapsed_ms"),
            **fresh_summary,
        },
        "market_truth_writes": 0,
        "ai_api_calls": int(query_bridge.get("api_calls") or 0) + int(relevance_adjudication.get("api_calls") or 0),
        "query_bridge": dict(query_bridge),
        "truth_boundary": "RESEARCH_OUTPUT_ONLY;_NO_AUTOMATIC_OPPORTUNITY_SCORE_OR_PRODUCT_ACCEPTANCE_DECISION;_NO_MARKET_TRUTH_WRITE",
    }
    try:
        handoff = await asyncio.to_thread(
            record_founder_hypothesis_probe,
            title=title,
            description=description,
            probe=result,
        )
    except Exception as exc:
        handoff = {
            "status": "FOUNDER_HANDOFF_PERSISTENCE_FAILED_VISIBLE",
            "error": f"{type(exc).__name__}: {exc}",
            "market_truth_writes": 0,
        }
    result["founder_hypothesis_handoff"] = handoff
    return result

