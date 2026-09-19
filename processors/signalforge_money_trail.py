from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select

from processors.signalforge_founder_query_contracts import semantic_profile

from database.connection import (
    async_session,
    ProblemCandidate,
    RadarCase,
    RadarClaim,
    RadarClaimEvidence,
    RadarEvidence,
)

ENGINE_VERSION = "signalforge-money-trail-revenue-wedge-v1"
TRUTH_BOUNDARY = (
    "MONEY_TRAIL_IS_A_DERIVED_FOUNDER_PROJECTION_OVER_EXISTING_PUBLISHED_EVIDENCE;_"
    "IT_NEVER_CREATES_C01_C14_OR_MARKET_TRUTH_AND_NEVER_INVENTS_NUMERIC_SPEND"
)

SPEND_BUCKETS = (
    "VENDOR_SPEND",
    "LABOR_SPEND",
    "CONTRACTOR_SPEND",
    "REWORK_COST",
    "RISK_COST",
    "LOST_REVENUE",
)

_SPEND_PATTERNS: dict[str, tuple[str, ...]] = {
    "VENDOR_SPEND": (
        "subscription", "license", "licence", "seat", "per user", "per month", "monthly",
        "pricing", "price", "paid plan", "we pay", "pay for", "costs $", "cost $", "saas",
        "tooling", "vendor", "plan costs", "annual plan",
    ),
    "LABOR_SPEND": (
        "engineer hours", "engineering hours", "developer hours", "qa hours", "manual qa",
        "manual review", "senior engineer", "code review", "review time", "hours per", "person-hours",
        "man-hours", "staff time", "employee time", "manual work", "manually",
    ),
    "CONTRACTOR_SPEND": (
        "contractor", "consultant", "freelancer", "outsourc", "external qa", "testing vendor",
        "agency fee", "consulting fee", "contracted",
    ),
    "REWORK_COST": (
        "rework", "redo", "do over", "fix again", "bug fixing", "bugfix", "rollback", "hotfix",
        "failed delivery", "client rework", "regression", "defect escape", "repeat work",
    ),
    "RISK_COST": (
        "incident", "security breach", "compliance", "fine", "penalty", "liability", "audit failure",
        "downtime", "outage", "sla", "breach", "risk cost",
    ),
    "LOST_REVENUE": (
        "lost revenue", "lost sale", "churn", "customer churn", "refund", "missed revenue",
        "missed deadline", "delay launch", "delayed launch", "lost customer", "revenue loss",
    ),
}

_PAID_TERMS = (
    "we pay", "i pay", "pay for", "paid for", "paying for", "subscription", "license", "licence", "pricing",
    "per month", "monthly", "annual plan", "bought", "purchased", "customer of",
)
_DISSATISFACTION_TERMS = (
    "but still", "still have to", "still need", "doesn't", "does not", "doesn’t", "can't", "cannot",
    "manual", "manually", "workaround", "switched from", "switch away", "not enough", "fails",
    "failure", "broken", "unreliable", "missing", "frustrat", "pain", "slow", "rework", "redo",
)

_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:US\$|USD\s*|NT\$|TWD\s*|€|EUR\s*|£|GBP\s*|\$)\s?"
    r"[0-9][0-9,]*(?:\.[0-9]+)?(?:\s*(?:/|per\s+)?(?:user|seat|month|mo|year|yr|delivery|project|hour|hr))?",
    re.IGNORECASE,
)

_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{2,}|[\u4e00-\u9fff]{2,}")
_STOP = {
    "with", "from", "this", "that", "have", "their", "they", "them", "into", "using", "used", "level",
    "general", "purpose", "compared", "workflow", "workflows", "software", "system", "tool", "tools",
    "product", "products", "service", "services", "about", "what", "when", "where", "which", "than",
}

_SEGMENTS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("AI_HEAVY_AGENCIES", ("agency", "agencies", "client delivery", "client handoff", "outsourcing", "software house"), "AI / 軟體代理商"),
    ("STARTUP_TECH_LEADERS", ("startup", "cto", "technical founder", "founder", "engineering lead"), "新創 CTO / 技術負責人"),
    ("ENGINEERING_TEAMS", ("engineering team", "developer team", "software team", "dev team", "engineering manager"), "軟體工程團隊"),
    ("ENTERPRISE_TECH", ("enterprise", "large company", "security team", "platform team", "procurement"), "企業技術團隊"),
    ("SOLO_BUILDERS", ("solo", "indie", "independent developer", "single developer", "solopreneur"), "Solo / 獨立開發者"),
    ("OUTSOURCING_BUYERS", ("outsourcing buyer", "client", "buyer", "customer", "procurement"), "委外軟體買方"),
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _tokens(text: str) -> set[str]:
    return {x.lower() for x in _TERM_RE.findall(text or "") if len(x) >= 3 and x.lower() not in _STOP}


def _phrase_present(text: str, phrase: str) -> bool:
    low = (text or "").lower()
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(phrase.lower()) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, low) is not None


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(_phrase_present(text, n) for n in needles)


def _term_hits(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _phrase_present(text, term)]


def _evidence_text(row: Mapping[str, Any]) -> str:
    return " ".join(
        _clean(row.get(k)) for k in ("source_title", "excerpt", "rationale") if _clean(row.get(k))
    )


def classify_segment(*texts: str) -> tuple[str, str, list[str]]:
    hay = " ".join(_clean(t) for t in texts if _clean(t)).lower()
    matches: list[tuple[int, str, str, list[str]]] = []
    for key, terms, label in _SEGMENTS:
        hit = [t for t in terms if t in hay]
        if hit:
            matches.append((len(hit), key, label, hit))
    if not matches:
        return "PRIMARY_SEGMENT_UNKNOWN", "主要買家族群尚未被直接證明", []
    matches.sort(key=lambda x: (-x[0], x[1]))
    _, key, label, hit = matches[0]
    return key, label, hit


