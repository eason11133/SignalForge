"""SignalForge Founder UX Architecture v1 — Phase 1 canonical projection layer.

This module does not create new Market Truth and does not reclassify commercial
opportunities.  It turns existing Part 1-6 canonical product state into a stable,
Founder-facing Opportunity model so frontend code can render one product model
instead of reconstructing business semantics from many backend structures.

Internal enums / API fields remain English.  Human-facing labels are natural
Chinese.  React must not own the semantics implemented here.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

ENGINE_VERSION = "signalforge-founder-ux-architecture-v1-phase1-contract-closure"
MARKET_TRUTH_WRITES = 0
TRUTH_BOUNDARY = (
    "FOUNDER_VIEW_MODELS_ARE_READ_ONLY_CANONICAL_PRODUCT_PROJECTIONS;_"
    "THEY_DO_NOT_WRITE_C01_C14,_MARKET_TRUTH,_CALIBRATION,_OR_LINEAGE"
)

OWNER_VALUES = {"SIGNALFORGE", "FOUNDER", "CHATGPT", "EASON_ONE", "MARKET_WAIT"}
SOURCE_KINDS = {"PUBLISHED_THESIS", "FOUNDER_HYPOTHESIS"}
LINEAGE_REVIEW_STATES = {"NO_MATCH", "COMPATIBLE_PUBLISHED_EVIDENCE", "POSSIBLE_MATCH_REVIEW", "CANONICAL_MATCH"}
ATTENTION_STATES = {"NONE", "NEEDS_FOUNDER_DECISION", "NEEDS_FOUNDER_INPUT", "DECISION_CHANGING_EVIDENCE", "MARKET_TEST_DUE", "OUTCOME_REVIEW_REQUIRED", "FUTURE_EASON_ONE_REVIEW_REQUIRED"}


def _clean(v: Any, limit: int = 6000) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _upper(v: Any) -> str:
    return _clean(v, 200).upper()


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


def stable_id(kind: str, canonical_id: str) -> str:
    """Stable ID derived only from an existing canonical identity, never title text."""
    k = _upper(kind).replace(" ", "_")
    cid = _clean(canonical_id, 1000)
    if not cid:
        raise ValueError("canonical_id is required for stable identity")
    prefix = {
        "OPPORTUNITY": "opp",
        "FOUNDER_HYPOTHESIS": "fh",
        "PUBLISHED_THESIS": "pth",
        "PROBLEM_LINEAGE": "pl",
        "EVIDENCE": "ev",
        "FOUNDER_MEMORY_ENTRY": "fme",
        "DECISION_ARTIFACT": "da",
        "MARKET_TEST": "mt",
        "MARKET_ACTION": "ma",
        "OUTCOME": "out",
        "CALIBRATION_UNIT": "cal",
        "EASON_ONE_WORK_CONTRACT": "eow",
        "ATTENTION_EVENT": "att",
    }.get(k, "id")
    digest = hashlib.sha256(f"{k}:{cid}".encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def opportunity_id(source_kind: str, canonical_source_id: str) -> str:
    """Source-derived opportunity id for objects not yet canonically merged.

    Source identity is not canonical opportunity identity. A Founder hypothesis
    that later receives a verified canonical Published binding must resolve to
    the Published opportunity id instead of creating a second home.
    """
    sk = _upper(source_kind)
    if sk not in SOURCE_KINDS:
        raise ValueError(f"unsupported source_kind {source_kind!r}")
    return stable_id("OPPORTUNITY", f"{sk}:{_clean(canonical_source_id, 1000)}")


def canonical_opportunity_id(*, source_kind: str, canonical_source_id: str, lineage_review: Mapping[str, Any] | None = None) -> tuple[str, str | None]:
    """Resolve one canonical Opportunity home and optional source alias.

    A Founder hypothesis is merged only when a canonical lineage binding has
    stable published_thesis_id + problem_lineage_id + canonical_binding_id.
    Compatibility-only evidence never merges identities.
    """
    source_oid = opportunity_id(source_kind, canonical_source_id)
    review = _mapping(lineage_review)
    if _upper(source_kind) == "FOUNDER_HYPOTHESIS" and review.get("state") == "CANONICAL_MATCH":
        published_thesis_id = _clean(review.get("published_thesis_id"), 1000)
        if published_thesis_id:
            target = opportunity_id("PUBLISHED_THESIS", published_thesis_id)
            return target, source_oid if target != source_oid else None
    return source_oid, None


def owner_label(owner: str) -> str:
    return {
        "SIGNALFORGE": "SignalForge 正在處理",
        "FOUNDER": "需要你決定",
        "CHATGPT": "可以跟 ChatGPT 討論",
        "EASON_ONE": "未來可交給 Eason One",
        "MARKET_WAIT": "等待市場回覆",
    }.get(_upper(owner), "尚未決定")


def _state_label(state: str) -> str:
    return {
        "SUPPORTED": "有證據",
        "KNOWN": "已確認",
        "PARTIAL": "有跡象",
        "STRONG": "有明確跡象",
        "MEDIUM": "有跡象",
        "WEAK": "證據偏弱",
        "FOUND": "有證據",
        "NOT_FOUND": "尚未找到",
        "NOT_FOUND_IN_CURRENT_PUBLISHED_EVIDENCE": "目前 Published evidence 尚未找到",
        "NO_COMPATIBLE_PUBLISHED_THESIS": "沒有可安全沿用的 Published thesis",
        "UNKNOWN": "未知",
        "UNASSESSED": "尚未評估",
        "INSUFFICIENT": "證據不足",
        "CONTRADICTED": "有反方證據",
        "REFUTED": "目前不成立",
        "COMPLETE_FOR_CONFIGURED_FAST_SOURCES": "完整",
        "PARTIAL_FOR_CONFIGURED_FAST_SOURCES": "部分",
    }.get(_upper(state), "未知")


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def _founder_copy(value: Any, fallback: str, *, exact: Mapping[str, str] | None = None) -> str:
    """Never leak internal English prose/enums into the Founder control surface."""
    text = _clean(value)
    if not text:
        return fallback
    mapping = {
        "Trust/domain/buyer access does not fit the Founder.": "目前的信任門檻、領域適配或買家接觸能力不適合你直接投入。",
        "No credible access path.": "如果找不到可信的買家接觸路徑，就先停手或改用合作方式。",
        "Can the Founder reach a trusted channel?": "你能不能透過可信管道接觸到真正的目標買家？",
    }
    mapping.update(dict(exact or {}))
    if text in mapping:
        return mapping[text]
    if _has_cjk(text):
        return text
    # Proper product names may remain English elsewhere, but decision prose must
    # be natural Chinese. Unknown backend prose fails closed to a semantic fallback.
    return fallback


def _buyer_founder_label(value: Any) -> str:
    text = _clean(value, 300)
    if not text or _upper(text) == "UNKNOWN":
        return "未知"
    if _has_cjk(text):
        return text
    known = {
        "Engineering Team": "工程團隊",
        "Enterprise Engineering Team": "企業工程團隊",
        "Healthcare operations": "醫療營運團隊",
        "Procurement": "採購團隊",
        "Purchasing": "採購團隊",
        "Sourcing": "尋源／採購團隊",
    }
    return known.get(text, "已辨識買家（查看證據）")


def build_lineage_review(binding: Mapping[str, Any] | None) -> dict[str, Any]:
    """Founder-visible lineage contract. Truth inheritance is fail-closed.

    Compatibility against Published candidate evidence is not a canonical lineage
    binding. CANONICAL_MATCH requires durable identities for the Published thesis,
    problem lineage and binding itself.
    """
    row = _mapping(binding)
    status = _upper(row.get("status"))
    confidence = float(row.get("confidence") or 0.0)
    considered = _list(row.get("candidates_considered") or row.get("matched_candidates"))
    published_thesis_id = _clean(row.get("published_thesis_id") or row.get("canonical_published_thesis_id"), 1000) or None
    problem_lineage_id = _clean(row.get("problem_lineage_id") or row.get("canonical_problem_lineage_id"), 1000) or None
    canonical_binding_id = _clean(row.get("canonical_binding_id"), 1000) or None
    canonical_identity_complete = bool(published_thesis_id and problem_lineage_id and canonical_binding_id)

    # MATCHED from Part 1 Money Trail currently means compatibility against
    # ProblemCandidate/RadarCase Published evidence. It must never silently become
    # a canonical ProblemLineage/Published Thesis binding.
    if status in {"CANONICAL_MATCH", "CANONICAL_LINEAGE_MATCH"} and canonical_identity_complete:
        review_state = "CANONICAL_MATCH"
        inheritance = "CANONICAL_BINDING_GATE_PASSED"
        allow_inheritance = True
        label = "已確認屬於同一個既有問題族群"
    elif status == "MATCHED":
        review_state = "COMPATIBLE_PUBLISHED_EVIDENCE"
        inheritance = "NO_TRUTH_INHERITANCE"
        allow_inheritance = False
        label = "找到相容的 Published evidence，但尚未確認為同一個問題族群"
    elif considered or status in {"POSSIBLE", "AMBIGUOUS", "REVIEW", "INSUFFICIENT"}:
        review_state = "POSSIBLE_MATCH_REVIEW"
        inheritance = "NO_TRUTH_INHERITANCE"
        allow_inheritance = False
        label = "可能相關，但尚未確認為同一問題"
    else:
        review_state = "NO_MATCH"
        inheritance = "NO_TRUTH_INHERITANCE"
        allow_inheritance = False
        label = "目前沒有可安全沿用的既有問題族群"

    reasons = []
    raw_reason = row.get("reason") or row.get("match_reason")
    if isinstance(raw_reason, list):
        reasons.extend(_clean(x, 500) for x in raw_reason if _clean(x, 500))
    elif _clean(raw_reason, 1000):
        reasons.append(_clean(raw_reason, 1000))
    compat = {
        "problem_semantic_compatibility": row.get("problem_semantic_compatibility"),
        "workflow_compatibility": row.get("workflow_compatibility"),
        "actor_buyer_compatibility": row.get("actor_buyer_compatibility"),
        "economic_job_compatibility": row.get("economic_job_compatibility"),
    }
    review_actions = []
    if review_state in {"COMPATIBLE_PUBLISHED_EVIDENCE", "POSSIBLE_MATCH_REVIEW"}:
        review_actions = ["CONFIRM_SAME_LINEAGE", "KEEP_SEPARATE", "COMPARE_EVIDENCE"]
    return {
        "state": review_state,
        "label": label,
        "confidence": confidence if status in {"MATCHED", "CANONICAL_MATCH", "CANONICAL_LINEAGE_MATCH"} or considered else None,
        "match_reason": reasons,
        "compatibility": compat,
        "hard_conflicts": _list(row.get("hard_conflicts")),
        "published_thesis_id": published_thesis_id,
        "problem_lineage_id": problem_lineage_id,
        "canonical_binding_id": canonical_binding_id,
        "canonical_identity_complete": canonical_identity_complete,
        "truth_inheritance": inheritance,
        "allow_truth_inheritance": allow_inheritance,
        "review_actions": review_actions,
        "market_truth_writes": 0,
    }


def _attention_contract(*, opportunity_id_value: str, call_state: str, owner: str, explicit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Canonical Founder-attention contract. Owner is not inbox membership."""
    row = _mapping(explicit)
    explicit_state = _upper(row.get("attention_state"))
    if explicit_state in ATTENTION_STATES and explicit_state != "NONE":
        state = explicit_state
        requires = bool(row.get("requires_founder_action", True))
        priority = int(row.get("attention_priority") or 50)
        reason = _founder_copy(row.get("inbox_reason"), "有新的事件需要你做決定。")
        event_id = _clean(row.get("attention_event_id"), 1000) or stable_id("ATTENTION_EVENT", f"{opportunity_id_value}:{state}:{reason}")
        return {"attention_state": state, "requires_founder_action": requires, "inbox_reason": reason, "attention_priority": priority, "attention_event_id": event_id if requires else None}

    state = _upper(call_state)
    if state == "READY_FOR_MARKET_TEST":
        att, reason, priority = "NEEDS_FOUNDER_DECISION", "這個方向已經準備好進入市場測試，需要你決定是否鎖定測試。", 100
    elif state == "EXISTING_THESIS_REVIEW":
        att, reason, priority = "NEEDS_FOUNDER_DECISION", "需要你確認這個 Founder idea 是否真的屬於既有問題族群。", 95
    elif state == "VALIDATE_DISTRIBUTION":
        att, reason, priority = "NEEDS_FOUNDER_INPUT", "下一步需要你確認可接觸的買家或可信分發路徑。", 90
    else:
        # PARK / DO_NOT_INVEST_NOW / research / watch are states, not recurring inbox events.
        return {"attention_state": "NONE", "requires_founder_action": False, "inbox_reason": None, "attention_priority": 0, "attention_event_id": None}
    event_id = stable_id("ATTENTION_EVENT", f"{opportunity_id_value}:{att}:{state}")
    return {"attention_state": att, "requires_founder_action": True, "inbox_reason": reason, "attention_priority": priority, "attention_event_id": event_id}


def _published_snapshot_contract(thesis: Mapping[str, Any]) -> dict[str, Any]:
    """Expose snapshot identity only when an immutable snapshot id actually exists."""
    thesis_id = _clean(thesis.get("thesis_id"), 1000) or None
    snapshot_id = _clean(thesis.get("published_snapshot_id") or thesis.get("snapshot_id") or thesis.get("immutable_snapshot_id"), 1000) or None
    revision_raw = thesis.get("published_revision") if thesis.get("published_revision") is not None else thesis.get("revision")
    revision = revision_raw if isinstance(revision_raw, (int, str)) and _clean(revision_raw, 200) else None
    return {"published_thesis_id": thesis_id, "published_snapshot_id": snapshot_id, "published_revision": revision}

def _money_summary_from_founder_probe(published: Mapping[str, Any], lineage: Mapping[str, Any]) -> dict[str, Any]:
    matched = bool(lineage.get("allow_truth_inheritance"))
    if not matched:
        return {
            "buyer": {"state": "UNKNOWN", "label": "未知"},
            "existing_spend": {"state": "UNKNOWN", "label": "未知"},
            "paid_dissatisfaction": {"state": "UNKNOWN", "label": "未知", "count": 0},
            "reachability": {"state": "UNKNOWN", "label": "未知"},
        }
    buyer = _mapping(published.get("buyer_segment") or published.get("buyer"))
    spend = _mapping(published.get("current_spend"))
    pd = _mapping(published.get("paid_dissatisfaction"))
    wedge = _mapping(published.get("revenue_wedge"))
    buyer_text = buyer.get("segment") or buyer.get("label") or buyer.get("buyer") or "UNKNOWN"
    buyer_founder_label = _buyer_founder_label(buyer_text)
    spend_state = _upper(spend.get("status")) or "UNKNOWN"
    pd_count = int(pd.get("count") or 0)
    pd_state = _upper(pd.get("status")) or ("SUPPORTED" if pd_count else "UNKNOWN")
    reach_state = _upper(wedge.get("buyer_reachability")) or "UNKNOWN"
    return {
        "buyer": {"state": "KNOWN" if _upper(buyer_text) != "UNKNOWN" else "UNKNOWN", "label": buyer_founder_label},
        "existing_spend": {"state": spend_state, "label": _state_label(spend_state)},
        "paid_dissatisfaction": {"state": pd_state, "label": _state_label(pd_state), "count": pd_count},
        "reachability": {"state": reach_state, "label": _state_label(reach_state)},
    }