def classify_spend_evidence(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = _evidence_text(row)
    low = text.lower()
    amounts = list(dict.fromkeys(x.group(0).strip() for x in _AMOUNT_RE.finditer(text)))[:4]
    out: list[dict[str, Any]] = []
    for bucket in SPEND_BUCKETS:
        matched = _term_hits(low, _SPEND_PATTERNS[bucket])
        if not matched:
            continue
        if amounts or _contains_any(low, ("we pay", "pay for", "paid for", "cost", "subscription", "license", "contract")):
            grade = "OBSERVED"
        elif bucket in {"LABOR_SPEND", "REWORK_COST"} and _contains_any(low, ("hours", "manual", "manually", "rework", "redo")):
            grade = "OBSERVED"
        else:
            grade = "INFERRED"
        out.append({
            "bucket": bucket,
            "evidence_grade": grade,
            "amount_mentions": amounts,
            "matched_terms": matched[:6],
        })
    return out


def detect_paid_dissatisfaction(row: Mapping[str, Any]) -> dict[str, Any] | None:
    text = _evidence_text(row)
    low = text.lower()
    amount_mentions = list(dict.fromkeys(x.group(0).strip() for x in _AMOUNT_RE.finditer(text)))[:4]
    paid = _term_hits(low, _PAID_TERMS)
    if amount_mentions:
        paid.append("currency_amount")
    paid = list(dict.fromkeys(paid))
    dissatisfied = _term_hits(low, _DISSATISFACTION_TERMS)
    if not paid or not dissatisfied:
        return None
    return {
        "paid_cues": paid[:5],
        "dissatisfaction_cues": dissatisfied[:5],
        "amount_mentions": amount_mentions,
    }


def _state_rank(state: str) -> int:
    return {"REFUTED": 0, "UNKNOWN": 1, "INSUFFICIENT": 2, "PARTIAL": 2, "SUPPORTED": 3}.get(_upper(state), 1)


def _claim_state(claim_states: Mapping[str, Any], code: str) -> str:
    return _upper(claim_states.get(code)) or "UNKNOWN"


def build_revenue_wedge_projection(
    *,
    claim_states: Mapping[str, Any],
    founder_addressability: Mapping[str, Any],
    spend_items: Sequence[Mapping[str, Any]],
    paid_dissatisfaction: Sequence[Mapping[str, Any]],
    current_solutions: Sequence[str],
) -> dict[str, Any]:
    addr_dims = founder_addressability.get("dimensions") if isinstance(founder_addressability.get("dimensions"), Mapping) else {}
    right = _upper(((addr_dims.get("right_to_win") or {}).get("state") if isinstance(addr_dims.get("right_to_win"), Mapping) else None)) or "UNKNOWN"
    buyer_access = _upper(((addr_dims.get("buyer_access") or {}).get("state") if isinstance(addr_dims.get("buyer_access"), Mapping) else None)) or "UNKNOWN"
    hard_blocked = bool(founder_addressability.get("hard_blocked"))
    trust = _upper(founder_addressability.get("trust_burden")) or "UNKNOWN"

    spend_observed = sum(1 for x in spend_items if _upper(x.get("evidence_grade")) == "OBSERVED")
    spend_groups = len({str(x.get("source_family_key") or x.get("source_url") or x.get("source_title") or "") for x in spend_items if str(x.get("source_family_key") or x.get("source_url") or x.get("source_title") or "")})
    if spend_observed >= 2 and spend_groups >= 2:
        spend_state = "STRONG"
    elif spend_observed >= 1:
        spend_state = "PARTIAL"
    else:
        spend_state = "UNKNOWN"

    pain = _claim_state(claim_states, "C03")
    buyer = _claim_state(claim_states, "C05")
    gap = _claim_state(claim_states, "C07")
    buildability = _claim_state(claim_states, "C09")
    competition = _claim_state(claim_states, "C13")

    if hard_blocked or right == "REFUTED" or any(x == "REFUTED" for x in (pain, buyer, gap, buildability)):
        decision = "KILL"
        rationale = "目前存在硬性反證或 Eason right-to-win 被否定，不應繼續追第一筆收入。"
    elif (
        spend_state == "STRONG"
        and pain == "SUPPORTED"
        and buyer == "SUPPORTED"
        and gap == "SUPPORTED"
        and buildability == "SUPPORTED"
        and buyer_access in {"SUPPORTED", "PARTIAL"}
        and trust != "HIGH"
    ):
        decision = "TRY_NOW"
        rationale = "既存支出、痛點、買家、未解缺口與執行能力同時有支持，且買家可達性沒有硬阻塞。"
    elif (
        spend_state in {"STRONG", "PARTIAL"}
        or len(paid_dissatisfaction) > 0
        or sum(_state_rank(x) >= 2 for x in (pain, buyer, gap)) >= 2
    ) and right != "REFUTED":
        decision = "INVESTIGATE"
        rationale = "已出現可追的金流／付費後不滿或多個商業訊號，但還不足以直接下注。"
    else:
        decision = "NOT_NOW"
        rationale = "目前連可截取的既存支出或足夠買家／缺口證據都還沒建立。"

    if buyer_access == "SUPPORTED":
        reachability = "REACHABLE"
    elif buyer_access == "PARTIAL":
        reachability = "BRIDGEABLE"
    elif buyer_access == "REFUTED":
        reachability = "NO"
    else:
        reachability = "UNKNOWN"

    return {
        "decision": decision,
        "existing_spend": spend_state,
        "pain": pain,
        "buyer_reality": buyer,
        "unresolved_gap": gap,
        "buyer_reachability": reachability,
        "mvp_buildability": buildability,
        "trust_required": trust,
        "competition_evidence": competition,
        "paid_dissatisfaction_count": len(paid_dissatisfaction),
        "current_solution_count": len(current_solutions),
        "rationale": rationale,
        "score": None,
        "truth_boundary": "QUALITATIVE_FOUNDER_RANKING_ONLY_NO_OPPORTUNITY_SCORE_AND_NO_MARKET_TRUTH_WRITE",
    }


def build_founder_playbook(*, segment_key: str, segment_label: str, problem: str, cheapest_test: Mapping[str, Any], evidence_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Planning-only execution help. It never claims a channel is proven reachable."""
    if _upper(segment_key) in {"", "PRIMARY_SEGMENT_UNKNOWN", "UNKNOWN"} or _upper(segment_label) == "UNKNOWN":
        return _discovery_playbook(playbook_type="BUYER_DISCOVERY", problem=problem, source_fit={}, buyer_label=None)
    source_types = {_upper(x.get("source_type")) for x in evidence_rows if _upper(x.get("source_type"))}
    if segment_key == "AI_HEAVY_AGENCIES":
        channels = [
            "LinkedIn：找 Founder / Agency Owner / Delivery Lead",
            "Clutch / agency directory：先列公司，再找 founder/owner 聯絡方式",
            "Upwork agency profiles：找有 AI / software delivery 記錄的 agency",
            "GitHub / Hacker News：只用來找具名團隊，再轉到可直接聯絡的人",
        ]
    elif segment_key == "STARTUP_TECH_LEADERS":
        channels = [
            "LinkedIn：CTO / Technical Founder / VP Engineering",
            "YC / startup directories：列公司後找技術負責人",
            "Hacker News / GitHub：找正在公開討論同類 workflow 的團隊",
        ]
    elif segment_key == "ENGINEERING_TEAMS":
        channels = [
            "LinkedIn：Engineering Manager / QA Lead / Platform Lead",
            "公司 career page / job listing：用正在招 QA / review / delivery roles 的公司當具名名單",
            "GitHub org / issues：找公開暴露相同 workflow 的團隊，再找決策者",
        ]
    elif segment_key == "SOLO_BUILDERS":
        channels = [
            "Indie Hackers / Hacker News Show HN",
            "GitHub 專案維護者",
            "Reddit / Discord 的 builder communities（先找具名對象，不把留言當 buyer proof）",
        ]
    elif segment_key == "ENTERPRISE_TECH":
        channels = [
            "LinkedIn：Platform / Engineering / QA / Security leader",
            "現有工作關係或 partner introduction（企業 cold outbound 的 trust 成本高）",
            "公開 job listing / vendor stack 當 target list，不把它當可達性證明",
        ]
    else:
        channels = [
            "LinkedIn：先找最接近問題 owner 的職稱",
            "現有 evidence 裡出現的具名公司／組織",
            "公開社群只用來找具名對象，再轉成一對一接觸",
        ]

    # Surface sources already present in evidence as optional starting hints.
    observed_hints: list[str] = []
    if any("REDDIT" in x for x in source_types): observed_hints.append("現有 evidence 有 Reddit 訊號")
    if any("HACKER" in x or x == "HN" for x in source_types): observed_hints.append("現有 evidence 有 Hacker News 訊號")
    if any("GITHUB" in x for x in source_types): observed_hints.append("現有 evidence 有 GitHub 訊號")
    if any("STACK" in x for x in source_types): observed_hints.append("現有 evidence 有 Stack Overflow 訊號")
    if any("JOB" in x or "REMOTIVE" in x or "ARBEIT" in x for x in source_types): observed_hints.append("現有 evidence 有 hiring / job 訊號")

    problem_short = _clean(problem)[:240] or "這個 workflow / 成本問題"
    outreach = (
        f"嗨，我在研究「{problem_short}」。不是先推產品，我想先確認這是不是你們真的在付成本的問題。"
        "方便問你最近一次遇到它時，現在怎麼處理、花了哪些工具費／人力／返工成本嗎？10 分鐘就好。"
    )
    questions = [
        "最近一次這個問題發生是什麼時候？請講實際案例，不問感覺。",
        "你們現在怎麼處理？用了哪些工具、誰要花時間？",
        "目前已經為這件事付哪些錢：軟體費、人力、外包、返工、延誤？",
        "即使已經付了這些成本，哪一段還是得人工做／仍會失敗？",
        "如果有人只把這個未解段落處理掉，你會從哪一筆現有預算付？什麼條件下會真的付？",
    ]
    offer = (
        "只有在前面已確認 current spend + unresolved gap 後才提："
        "用最小可交付版本處理那一個未解段落，直接報一個小額付費 pilot／per-delivery 價格；不要先問『你喜不喜歡這 idea』。"
    )
    return {
        "playbook_status": "READY",
        "playbook_type": "PAID_VALIDATION" if any(x in _upper(cheapest_test.get("action_type")) for x in ("WTP", "PRICE", "PAY", "PAID", "PILOT", "PREORDER")) else "PAIN_DISCOVERY",
        "target_person": segment_label,
        "channels": channels,
        "where_to_find": channels,
        "observed_source_hints": observed_hints,
        "outreach_message": outreach,
        "opening_message": outreach,
        "questions": questions,
        "offer_rule": offer,
        "when_to_ask_for_payment": offer,
        "sample_target": int(cheapest_test.get("sample_target") or 10),
        "target_count": int(cheapest_test.get("sample_target") or 10),
        "success_signal": cheapest_test.get("success_signal"),
        "failure_signal": cheapest_test.get("failure_signal"),
        "truth_boundary": "FOUNDER_PLAYBOOK_IS_PLANNING_ONLY;_CHANNEL_SUGGESTIONS_ARE_NOT_BUYER_ACCESS_PROOF",
    }


def _discovery_playbook(*, playbook_type: str, problem: str, source_fit: Mapping[str, Any], buyer_label: str | None = None) -> dict[str, Any]:
    problem_short = _clean(problem)[:240] or "這個 workflow / 成本問題"
    recommended = list(source_fit.get("recommended_source_families") or [])
    source_profile = _upper(source_fit.get("source_profile")) or "UNCLASSIFIED"
    if playbook_type == "BUYER_DISCOVERY":
        where = recommended or ["與這個 workflow 直接相關的公司／組織頁", "能指出問題 owner 的既有接觸對象"]
        opening = f"嗨，我在研究「{problem_short}」。我還沒有假設誰是買家，想先確認這件事在你們組織裡通常由哪個角色負責，能否指給我最接近的人？"
        questions = [
            "這個問題發生時，誰最先被影響？",
            "誰負責目前的 workaround 或處理流程？",
            "誰可以決定買工具、外包或投入額外人力？",
            "最近一次發生時，哪些角色真的參與了決策？",
            "如果我要找下一個同類型組織，應該找哪個職稱／部門？",
        ]
        payment = None
    elif playbook_type == "SPEND_DISCOVERY":
        where = recommended or ["現有問題 owner", "財務／採購／工具 owner"]
        opening = f"我在研究「{problem_short}」目前實際花掉哪些錢與人力，不是先推產品。可以帶我看最近一次實際處理嗎？"
        questions = [
            "最近一次發生時用了哪些工具或外包？",
            "哪些人花了多少時間？",
            "有沒有返工、延誤或錯誤成本？",
            "這筆成本現在從哪個預算／部門出？",
            "哪一段即使付錢後仍然要人工處理？",
        ]
        payment = None
    elif playbook_type == "REACHABILITY_DISCOVERY":
        who = buyer_label if buyer_label and _upper(buyer_label) != "UNKNOWN" else "目前假設的 buyer segment"
        where = recommended or ["LinkedIn / directory 的具名組織與角色", "既有 referral / partner path"]
        opening = f"我正在驗證是否能穩定接觸到「{who}」。先不推產品，只確認這個角色是否真的負責「{problem_short}」。"
        questions = [
            "你是否直接負責這個 workflow？",
            "如果不是，誰才是最接近的 owner？",
            "這類問題通常透過哪個管道被提出？",
            "誰會參與工具／服務採購？",
            "我還應該找哪一個同類角色？",
        ]
        payment = None
    else:  # PAIN_DISCOVERY
        where = recommended or ["與這個 problem class 最接近的使用者／operator 社群", "具名公司中的 workflow owner"]
        opening = f"我在研究「{problem_short}」是不是反覆發生的真問題。不是問你喜不喜歡 idea，只想聽最近一次實際發生的情況。"
        questions = [
            "最近一次發生是什麼時候？",
            "當時你具體怎麼處理？",
            "這件事多久會再發生一次？",
            "如果不處理，會造成什麼實際成本或風險？",
            "你現在用什麼 workaround？",
        ]
        payment = None
    return {
        "playbook_status": "READY",
        "playbook_type": playbook_type,
        "target_segment": buyer_label if buyer_label and _upper(buyer_label) != "UNKNOWN" else None,
        "target_count": 10,
        "where_to_find": where,
        "channels": where,
        "opening_message": opening,
        "outreach_message": opening,
        "questions": questions,
        "when_to_ask_for_payment": payment,
        "source_profile": source_profile,
        "truth_boundary": "DISCOVERY_PLAYBOOK_RESOLVES_A_FOUNDER_UNKNOWN;_IT_DOES_NOT_ASSERT_BUYER_IDENTITY_REACHABILITY_WTP_OR_MARKET_TRUTH",
    }


def route_founder_playbook(*, published_money_trail: Mapping[str, Any], decision_frontier: Mapping[str, Any], source_fit: Mapping[str, Any]) -> dict[str, Any]:
    """Return Founder execution guidance only when prerequisites are satisfied.

    This gate is intentionally stricter than the underlying template builders.
    A template existing is never enough to create a Founder Playbook.
    """
    disposition = _upper(decision_frontier.get("founder_hypothesis_disposition"))
    source_fit_state = _upper(source_fit.get("source_fit_state"))
    buyer = published_money_trail.get("buyer_segment") if isinstance(published_money_trail.get("buyer_segment"), Mapping) else {}
    buyer_label = _clean(buyer.get("label") or buyer.get("segment") or buyer.get("buyer") or "UNKNOWN")
    buyer_state = _upper(buyer.get("state")) or "UNKNOWN"
    buyer_unknown = _upper(buyer_label) in {"", "UNKNOWN", "PRIMARY_SEGMENT_UNKNOWN"} or buyer_state == "UNKNOWN"
    wedge = published_money_trail.get("revenue_wedge") if isinstance(published_money_trail.get("revenue_wedge"), Mapping) else {}
    reach = _upper(wedge.get("buyer_reachability")) or "UNKNOWN"
    frontier_exists = bool(_clean(decision_frontier.get("question") or decision_frontier.get("decision_frontier")))

    empty = {
        "target_count": None,
        "target_segment": None,
        "where_to_find": [],
        "channels": [],
        "opening_message": None,
        "outreach_message": None,
        "questions": [],
        "when_to_ask_for_payment": None,
    }

    if disposition in {"PARK", "PARK_FOUNDER_HYPOTHESIS"}:
        return {
            "playbook_status": "NOT_APPLICABLE", "playbook_type": None, **empty,
            "blocked_by": ["HYPOTHESIS_PARKED"],
            "next_unlock": "Reopen only after a decision-changing trigger or new evidence.",
            "truth_boundary": "PARKED_HYPOTHESIS_HAS_NO_ACTIVE_FOUNDER_PLAYBOOK_UNTIL_EXPLICIT_REOPEN",
        }

    blocked_by: list[str] = []
    if source_fit_state != "SUFFICIENT":
        blocked_by.append("SOURCE_FIT_INSUFFICIENT")
    if disposition in {"WAIT_FOR_SOURCE_FIT", "SOURCE_FIT_INSUFFICIENT"} and "SOURCE_FIT_INSUFFICIENT" not in blocked_by:
        blocked_by.append("SOURCE_FIT_INSUFFICIENT")
    if buyer_unknown:
        blocked_by.append("BUYER_UNKNOWN")
    if reach in {"", "UNKNOWN", "UNVALIDATED", "NOT_ESTABLISHED"}:
        blocked_by.append("REACHABILITY_UNKNOWN")
    if not frontier_exists:
        blocked_by.append("DECISION_FRONTIER_MISSING")

    if blocked_by:
        next_unlock = "Establish an evidence-backed buyer segment and source-fit coverage first."
        if blocked_by == ["REACHABILITY_UNKNOWN"]:
            next_unlock = "Establish a concrete, evidence-backed path to reach the buyer segment first."
        return {
            "playbook_status": "BLOCKED", "playbook_type": None, **empty,
            "blocked_by": blocked_by,
            "next_unlock": next_unlock,
            "truth_boundary": "BLOCKED_PLAYBOOK_CREATES_NO_BUYER_IDENTITY_REACHABILITY_WTP_OR_MARKET_TRUTH",
        }

    # Prerequisites are satisfied. Route from the Decision Frontier rather than
    # exposing a blank template. Reuse the complete Money-Trail playbook when it
    # already exists; otherwise produce a complete deterministic discovery plan.
    unknown = decision_frontier.get("decision_unknown") if isinstance(decision_frontier.get("decision_unknown"), Mapping) else {}
    ukey = _upper(unknown.get("unknown_key"))
    existing = published_money_trail.get("founder_playbook") if isinstance(published_money_trail.get("founder_playbook"), Mapping) else {}
    has_complete_existing = bool(existing.get("channels") and existing.get("questions") and existing.get("outreach_message"))

    if ukey == "WILLINGNESS_TO_PAY" or _upper(decision_frontier.get("next_mode")) == "MARKET_ACTION":
        if not has_complete_existing:
            return {
                "playbook_status": "BLOCKED", "playbook_type": None, **empty,
                "blocked_by": ["PLAYBOOK_TEMPLATE_INCOMPLETE"],
                "next_unlock": "Build a complete paid-validation playbook from the validated buyer/reachability context first.",
                "truth_boundary": "NO_PARTIAL_FOUNDER_PLAYBOOK_OUTPUT",
            }
        return {
            **dict(existing),
            "playbook_status": "READY",
            "playbook_type": "PAID_VALIDATION",
            "target_segment": buyer_label,
            "target_count": int(existing.get("sample_target") or existing.get("target_count") or 10),
            "where_to_find": list(existing.get("channels") or []),
            "opening_message": existing.get("outreach_message"),
            "when_to_ask_for_payment": existing.get("offer_rule") or existing.get("when_to_ask_for_payment"),
            "blocked_by": [],
            "truth_boundary": "FOUNDER_PLAYBOOK_IS_EXECUTION_GUIDANCE_ONLY;_IT_CANNOT_CREATE_MARKET_TRUTH_OR_WTP",
        }

    playbook_type = "PAIN_DISCOVERY"
    if ukey == "CURRENT_SPEND":
        playbook_type = "SPEND_DISCOVERY"
    pb = _discovery_playbook(playbook_type=playbook_type, problem=_clean(published_money_trail.get("problem") or published_money_trail.get("title") or ""), source_fit=source_fit, buyer_label=buyer_label)
    pb["blocked_by"] = []
    pb["target_segment"] = buyer_label
    return pb


def build_cheapest_test(
    *,
    revenue_wedge: Mapping[str, Any],
    action: Mapping[str, Any] | None,
    segment_label: str,
) -> dict[str, Any]:
    action = dict(action or {})
    template = action.get("template") if isinstance(action.get("template"), Mapping) else {}
    sample = int(template.get("default_sample") or 10)
    action_type = _upper(action.get("action_type"))
    if action_type:
        if "BUYER" in action_type and "CHANNEL" in action_type:
            instruction = f"列出並實際探測 {sample} 個你能接觸到的 {segment_label}／買家管道。"
        elif any(x in action_type for x in ("WTP", "PRICE", "PAY")):
            instruction = f"對 {sample} 個真實 {segment_label} 提出明確價格／付費 offer，看實際承諾行為。"
        elif "INTERVIEW" in action_type:
            instruction = f"訪談 {sample} 個真正承受問題的 {segment_label}，只問最近一次 workflow、現有支出與替代方案。"
        else:
            instruction = f"對 {sample} 個 {segment_label} 完成一次限定樣本的真人市場測試。"
        return {
            "action_type": action_type,
            "sample_target": sample,
            "instruction": instruction,
            "success_signal": _clean(template.get("success_signal")) or "取得至少一個會改變是否值得做的真實 buyer 行為訊號。",
            "failure_signal": _clean(template.get("failure_signal")) or "限定樣本後仍沒有 material current cost、buyer access 或付費訊號。",
            "cost_class": _upper(template.get("cost_class")) or "LOW",
            "source": "CURRENT_FOUNDER_ACTION_QUEUE",
        }

    spend = _upper(revenue_wedge.get("existing_spend"))
    reach = _upper(revenue_wedge.get("buyer_reachability"))
    if reach in {"UNKNOWN", "NO"}:
        return {
            "action_type": "IDENTIFY_REACHABLE_BUYER_CHANNEL",
            "sample_target": 10,
            "instruction": f"先找 10 個你實際能接觸的 {segment_label}，不要先做產品。",
            "success_signal": "至少找到 1 個可重複觸及合格買家的管道，並能列出具名對象。",
            "failure_signal": "限定探測後仍找不到可觸及的合格買家管道。",
            "cost_class": "LOW",
            "source": "DERIVED_MONEY_TRAIL_TEST_PLAN",
        }
    if spend == "UNKNOWN":
        return {
            "action_type": "CURRENT_SPEND_INTERVIEW",
            "sample_target": 10,
            "instruction": f"訪談 10 個 {segment_label}，只重建最近一次問題發生時實際花掉的軟體費、工時、外包與返工成本。",
            "success_signal": "至少 2/10 能指出具體且 material 的現有支出／成本。",
            "failure_signal": "少於 2/10 有 material current spend，先停止這個 revenue wedge。",
            "cost_class": "LOW",
            "source": "DERIVED_MONEY_TRAIL_TEST_PLAN",
        }
    return {
        "action_type": "BOUNDED_PAID_OFFER",
        "sample_target": 10,
        "instruction": f"對 10 個 {segment_label} 提一個非常窄的付費 offer，直接測是否願意把現有支出的一小部分轉給我們。",
        "success_signal": "至少 2/10 願意進一步談付費，且至少 1 個出現實際金額／付費承諾。",
        "failure_signal": "少於 2/10 願意考慮付費，或目前成本不 material，就停掉／換 segment。",
        "cost_class": "LOW",
        "source": "DERIVED_MONEY_TRAIL_TEST_PLAN",
    }


def _evidence_ref(row: Mapping[str, Any], *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "claim_code": row.get("claim_code"),
        "claim_state": row.get("claim_state"),
        "stance": row.get("stance"),
        "source_type": row.get("source_type"),
        "source_title": row.get("source_title"),
        "excerpt": _clean(row.get("excerpt"))[:700],
        "source_url": row.get("source_url"),
        "source_family_key": row.get("source_family_key"),
        "authority_class": row.get("authority_class"),
        "directness": row.get("directness"),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def build_money_trail_from_rows(
    *,
    thesis: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
    market_action: Mapping[str, Any] | None = None,
    source_label: str = "BRAIN_THESIS",
) -> dict[str, Any]:
    claim_states = dict(thesis.get("claim_states") or {})
    if not claim_states:
        for row in evidence_rows:
            code = _upper(row.get("claim_code"))
            state = _upper(row.get("claim_state"))
            if code and state:
                claim_states[code] = state

    actor_text = " ".join(
        _clean(x.get(k)) for x in candidate_rows for k in ("actor", "actor_category", "buyer_context", "title", "problem_statement") if _clean(x.get(k))
    )
    evidence_text = " ".join(_evidence_text(x) for x in evidence_rows[:80])
    segment_key, segment_label, segment_cues = classify_segment(actor_text, evidence_text)

    spend: list[dict[str, Any]] = []
    paid_dissat: list[dict[str, Any]] = []
    solution_names: list[str] = []
    solution_seen: set[str] = set()
    recipients: list[dict[str, Any]] = []
    recipient_seen: set[str] = set()

    for row in evidence_rows:
        for classified in classify_spend_evidence(row):
            spend.append(_evidence_ref(row, extra=classified))
        pd = detect_paid_dissatisfaction(row)
        if pd:
            paid_dissat.append(_evidence_ref(row, extra=pd))

        if _upper(row.get("claim_code")) == "C06" and _upper(row.get("stance")) == "SUPPORT":
            md = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), Mapping) else {}
            for key in ("solution_identity", "solution", "product", "tool", "competitor", "alternative"):
                name = _clean(md.get(key))
                if name and name.lower() not in solution_seen:
                    solution_seen.add(name.lower())
                    solution_names.append(name)
                    if name.lower() not in recipient_seen:
                        recipient_seen.add(name.lower())
                        recipients.append({"recipient": name, "type": "VENDOR_OR_EXISTING_SOLUTION", "basis": "VALIDATED_C06_METADATA"})
                    break

    # Keep one representation of the same evidence/bucket pair.
    dedup_spend: list[dict[str, Any]] = []
    seen_spend: set[tuple[str, str, str]] = set()
    for item in spend:
        key = (
            str(item.get("bucket")),
            str(item.get("source_family_key") or ""),
            str(item.get("excerpt") or "")[:180],
        )
        if key in seen_spend:
            continue
        seen_spend.add(key)
        dedup_spend.append(item)
    spend = dedup_spend[:24]

    dedup_pd: list[dict[str, Any]] = []
    seen_pd: set[tuple[str, str]] = set()
    for item in paid_dissat:
        key = (str(item.get("source_family_key") or ""), str(item.get("excerpt") or "")[:220])
        if key in seen_pd:
            continue
        seen_pd.add(key)
        dedup_pd.append(item)
    paid_dissat = dedup_pd[:12]

    founder_addressability = thesis.get("founder_addressability") if isinstance(thesis.get("founder_addressability"), Mapping) else {}
    wedge = build_revenue_wedge_projection(
        claim_states=claim_states,
        founder_addressability=founder_addressability,
        spend_items=spend,
        paid_dissatisfaction=paid_dissat,
        current_solutions=solution_names,
    )
    test = build_cheapest_test(revenue_wedge=wedge, action=market_action, segment_label=segment_label)
    playbook = build_founder_playbook(
        segment_key=segment_key,
        segment_label=segment_label,
        problem=_clean(thesis.get("representative_problem") or thesis.get("representative_title") or ""),
        cheapest_test=test,
        evidence_rows=evidence_rows,
    )

    # A cash-flow recipient is only asserted when evidence identifies one.
    if any(x.get("bucket") == "LABOR_SPEND" for x in spend):
        recipients.append({"recipient": "內部工程／QA 人力", "type": "INTERNAL_LABOR", "basis": "VALIDATED_EVIDENCE_MENTIONS_LABOR_OR_MANUAL_WORK"})
    if any(x.get("bucket") == "CONTRACTOR_SPEND" for x in spend):
        recipients.append({"recipient": "外包／顧問／測試供應商", "type": "EXTERNAL_SERVICES", "basis": "VALIDATED_EVIDENCE_MENTIONS_CONTRACTOR_OR_EXTERNAL_SERVICE"})

    strongest_spend = next((x for x in spend if _upper(x.get("evidence_grade")) == "OBSERVED"), spend[0] if spend else None)
    if strongest_spend:
        capture = {
            "status": "HYPOTHESIS",
            "statement": f"可能的切入點：降低或取代 {strongest_spend.get('bucket')} 中目前仍由現有方案／人工承擔的成本。",
            "basis": [strongest_spend],
            "truth_boundary": "POSSIBLE_WEDGE_IS_DERIVED_HYPOTHESIS_NOT_PROOF_OF_DEMAND",
        }
    else:
        capture = {
            "status": "UNKNOWN",
            "statement": "目前還找不到一筆有證據支持、可被 Eason 截取的既存支出。先不要做產品。",
            "basis": [],
            "truth_boundary": "NO_SPEND_EVIDENCE_MEANS_NO_MONEY_CAPTURE_CLAIM",
        }

    title = _clean(thesis.get("representative_title") or thesis.get("representative_problem") or thesis.get("thesis_id"))
    return {
        "engine_version": ENGINE_VERSION,
        "thesis_id": thesis.get("thesis_id"),
        "source": source_label,
        "title": title,
        "problem": _clean(thesis.get("representative_problem") or title),
        "strategic_track": thesis.get("strategic_track"),
        "zip2_readiness": thesis.get("zip2_readiness"),
        "buyer_segment": {
            "key": segment_key,
            "label": segment_label,
            "evidence_cues": segment_cues,
            "state": "SUPPORTED_OR_DERIVED_FROM_PUBLISHED_CONTEXT" if segment_cues else "UNKNOWN",
        },
        "claim_states": claim_states,
        "current_spend": {
            "status": wedge.get("existing_spend"),
            "buckets": {
                bucket: [x for x in spend if x.get("bucket") == bucket][:6]
                for bucket in SPEND_BUCKETS
            },
            "evidence_count": len(spend),
            "numeric_estimate_created": False,
            "truth_boundary": "NO_NUMERIC_SPEND_ESTIMATE_WITHOUT_DIRECT_AMOUNT_EVIDENCE",
        },
        "money_recipients_today": recipients[:12],
        "current_solutions": solution_names[:20],
        "paid_dissatisfaction": {
            "status": "FOUND" if paid_dissat else "NOT_FOUND_IN_CURRENT_PUBLISHED_EVIDENCE",
            "items": paid_dissat,
            "count": len(paid_dissat),
            "truth_boundary": "PAID_DISSATISFACTION_IS_HIGH_VALUE_INVESTIGATION_SIGNAL_NOT_AUTOMATIC_MARKET_PROOF",
        },
        "possible_revenue_wedge": capture,
        "revenue_wedge": wedge,
        "cheapest_test": test,
        "founder_playbook": playbook,
        "founder_addressability": dict(founder_addressability),
        "member_candidate_ids": list(thesis.get("member_candidate_ids") or []),
        "published_evidence_count": len(evidence_rows),
        "truth_boundary": TRUTH_BOUNDARY,
    }


def assess_founder_published_binding(query: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed compatibility gate before reusing Published evidence.

    A lexical nearest-neighbor is not enough.  Reuse requires compatible problem
    semantics plus workflow/actor/economic-job support.  The result is a routing
    decision only; it never promotes or mutates Published truth.
    """
    q = semantic_profile(query)
    problem_text = " ".join(_clean(candidate.get(k)) for k in ("title","problem_statement","failure_mode","consequence") if _clean(candidate.get(k)))
    workflow_text = " ".join(_clean(candidate.get(k)) for k in ("title","problem_statement","task","object","workaround") if _clean(candidate.get(k)))
    actor_text = " ".join(_clean(candidate.get(k)) for k in ("actor","actor_category","buyer_context") if _clean(candidate.get(k)))
    economic_text = " ".join(_clean(candidate.get(k)) for k in ("buyer_context","consequence","workaround","task") if _clean(candidate.get(k)))
    pp, wp, ap, ep = (semantic_profile(problem_text), semantic_profile(workflow_text), semantic_profile(actor_text), semantic_profile(economic_text))

    q_terms = set(q.get("terms") or [])
    problem_terms = set(pp.get("terms") or [])
    workflow_terms = set(wp.get("terms") or [])
    actor_terms = set(ap.get("terms") or [])
    economic_terms = set(ep.get("terms") or [])
    q_domains = set(q.get("domains") or [])
    p_domains = set(pp.get("domains") or [])
    q_workflows = set(q.get("workflows") or [])
    p_workflows = set(wp.get("workflows") or [])
    q_actors = set(q.get("actors") or [])
    p_actors = set(ap.get("actors") or [])

    problem_shared = sorted(q_terms & problem_terms)
    workflow_shared = sorted(q_terms & workflow_terms)
    actor_shared = sorted(q_terms & actor_terms)
    economic_shared = sorted(q_terms & economic_terms)
    domain_overlap = sorted(q_domains & p_domains)
    workflow_overlap = sorted(q_workflows & p_workflows)
    actor_overlap = sorted(q_actors & p_actors)

    domain_conflict = bool(q_domains and p_domains and not domain_overlap)
    workflow_conflict = bool(q_workflows and p_workflows and not workflow_overlap)
    actor_conflict = bool(q_actors and p_actors and not actor_overlap)

    problem_score = 0.0
    if domain_overlap:
        problem_score += 0.55
    if len(problem_shared) >= 2:
        problem_score += 0.35
    elif len(problem_shared) == 1:
        problem_score += 0.15
    problem_score = min(problem_score, 1.0)

    workflow_score = min(1.0, (0.7 if workflow_overlap else 0.0) + (0.3 if len(workflow_shared) >= 2 else 0.15 if workflow_shared else 0.0))
    actor_score = min(1.0, (0.75 if actor_overlap else 0.0) + (0.25 if actor_shared else 0.0))
    economic_score = min(1.0, 0.25 * min(len(economic_shared), 4))

    # Missing actor/economic fields are not positive evidence.  Fail closed rather
    # than allowing generic tokens such as team/manual/workflow to carry a match.
    overall = round(0.45 * problem_score + 0.25 * workflow_score + 0.20 * actor_score + 0.10 * economic_score, 4)
    hard_conflicts = []
    if domain_conflict:
        hard_conflicts.append("PROBLEM_DOMAIN_CONFLICT")
    if workflow_conflict and q_workflows:
        hard_conflicts.append("WORKFLOW_CONFLICT")
    if actor_conflict and q_actors:
        hard_conflicts.append("ACTOR_BUYER_CONFLICT")

    compatible_secondary = workflow_score >= 0.55 or actor_score >= 0.55 or economic_score >= 0.5
    matched = not hard_conflicts and problem_score >= 0.55 and compatible_secondary and overall >= 0.5
    return {
        "status": "MATCHED" if matched else "REJECTED",
        "confidence": overall,
        "threshold": 0.5,
        "problem_semantic_compatibility": round(problem_score, 3),
        "workflow_compatibility": round(workflow_score, 3),
        "actor_buyer_compatibility": round(actor_score, 3),
        "economic_job_compatibility": round(economic_score, 3),
        "domain_overlap": domain_overlap,
        "workflow_overlap": workflow_overlap,
        "actor_overlap": actor_overlap,
        "shared_problem_terms": problem_shared[:12],
        "shared_workflow_terms": workflow_shared[:12],
        "shared_actor_terms": actor_shared[:10],
        "shared_economic_terms": economic_shared[:10],
        "hard_conflicts": hard_conflicts,
        "match_reason": (
            "Published evidence may be reused only because problem semantics and at least one workflow/actor/economic-job axis are compatible."
            if matched else
            "Fail closed: lexical proximity is insufficient to prove the same problem/lineage; Published evidence is not reused."
        ),
        "market_truth_writes": 0,
    }


def _unknown_direction_probe(*, query: str, title: str, binding_candidates: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "status": "NO_COMPATIBLE_PUBLISHED_THESIS",
        "query": query,
        "title": _clean(title),
        "source": "FOUNDER_READ_ONLY_DIRECTION_PROBE",
        "published_thesis_match": {
            "status": "NONE",
            "confidence": 0.0,
            "reason": "No Published candidate passed the fail-closed problem/workflow/actor/economic-job compatibility gate.",
            "candidates_considered": list(binding_candidates or [])[:8],
        },
        "matched_candidates": [],
        "buyer_segment": {"key": "PRIMARY_SEGMENT_UNKNOWN", "label": "UNKNOWN", "evidence_cues": [], "state": "UNKNOWN"},
        "current_spend": {"status": "UNKNOWN", "buckets": {b: [] for b in SPEND_BUCKETS}, "evidence_count": 0, "numeric_estimate_created": False},
        "paid_dissatisfaction": {"status": "UNKNOWN", "items": [], "count": 0, "truth_boundary": "NO_COMPATIBLE_PUBLISHED_BINDING_MEANS_NO_PAID_DISSATISFACTION_CLAIM"},
        "money_recipients_today": [],
        "current_solutions": [],
        "possible_revenue_wedge": {"status": "UNKNOWN", "statement": "No compatible Published thesis is bound to this Founder hypothesis.", "basis": []},
        "revenue_wedge": {"decision": "NOT_NOW", "existing_spend": "UNKNOWN", "buyer_reality": "UNKNOWN", "unresolved_gap": "UNKNOWN", "buyer_reachability": "UNKNOWN"},
        "founder_playbook": {"playbook_status": "ROUTE_BY_DECISION_FRONTIER", "playbook_type": None, "target_segment": None, "target_count": None, "channels": [], "where_to_find": [], "opening_message": None, "questions": [], "when_to_ask_for_payment": None, "truth_boundary": "NO_EXECUTION_TEMPLATE_IS_CREATED_UNTIL_THE_DECISION_FRONTIER_SELECTS_WHICH_UNKNOWN_TO_RESOLVE"},
        "published_evidence_count": 0,
        "next_step": "FRESH_OR_TARGETED_RESEARCH_WITHOUT_PUBLISHED_EVIDENCE_REUSE",
        "truth_boundary": "NO_COMPATIBLE_PUBLISHED_BINDING;_BUYER_SPEND_PAID_DISSATISFACTION_AND_NEXT_ACTION_REMAIN_UNKNOWN",
    }


async def _load_candidate_and_evidence(member_candidate_ids: Sequence[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ids = [int(x) for x in member_candidate_ids if int(x) > 0]
    if not ids:
        return [], []
    async with async_session() as session:
        rows = (await session.execute(
            select(ProblemCandidate, RadarCase)
            .join(RadarCase, RadarCase.candidate_id == ProblemCandidate.id)
            .where(ProblemCandidate.id.in_(ids))
        )).all()
        candidate_rows: list[dict[str, Any]] = []
        case_ids: list[int] = []
        for candidate, case in rows:
            case_ids.append(int(case.id))
            candidate_rows.append({
                "candidate_id": int(candidate.id),
                "case_id": int(case.id),
                "title": candidate.title,
                "problem_statement": candidate.problem_statement,
                "actor": candidate.actor,
                "actor_category": candidate.actor_category,
                "buyer_context": candidate.buyer_context,
                "workaround": candidate.workaround,
                "community_platform": candidate.community_platform,
                "system_verdict": case.system_verdict,
                "current_gate": case.current_gate,
            })
        if not case_ids:
            return candidate_rows, []
        ev_rows = (await session.execute(
            select(RadarClaim, RadarClaimEvidence, RadarEvidence)
            .join(RadarClaimEvidence, RadarClaimEvidence.claim_id == RadarClaim.id)
            .join(RadarEvidence, RadarEvidence.id == RadarClaimEvidence.evidence_id)
            .where(RadarClaim.case_id.in_(case_ids))
            .where(RadarClaimEvidence.validated.is_(True))
        )).all()
        evidence_rows: list[dict[str, Any]] = []
        for claim, link, ev in ev_rows:
            evidence_rows.append({
                "case_id": int(claim.case_id),
                "claim_code": str(claim.claim_code or ""),
                "claim_state": str(claim.state or "UNKNOWN"),
                "claim_statement": claim.statement,
                "stance": str(link.stance or "INSUFFICIENT"),
                "validated": bool(link.validated),
                "rationale": link.rationale,
                "source_type": str(ev.source_type or ""),
                "source_title": str(ev.source_title or ""),
                "excerpt": str(ev.excerpt or ""),
                "source_url": ev.source_url,
                "source_family_key": str(ev.source_family_key or ""),
                "directness": str(ev.directness or ""),
                "authority_class": str(ev.authority_class or ""),
                "raw_metadata": dict(ev.raw_metadata or {}),
            })
        return candidate_rows, evidence_rows


def _market_action_map(limit: int = 100) -> dict[str, dict[str, Any]]:
    try:
        from processors.signalforge_market_action_registry import build_market_action_queue
        report = build_market_action_queue(limit=limit)
    except Exception:
        return {}
    return {
        str(x.get("thesis_id")): dict(x)
        for x in (report.get("items") or [])
        if isinstance(x, Mapping) and x.get("thesis_id")
    }


async def build_money_trail_for_thesis(thesis: Mapping[str, Any]) -> dict[str, Any]:
    candidate_rows, evidence_rows = await _load_candidate_and_evidence(thesis.get("member_candidate_ids") or [])
    action = _market_action_map().get(str(thesis.get("thesis_id") or ""))
    return build_money_trail_from_rows(
        thesis=thesis,
        candidate_rows=candidate_rows,
        evidence_rows=evidence_rows,
        market_action=action,
        source_label="BRAIN_THESIS",
    )


async def build_money_trail_portfolio(limit: int = 20) -> dict[str, Any]:
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio

    portfolio = dict(get_brain_v2_portfolio())
    theses = [x for x in (portfolio.get("portfolio") or []) if isinstance(x, Mapping)]
    trails: list[dict[str, Any]] = []
    for thesis in theses[: max(0, int(limit))]:
        try:
            trails.append(await build_money_trail_for_thesis(thesis))
        except Exception as exc:
            trails.append({
                "engine_version": ENGINE_VERSION,
                "thesis_id": thesis.get("thesis_id"),
                "title": thesis.get("representative_title"),
                "status": "MONEY_TRAIL_UNAVAILABLE_NON_BLOCKING",
                "error": f"{type(exc).__name__}: {exc}",
                "truth_boundary": TRUTH_BOUNDARY,
            })

    order = {"TRY_NOW": 0, "INVESTIGATE": 1, "NOT_NOW": 2, "KILL": 3}
    trails.sort(key=lambda x: (
        order.get(_upper((x.get("revenue_wedge") or {}).get("decision")), 9),
        -int((x.get("paid_dissatisfaction") or {}).get("count") or 0),
        -int((x.get("current_spend") or {}).get("evidence_count") or 0),
        str(x.get("thesis_id") or ""),
    ))
    counts = defaultdict(int)
    for trail in trails:
        counts[_upper((trail.get("revenue_wedge") or {}).get("decision")) or "UNAVAILABLE"] += 1
    return {
        "engine_version": ENGINE_VERSION,
        "status": portfolio.get("status"),
        "count": len(trails),
        "counts": dict(counts),
        "items": trails,
        "market_calibration": portfolio.get("market_calibration") or {},
        "truth_boundary": TRUTH_BOUNDARY,
    }


async def probe_money_trail_direction(*, title: str, description: str = "", limit_candidates: int = 5) -> dict[str, Any]:
    """Read-only Founder probe over Published evidence with fail-closed binding.

    The old implementation selected nearest lexical candidates.  This closure
    refuses Published evidence reuse unless the candidate passes problem,
    workflow, actor/buyer and economic-job compatibility gates.
    """
    query = _clean(f"{title} {description}")
    q_tokens = _tokens(query)
    if not q_tokens:
        return {"engine_version": ENGINE_VERSION, "status": "INVALID_QUERY", "query": query, "truth_boundary": "READ_ONLY_PROBE_CREATES_NO_MARKET_TRUTH"}

    async with async_session() as session:
        rows = (await session.execute(select(ProblemCandidate, RadarCase).join(RadarCase, RadarCase.candidate_id == ProblemCandidate.id))).all()

    compatible: list[tuple[float, ProblemCandidate, RadarCase, dict[str, Any]]] = []
    considered: list[dict[str, Any]] = []
    for candidate, case in rows:
        candidate_map = {
            "title": candidate.title, "problem_statement": candidate.problem_statement, "actor": candidate.actor,
            "actor_category": candidate.actor_category, "buyer_context": candidate.buyer_context, "task": candidate.task,
            "object": candidate.object, "failure_mode": candidate.failure_mode, "consequence": candidate.consequence,
            "workaround": candidate.workaround,
        }
        binding = assess_founder_published_binding(query, candidate_map)
        summary = {"candidate_id": int(candidate.id), "case_id": int(case.id), "title": candidate.title, **binding}
        considered.append(summary)
        if binding.get("status") == "MATCHED":
            score = float(binding.get("confidence") or 0.0)
            if _upper(case.system_verdict) in {"INVESTIGATE", "VALIDATE"}:
                score += 0.02
            compatible.append((score, candidate, case, binding))

    compatible.sort(key=lambda x: (-x[0], int(x[1].id)))
    selected = compatible[: max(1, int(limit_candidates))]
    considered.sort(key=lambda x: (-float(x.get("confidence") or 0.0), int(x.get("candidate_id") or 0)))
    if not selected:
        return _unknown_direction_probe(query=query, title=title, binding_candidates=considered)

    member_ids = [int(candidate.id) for _, candidate, _, _ in selected]
    candidate_rows, evidence_rows = await _load_candidate_and_evidence(member_ids)
    synthetic = {
        "thesis_id": "probe:" + hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
        "representative_title": _clean(title), "representative_problem": _clean(description) or _clean(title),
        "strategic_track": "PROBE_ONLY", "zip2_readiness": "UNASSESSED", "member_candidate_ids": member_ids, "claim_states": {},
        "founder_addressability": {"first_person_addressability_state": "UNASSESSED_FOR_PROBE", "trust_burden": "UNKNOWN", "learning_distance": "UNKNOWN", "dimensions": {}, "blocking_unknowns": [], "hard_blocked": False},
    }
    result = build_money_trail_from_rows(thesis=synthetic, candidate_rows=candidate_rows, evidence_rows=evidence_rows, market_action=None, source_label="FOUNDER_READ_ONLY_DIRECTION_PROBE_COMPATIBLE_BINDING")
    top_score, _, _, top_binding = selected[0]
    result.update({
        "status": "PROBE_ONLY_COMPATIBLE_PUBLISHED_BINDING", "query": query,
        "published_thesis_match": {
            "status": "MATCHED", "confidence": round(float(top_score), 4), "reason": top_binding.get("match_reason"),
            "problem_semantic_compatibility": top_binding.get("problem_semantic_compatibility"),
            "workflow_compatibility": top_binding.get("workflow_compatibility"),
            "actor_buyer_compatibility": top_binding.get("actor_buyer_compatibility"),
            "economic_job_compatibility": top_binding.get("economic_job_compatibility"),
            "hard_conflicts": top_binding.get("hard_conflicts") or [],
        },
        "matched_candidates": [{"candidate_id": int(candidate.id), "case_id": int(case.id), "title": candidate.title, "match_score": round(score, 4), "binding": binding} for score, candidate, case, binding in selected],
        "truth_boundary": "FOUNDER_DIRECTION_PROBE_REUSES_PUBLISHED_EVIDENCE_ONLY_AFTER_FAIL_CLOSED_MULTI_AXIS_COMPATIBILITY;_NO_NEW_MARKET_TRUTH",
    })
    return result