def _founder_hypothesis_call(frontier: Mapping[str, Any], fast: Mapping[str, Any], lineage: Mapping[str, Any]) -> tuple[str, str, str, str]:
    mode = _upper(frontier.get("next_mode"))
    if lineage.get("state") == "CANONICAL_MATCH":
        return ("EXISTING_THESIS_REVIEW", "檢查是否沿用既有問題族群", "這個方向可能已有可沿用的 Published problem lineage，但仍需要確認目前 Founder idea 與既有 thesis 的關係。", "FOUNDER")
    if _upper(frontier.get("founder_hypothesis_disposition")) == "WAIT_FOR_SOURCE_FIT" or mode == "SOURCE_FIT_RESEARCH":
        return ("CONTINUE_RESEARCH", "先補適配來源，再判斷市場", "目前的來源組合不適合這類 buyer / problem；0 traces 不能被解讀成市場不存在。", "SIGNALFORGE")
    if mode == "PARK_FOUNDER_HYPOTHESIS":
        return ("PARK", "目前先停在這裡", _clean(frontier.get("question")) or "適配 bounded research 已完成，剩餘未知的資訊價值不足以支持繼續投入。", "MARKET_WAIT")
    if int(fast.get("problem_discussions") or 0) == 0 and int(fast.get("firsthand_pain") or 0) == 0:
        return ("INSUFFICIENT_EVIDENCE", "目前沒有足夠市場證據", "目前還沒有足夠、可安全沿用的市場證據支持這個方向。", "SIGNALFORGE")
    return ("CONTINUE_RESEARCH", "繼續查證，現在不要做產品", "已看到初步市場痕跡，但還不足以進入市場測試。", "SIGNALFORGE")


def build_founder_hypothesis_opportunity_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """FounderOpportunityView for a durable Part 1 Founder hypothesis."""
    hid = _clean(row.get("hypothesis_id"), 1000)
    if not hid:
        raise ValueError("Founder hypothesis requires hypothesis_id")
    probe = _mapping(row.get("last_probe"))
    fast = _mapping(probe.get("fast_probe"))
    published = _mapping(probe.get("published_money_trail"))
    frontier = _mapping(probe.get("decision_frontier"))
    binding = _mapping(published.get("published_thesis_match"))
    lineage = build_lineage_review(binding)
    state, label, why, owner = _founder_hypothesis_call(frontier, fast, lineage)
    question = _founder_copy(frontier.get("question"), "目前還沒有形成唯一需要回答的問題")
    today = _mapping(probe.get("today"))
    next_label = _founder_copy(today.get("today_action") or frontier.get("today_action"), "決定下一個限定且可驗證的查證動作")
    stop = _founder_copy(frontier.get("kill_if"), "當預先定義的 Founder 停手條件成立時停止")
    source_oid = opportunity_id("FOUNDER_HYPOTHESIS", hid)
    oid, _ = canonical_opportunity_id(source_kind="FOUNDER_HYPOTHESIS", canonical_source_id=hid, lineage_review=lineage)
    alias_of = oid if oid != source_oid else None
    attention = _attention_contract(opportunity_id_value=oid, call_state=state, owner=owner, explicit=_mapping(row.get("attention")))
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderOpportunityView",
        "opportunity_id": oid,
        "canonical_opportunity_id": oid,
        "alias_of": alias_of,
        "title": row.get("title"),
        "source": {
            "kind": "FOUNDER_HYPOTHESIS", "canonical_id": hid, "provenance": "FOUNDER_HYPOTHESIS", "market_authority": "NONE",
            "source_opportunity_id": source_oid,
        },
        "current_call": {"state": state, "label": label},
        "why": _founder_copy(why, "目前還沒有足夠市場證據支持直接投入。"),
        "decision_frontier": {"question": question},
        "source_adequacy": dict(_mapping(frontier.get("source_adequacy") or fast.get("source_adequacy"))),
        "founder_playbook": dict(_mapping(published.get("founder_playbook"))),
        "next_action": {"owner": owner, "label": next_label},
        "stop_condition": {"label": stop},
        "owner": {"state": owner, "label": owner_label(owner)},
        "attention": attention,
        "attention_state": attention.get("attention_state"),
        "requires_founder_action": attention.get("requires_founder_action"),
        "inbox_reason": attention.get("inbox_reason"),
        "attention_priority": attention.get("attention_priority"),
        "attention_event_id": attention.get("attention_event_id"),
        "money": _money_summary_from_founder_probe(published, lineage),
        "lineage_review": lineage,
        "search_coverage": {"state": _upper(fast.get("coverage")) or "UNKNOWN", "label": _state_label(_upper(fast.get("coverage")) or "UNKNOWN")},
        "stable_ids": {
            "opportunity_id": oid,
            "canonical_opportunity_id": oid,
            "source_opportunity_id": source_oid,
            "founder_hypothesis_id": stable_id("FOUNDER_HYPOTHESIS", hid),
            "published_thesis_id": stable_id("PUBLISHED_THESIS", lineage["published_thesis_id"]) if lineage.get("published_thesis_id") else None,
            "problem_lineage_id": stable_id("PROBLEM_LINEAGE", lineage["problem_lineage_id"]) if lineage.get("problem_lineage_id") else None,
        },
        "integration": {"execution_target": None, "handoff_status": "NOT_REQUESTED", "execution_contract_id": None, "external_execution_id": None},
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }

def _published_call(item: Mapping[str, Any]) -> tuple[str, str, str]:
    action = _upper(item.get("founder_action"))
    hard_kill = bool(item.get("hard_kill"))
    if hard_kill or action == "PARK":
        return ("DO_NOT_INVEST_NOW", "現在不要投入", "FOUNDER")
    if action == "PARK_OR_PARTNER":
        return ("DO_NOT_INVEST_NOW", "現在不適合你投入", "FOUNDER")
    if action == "ACTION_NOW":
        return ("READY_FOR_MARKET_TEST", "準備市場測試", "FOUNDER")
    if action == "VALIDATE_DISTRIBUTION":
        return ("VALIDATE_DISTRIBUTION", "先驗證你能不能有效接觸這個市場", "FOUNDER")
    if action == "WATCH":
        return ("WATCH", "長期可能重要，現在先觀察", "MARKET_WAIT")
    return ("CONTINUE_RESEARCH", "繼續查證，現在不要做產品", "SIGNALFORGE")


def build_published_opportunity_view(thesis: Mapping[str, Any], trail: Mapping[str, Any], decision_item: Mapping[str, Any]) -> dict[str, Any]:
    """FounderOpportunityView over an existing Published thesis."""
    tid = _clean(thesis.get("thesis_id") or decision_item.get("thesis_id"), 1000)
    if not tid:
        raise ValueError("Published thesis requires thesis_id")
    oid = opportunity_id("PUBLISHED_THESIS", tid)
    call_state, call_label, owner = _published_call(decision_item)
    frontier = _mapping(decision_item.get("decision_frontier"))
    raw_reason = _clean(_mapping(decision_item.get("rank_explanation")).get("plain_reason"))
    if not raw_reason:
        raw_reason = _clean(decision_item.get("founder_actionability", {}).get("reason") if isinstance(decision_item.get("founder_actionability"), Mapping) else "")
    reason = _founder_copy(raw_reason, "目前判斷由已發布市場證據、Money Trail、Founder Fit 與已驗證反方證據共同決定。")
    buyer = _mapping(trail.get("buyer_segment") or trail.get("buyer"))
    spend = _mapping(trail.get("current_spend"))
    pd = _mapping(trail.get("paid_dissatisfaction"))
    wedge = _mapping(trail.get("revenue_wedge"))
    buyer_raw = buyer.get("segment") or buyer.get("label") or buyer.get("buyer")
    buyer_label = _buyer_founder_label(buyer_raw)
    spend_state = _upper(spend.get("status")) or _upper(decision_item.get("existing_spend")) or "UNKNOWN"
    pd_count = int(pd.get("count") or decision_item.get("paid_dissatisfaction_count") or 0)
    pd_state = _upper(pd.get("status")) or _upper(decision_item.get("paid_dissatisfaction_status")) or ("SUPPORTED" if pd_count else "UNKNOWN")
    reach = _upper(wedge.get("buyer_reachability")) or "UNKNOWN"
    question = _founder_copy(frontier.get("question") or decision_item.get("best_next_evidence"), "目前還沒有形成唯一需要回答的問題")
    next_fallback = {
        "FOUNDER": "決定是否執行目前建議的 Founder 行動",
        "SIGNALFORGE": "繼續回答目前最關鍵的未知",
        "MARKET_WAIT": "等待觸發條件或新的市場證據",
    }.get(owner, "決定下一步")
    next_label = _founder_copy(frontier.get("today_action") or decision_item.get("best_next_action"), next_fallback)
    stop = _founder_copy(frontier.get("kill_if"), "如果目前關鍵假設被 Published evidence 反駁，就停止或降級。")
    snapshot = _published_snapshot_contract(thesis)
    attention = _attention_contract(opportunity_id_value=oid, call_state=call_state, owner=owner, explicit=_mapping(decision_item.get("attention")))
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderOpportunityView",
        "opportunity_id": oid,
        "canonical_opportunity_id": oid,
        "alias_of": None,
        "title": thesis.get("title") or decision_item.get("title"),
        "source": {
            "kind": "PUBLISHED_THESIS", "canonical_id": tid, "market_authority": "PUBLISHED",
            **snapshot,
        },
        "current_call": {"state": call_state, "label": call_label},
        "why": reason,
        "decision_frontier": {"question": question},
        "next_action": {"owner": owner, "label": next_label},
        "stop_condition": {"label": stop},
        "owner": {"state": owner, "label": owner_label(owner)},
        "attention": attention,
        "attention_state": attention.get("attention_state"),
        "requires_founder_action": attention.get("requires_founder_action"),
        "inbox_reason": attention.get("inbox_reason"),
        "attention_priority": attention.get("attention_priority"),
        "attention_event_id": attention.get("attention_event_id"),
        "money": {
            "buyer": {"state": "KNOWN" if buyer_label != "未知" else "UNKNOWN", "label": buyer_label},
            "existing_spend": {"state": spend_state, "label": _state_label(spend_state)},
            "paid_dissatisfaction": {"state": pd_state, "label": _state_label(pd_state), "count": pd_count},
            "reachability": {"state": reach, "label": _state_label(reach)},
        },
        "lineage_review": {
            "state": "CANONICAL_MATCH", "label": "Published thesis 已有 canonical problem lineage",
            "published_thesis_id": tid,
            "problem_lineage_id": _clean(thesis.get("problem_lineage_id"), 1000) or None,
            "canonical_binding_id": _clean(thesis.get("canonical_binding_id"), 1000) or None,
            "truth_inheritance": "PUBLISHED_OBJECT_OWNS_ITS_EXISTING_TRUTH", "allow_truth_inheritance": True, "market_truth_writes": 0,
        },
        "stable_ids": {
            "opportunity_id": oid,
            "canonical_opportunity_id": oid,
            "source_opportunity_id": oid,
            "published_thesis_id": stable_id("PUBLISHED_THESIS", tid),
            "problem_lineage_id": stable_id("PROBLEM_LINEAGE", str(thesis.get("problem_lineage_id"))) if thesis.get("problem_lineage_id") else None,
        },
        "integration": {"execution_target": None, "handoff_status": "NOT_REQUESTED", "execution_contract_id": None, "external_execution_id": None},
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }

def build_opportunity_list_view(opportunity_views: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # One canonical Opportunity home. If multiple source objects resolve to the
    # same canonical opportunity_id, keep one row and preserve source aliases.
    merged: dict[str, dict[str, Any]] = {}
    for v0 in opportunity_views:
        v = dict(v0)
        oid = _clean(v.get("canonical_opportunity_id") or v.get("opportunity_id"), 1000)
        if not oid:
            continue
        if oid not in merged:
            merged[oid] = v
            merged[oid].setdefault("source_aliases", [])
        else:
            existing = merged[oid]
            existing_src = _mapping(existing.get("source"))
            src = _mapping(v.get("source"))
            aliases = list(existing.get("source_aliases", []))
            for candidate_view, candidate_src in ((existing, existing_src), (v, src)):
                if candidate_src:
                    alias = {"kind": candidate_src.get("kind"), "canonical_id": candidate_src.get("canonical_id"), "source_opportunity_id": candidate_src.get("source_opportunity_id") or candidate_view.get("opportunity_id")}
                    if alias not in aliases:
                        aliases.append(alias)
            # Prefer Published thesis as the canonical display projection while
            # preserving every source object's identity as an alias.
            if _upper(src.get("kind")) == "PUBLISHED_THESIS" and _upper(existing_src.get("kind")) != "PUBLISHED_THESIS":
                existing.clear(); existing.update(v)
            existing["source_aliases"] = aliases
    rows = []
    for v in merged.values():
        owner = _mapping(v.get("owner"))
        call = _mapping(v.get("current_call"))
        nxt = _mapping(v.get("next_action"))
        att = _mapping(v.get("attention"))
        state = _upper(call.get("state"))
        section = "PAUSED" if state in {"DO_NOT_INVEST_NOW", "PARK"} else "WATCHING" if state == "WATCH" else "ACTIVE"
        rows.append({
            "opportunity_id": v.get("canonical_opportunity_id") or v.get("opportunity_id"),
            "title": v.get("title"),
            "section": section,
            "current_call": dict(call),
            "next_action": dict(nxt),
            "owner": dict(owner),
            "attention": dict(att),
            "source_kind": _mapping(v.get("source")).get("kind"),
            "source_aliases": _list(v.get("source_aliases")),
        })
    return {"engine_version": ENGINE_VERSION, "view_model": "FounderOpportunityListView", "items": rows, "count": len(rows), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def build_today_view(opportunity_views: Sequence[Mapping[str, Any]], *, max_founder_items: int = 3) -> dict[str, Any]:
    founder_items = []
    background = {"SIGNALFORGE": 0, "MARKET_WAIT": 0, "CHATGPT": 0, "EASON_ONE": 0}
    seen_events: set[str] = set()
    for v in opportunity_views:
        owner = _upper(_mapping(v.get("owner")).get("state"))
        att = _mapping(v.get("attention"))
        requires = bool(att.get("requires_founder_action"))
        event_id = _clean(att.get("attention_event_id"), 1000)
        if requires and event_id and event_id not in seen_events:
            seen_events.add(event_id)
            founder_items.append({
                "opportunity_id": v.get("canonical_opportunity_id") or v.get("opportunity_id"),
                "title": v.get("title"),
                "current_call": v.get("current_call"),
                "why_now": att.get("inbox_reason") or v.get("why"),
                "decision_frontier": v.get("decision_frontier"),
                "next_action": v.get("next_action"),
                "stop_condition": v.get("stop_condition"),
                "attention_state": att.get("attention_state"),
                "attention_priority": int(att.get("attention_priority") or 0),
                "attention_event_id": event_id,
            })
        elif owner in background:
            background[owner] += 1
    # Canonical priority first; input/data ordering never decides Founder attention.
    founder_items.sort(key=lambda x: (-int(x.get("attention_priority") or 0), str(x.get("attention_event_id") or ""), str(x.get("opportunity_id") or "")))
    cap = max(1, min(int(max_founder_items), 3))
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderTodayView",
        "needs_founder_count": len(founder_items),
        "items": founder_items[:cap],
        "background": {
            "signalforge_researching": background["SIGNALFORGE"],
            "waiting_market": background["MARKET_WAIT"],
            "chatgpt_discussion": background["CHATGPT"],
            "future_eason_one": background["EASON_ONE"],
        },
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }

def build_evidence_inspector_view(*, opportunity_id_value: str, supporting: Iterable[Mapping[str, Any]] = (), contradicting: Iterable[Mapping[str, Any]] = (), unknowns: Iterable[Any] = (), source_independence: Any = None, search_coverage: Mapping[str, Any] | None = None, lineage_review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderEvidenceInspectorView",
        "opportunity_id": opportunity_id_value,
        "supporting": [dict(x) for x in supporting],
        "contradicting": [dict(x) for x in contradicting],
        "unknowns": list(unknowns),
        "source_independence": source_independence,
        "search_coverage": dict(search_coverage or {}),
        "lineage_review": dict(lineage_review or {}),
        "system_details_default_expanded": False,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def build_compare_view(compare_result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderCompareView",
        "items": _list(compare_result.get("items") or compare_result.get("ranking")),
        "questions_answered": ["NOW", "LONG_TERM", "BIGGEST_UNKNOWN", "WHAT_CHANGES_RANKING"],
        "ranking_method": compare_result.get("ranking_method") or "TRANSPARENT_LEXICOGRAPHIC_RULES",
        "opaque_score": False,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def build_market_test_view(test: Mapping[str, Any]) -> dict[str, Any]:
    action_id = _clean(test.get("action_id") or test.get("market_action_id"), 1000)
    stable = stable_id("MARKET_TEST", action_id) if action_id else None
    rule = _mapping(test.get("decision_rule"))
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderMarketTestView",
        "market_test_id": stable,
        "market_action_id": action_id or None,
        "hypothesis": test.get("hypothesis"),
        "target": test.get("target"),
        "test": test.get("test"),
        "success": rule.get("success") or test.get("success"),
        "failure": rule.get("failure") or test.get("failure"),
        "inconclusive": rule.get("inconclusive") or test.get("inconclusive"),
        "max_cost": test.get("max_cost"),
        "max_sample": test.get("max_sample"),
        "locked": _upper(test.get("status")) in {"PREREGISTERED", "ACTIVE", "COMPLETED"},
        "execution_target": test.get("execution_target"),
        "handoff_status": test.get("handoff_status") or "NOT_REQUESTED",
        "execution_contract_id": test.get("execution_contract_id"),
        "external_execution_id": test.get("external_execution_id"),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def build_outcome_view(outcome: Mapping[str, Any]) -> dict[str, Any]:
    oid = _clean(outcome.get("outcome_id") or outcome.get("action_id"), 1000)
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderOutcomeView",
        "outcome_id": stable_id("OUTCOME", oid) if oid else None,
        "result": outcome.get("result"),
        "derived_counts": dict(_mapping(outcome.get("derived_counts") or outcome.get("counts"))),
        "supports": _list(outcome.get("supports")),
        "does_not_prove": _list(outcome.get("does_not_prove")),
        "actual_cost": outcome.get("actual_cost"),
        "cost_breach": bool(outcome.get("cost_breach")),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def build_learning_view(report: Mapping[str, Any]) -> dict[str, Any]:
    status = _upper(report.get("status") or report.get("general_predictive_accuracy")) or "UNVALIDATED"
    independent = int(report.get("independent_market_tests") or report.get("distinct_entities") or 0)
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderLearningView",
        "status": status,
        "label": "尚未完成校準" if status == "UNVALIDATED" else "已累積足夠的限定市場學習",
        "independent_market_tests": independent,
        "can_change_future_ranking": bool(report.get("can_change_future_ranking")) if status != "UNVALIDATED" else False,
        "summary": report.get("summary"),
        "market_truth_writes": 0,
        "truth_boundary": "FOUNDER_LEARNING_VIEW_NEVER_TURNS_ENGINEERING_ACCEPTANCE_INTO_MARKET_ACCURACY",
    }


def build_discussion_context(opportunity_view: Mapping[str, Any], *, discussion_packet: Mapping[str, Any] | None = None, active_market_test_id: str | None = None) -> dict[str, Any]:
    source = _mapping(opportunity_view.get("source"))
    kind = _upper(source.get("kind"))
    lineage = _mapping(opportunity_view.get("lineage_review"))
    published_thesis_id = source.get("published_thesis_id") if kind == "PUBLISHED_THESIS" else lineage.get("published_thesis_id")
    # Never use thesis identity as fake immutable snapshot identity.
    published_snapshot_id = source.get("published_snapshot_id") if kind == "PUBLISHED_THESIS" else None
    published_revision = source.get("published_revision") if kind == "PUBLISHED_THESIS" else None
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderDiscussionContext",
        "opportunity_id": opportunity_view.get("canonical_opportunity_id") or opportunity_view.get("opportunity_id"),
        "published_thesis_id": published_thesis_id,
        "published_snapshot_id": published_snapshot_id,
        "published_revision": published_revision,
        "current_call": opportunity_view.get("current_call"),
        "decision_frontier": opportunity_view.get("decision_frontier"),
        "money_summary": opportunity_view.get("money"),
        "evidence_summary": _mapping(discussion_packet).get("evidence_replay"),
        "counterevidence_summary": _mapping(discussion_packet).get("counterevidence"),
        "founder_memory_summary": _mapping(discussion_packet).get("founder_memory"),
        "active_market_test_id": active_market_test_id,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def build_handoff_preview(*, opportunity_view: Mapping[str, Any], market_test: Mapping[str, Any] | None = None) -> dict[str, Any]:
    test = _mapping(market_test)
    source_market_test_id = test.get("market_test_id") or test.get("action_id")
    opportunity_id_value = opportunity_view.get("canonical_opportunity_id") or opportunity_view.get("opportunity_id")
    return {
        "engine_version": ENGINE_VERSION,
        "view_model": "FounderHandoffPreview",
        "status": "RESERVED_NOT_EXECUTABLE",
        "opportunity_id": opportunity_id_value,
        "source_opportunity_id": opportunity_id_value,
        "execution_target": "EASON_ONE",
        "handoff_status": "PREVIEW_ONLY",
        "execution_contract_id": None,
        "external_execution_id": None,
        "source_market_test_id": source_market_test_id,
        "goal": test.get("test") or _mapping(opportunity_view.get("next_action")).get("label"),
        "why": test.get("why") or opportunity_view.get("why"),
        "deliverable": test.get("deliverable"),
        "deadline": test.get("deadline"),
        "must_verify": _list(test.get("must_verify")),
        "constraints": _list(test.get("constraints")),
        "budget": test.get("max_cost"),
        "do_not_do": _list(test.get("do_not_do")),
        "confirmation_required": True,
        "runtime_integration_available": False,
        "market_truth_writes": 0,
        "truth_boundary": "EASON_ONE_IS_SCHEMA_RESERVATION_ONLY_IN_FOUNDER_UX_V1_PHASE1;_NO_EXECUTION_SIDE_EFFECT",
    }

def architecture_status() -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "status": "PASS",
        "phase": "PHASE_1_PRODUCT_VIEW_MODEL",
        "owner_values": sorted(OWNER_VALUES),
        "attention_states": sorted(ATTENTION_STATES),
        "lineage_review_states": sorted(LINEAGE_REVIEW_STATES),
        "view_models": [
            "FounderTodayView", "FounderOpportunityListView", "FounderOpportunityView",
            "FounderEvidenceInspectorView", "FounderCompareView", "FounderMarketTestView",
            "FounderOutcomeView", "FounderLearningView", "FounderDiscussionContext", "FounderHandoffPreview",
        ],
        "frontend_business_logic_allowed": False,
        "chatgpt_full_live_integration_required_this_phase": False,
        "eason_one_runtime_required_this_phase": False,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }

async def build_current_opportunity_views(*, limit: int = 50, root: Any = None) -> list[dict[str, Any]]:
    """Build canonical FounderOpportunityView rows from current Published + Founder-hypothesis state."""
    from processors.signalforge_brain_v2_engine import get_brain_v2_portfolio
    from processors.signalforge_money_trail import build_money_trail_for_thesis
    from processors.signalforge_opportunity_decision_closure import (
        build_opportunity_decision_portfolio_closure,
        decorate_item,
    )
    from processors.signalforge_opportunity_decision import build_decision_item
    from processors.signalforge_founder_hypothesis_registry import list_founder_hypotheses

    portfolio = dict(get_brain_v2_portfolio(root=root)) if root is not None else dict(get_brain_v2_portfolio())
    theses = [dict(x) for x in _list(portfolio.get("portfolio")) if isinstance(x, Mapping)]
    thesis_by_id = {_clean(x.get("thesis_id"), 1000): x for x in theses if _clean(x.get("thesis_id"), 1000)}
    # Use the same Part 4 closure decision authority, but project the result here.
    decision = await build_opportunity_decision_portfolio_closure(limit=max(1, min(int(limit), 100)), root=root)
    decision_by_id = {
        _clean(x.get("thesis_id"), 1000): dict(x)
        for x in _list(decision.get("items"))
        if isinstance(x, Mapping) and _upper(x.get("source_kind")) != "FOUNDER_HYPOTHESIS" and _clean(x.get("thesis_id"), 1000)
    }
    views: list[dict[str, Any]] = []
    for tid, thesis in list(thesis_by_id.items())[: max(1, min(int(limit), 100))]:
        try:
            trail = await build_money_trail_for_thesis(thesis)
        except Exception as exc:
            trail = {"status": "MONEY_TRAIL_UNAVAILABLE_NON_BLOCKING", "error": f"{type(exc).__name__}: {exc}", "current_spend": {"status": "UNKNOWN"}, "paid_dissatisfaction": {"status": "UNKNOWN", "count": 0}, "revenue_wedge": {"buyer_reachability": "UNKNOWN"}}
        item = decision_by_id.get(tid)
        if not item:
            item = decorate_item(thesis, trail, build_decision_item(thesis, trail), root=root)
        views.append(build_published_opportunity_view(thesis, trail, item))

    by_opportunity = {_clean(v.get("opportunity_id"), 1000): v for v in views if _clean(v.get("opportunity_id"), 1000)}
    for row in list_founder_hypotheses(limit=max(1, min(int(limit), 100)), root=root):
        hv = build_founder_hypothesis_opportunity_view(row)
        oid = _clean(hv.get("opportunity_id"), 1000)
        if oid and oid in by_opportunity:
            existing = by_opportunity[oid]
            alias = {
                "kind": "FOUNDER_HYPOTHESIS",
                "canonical_id": _mapping(hv.get("source")).get("canonical_id"),
                "source_opportunity_id": _mapping(hv.get("source")).get("source_opportunity_id"),
            }
            existing.setdefault("source_aliases", []).append(alias)
            existing.setdefault("stable_ids", {}).setdefault("founder_hypothesis_ids", []).append(_mapping(hv.get("stable_ids")).get("founder_hypothesis_id"))
            existing["founder_lineage_review"] = hv.get("lineage_review")
            continue
        views.append(hv)
        if oid:
            by_opportunity[oid] = hv
    return views


async def current_opportunity_list_view(*, limit: int = 50, root: Any = None) -> dict[str, Any]:
    return build_opportunity_list_view(await build_current_opportunity_views(limit=limit, root=root))


async def current_today_view(*, limit: int = 50, root: Any = None) -> dict[str, Any]:
    return build_today_view(await build_current_opportunity_views(limit=limit, root=root))


async def current_opportunity_view(opportunity_id_value: str, *, limit: int = 100, root: Any = None) -> dict[str, Any] | None:
    target = _clean(opportunity_id_value, 1000)
    for row in await build_current_opportunity_views(limit=limit, root=root):
        if _clean(row.get("opportunity_id"), 1000) == target:
            return row
    return None
