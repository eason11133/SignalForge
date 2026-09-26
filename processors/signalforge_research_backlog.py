from __future__ import annotations

import asyncio
import copy
import difflib
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from processors.signalforge_behavior_tracking import (
    BEHAVIOR_TRACKING_VERSION,
    ManualTrendsProvider,
    enrich_material,
    migrate_behavior_state,
    record_behavior_cycle,
)

ENGINE_VERSION = "signalforge-research-backlog-v1.6-parallel-freshness-hotfix11"
STORE_PATH = Path(".radar_runtime/founder_opportunity_research_v1.json")
LEGACY_STORE_PATH = Path(".radar_runtime/idea_research_backlog_v1.json")
CURATED_SOURCE_KINDS = {
    "FOUNDER_OPPORTUNITY",
    "FOUNDER_IDEA",
    "AI_DISCUSSION",
    "CURATED_OPPORTUNITY",
    "MANUAL",
    "USER_SUBMITTED",
}
TRUTH_BOUNDARY = (
    "RESEARCH_BACKLOG_IS_FOUNDER_WORKFLOW_STATE_ONLY;_"
    "UNVALIDATED_SEARCH_TRACES_NEVER_BECOME_MARKET_TRUTH_OR_CALIBRATION;_"
    "EVIDENCE_MUST_MATCH_BOTH_OPPORTUNITY_AND_RESEARCH_LANE;_"
    "RELATED_OR_DUPLICATE_TRACES_DO_NOT_COUNT_AS_QUALIFIED_EVIDENCE;_"
    "REVIEW_READY_REQUIRES_EVIDENCE_DIVERSITY_NOT_JUST_LANE_ATTEMPTS"
)

_LOCK = threading.RLock()
_SINGLE_ITEM_RUN_LOCK = threading.Lock()
_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")

JOB_ORDER = (
    "BASELINE",
    "CURRENT_SOLUTIONS",
    "PAID_DISSATISFACTION",
    "BUYER_PAYER_WTP",
    "COUNTEREVIDENCE",
)

JOB_QUESTIONS = {
    "BASELINE": "這個問題在公開市場上是否真的有可辨識的真人討論、現有方案或反面資料？",
    "CURRENT_SOLUTIONS": "受影響的人現在到底怎麼解這個問題，現有產品、服務、開源工具與人工 workaround 各覆蓋哪一段？",
    "PAID_DISSATISFACTION": "已經付錢或投入明顯成本的人，是否仍然需要手動補洞、抱怨、換工具或承受返工？",
    "BUYER_PAYER_WTP": "誰擁有這個 workflow、誰能決定預算，公開資料裡是否有實際 spend、採購、切換或 willingness-to-pay 證據？",
    "COUNTEREVIDENCE": "有哪些證據會推翻這個方向，例如問題其實不重要、已經被解得夠好、被現有產品綁定，或正在快速消失？",
}

TERMINAL_AUTO_STATES = {
    "PARKED_NO_PUBLIC_SIGNAL",
    "PARKED_WEAK_SIGNAL",
    "SOURCE_LIMITED",
    "REVIEW_READY",
    "STOPPED",
}

# Fast recovery is bounded; after repeated outages SignalForge falls back to a weekly probe
# instead of hammering public sources every idle poll.
_SOURCE_RETRY_DELAYS_SECONDS = (300, 900, 3600, 14400, 86400, 259200, 604800)
_SOURCE_CIRCUIT_DELAYS_SECONDS = (300, 900, 3600, 14400, 86400)
_SOURCE_CIRCUIT_THRESHOLD = 6
_POST_INITIAL_NEW_BURST = 3
_DEFAULT_RESEARCH_CONCURRENCY = 6
_MAX_RESEARCH_CONCURRENCY = 12
_REVIEW_READY_FRESHNESS_SECONDS = 7 * 86400
_PARKED_WEAK_FRESHNESS_SECONDS = 14 * 86400
_PARKED_NO_SIGNAL_FRESHNESS_SECONDS = 30 * 86400


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_secret_available(name: str) -> bool:
    if _clean(os.environ.get(name)):
        return True
    if os.name != "nt":
        return False
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return bool(_clean(value))
    except Exception:
        return False


def _general_web_runtime_configured() -> bool:
    return any(_runtime_secret_available(name) for name in ("SERPER_API_KEY", "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"))


def _latest_history_missing_general_web_config(item: Mapping[str, Any]) -> bool:
    for row in reversed([x for x in (item.get("history") or []) if isinstance(x, Mapping)]):
        trace = row.get("research_trace") if isinstance(row.get("research_trace"), Mapping) else {}
        failed = trace.get("failed_sources") if isinstance(trace.get("failed_sources"), list) else []
        text = " ".join(_clean(x.get("error") if isinstance(x, Mapping) else x) for x in failed).upper()
        if "GENERAL_WEB_PROVIDER_NOT_CONFIGURED" in text or "SERPER_API_KEY_NOT_CONFIGURED" in text or "TAVILY_API_KEY_NOT_CONFIGURED" in text or "BRAVE_SEARCH_API_KEY_NOT_CONFIGURED" in text:
            return True
        # Only inspect the newest completed lane attempt.
        break
    return False


def _source_retry_due(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    if _clean(item.get("auto_status")).upper() != "SOURCE_LIMITED":
        return False
    job = _clean(item.get("next_job")).upper()
    if job not in JOB_ORDER:
        return False
    if _general_web_runtime_configured() and _latest_history_missing_general_web_config(item):
        return True
    retry_at = _parse_time(item.get("source_retry_after"))
    if retry_at is None:
        return True
    return retry_at <= (now or datetime.now(timezone.utc))


def _schedule_source_retry(item: dict[str, Any], job: str, reason: str) -> None:
    streak = max(0, int(item.get("source_retry_count") or 0)) + 1
    delay = _SOURCE_RETRY_DELAYS_SECONDS[min(streak - 1, len(_SOURCE_RETRY_DELAYS_SECONDS) - 1)]
    item["source_retry_count"] = streak
    item["source_last_limited_at"] = _now()
    item["source_retry_after"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    item["source_retry_job"] = job
    item["source_retry_reason"] = _clean(reason)[:900]


def _clear_source_retry(item: dict[str, Any]) -> None:
    item["source_retry_count"] = 0
    item["source_retry_after"] = None
    item["source_retry_job"] = None
    item["source_retry_reason"] = None


def _source_circuit_waiting(store: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    retry_at = _parse_time(automation.get("source_circuit_retry_after"))
    return retry_at is not None and retry_at > (now or datetime.now(timezone.utc))


def _record_source_health(store: dict[str, Any], *, limited: bool, reason: str = "") -> bool:
    """Open a global cooldown only for repeated transport/source outages, never for thin coverage alone."""
    worker = store.setdefault("worker", {})
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    if not limited:
        worker["consecutive_source_limited"] = 0
        # One healthy research result proves the batch path can reach enough sources again.
        automation["source_circuit_open_count"] = 0
        automation["source_circuit_retry_after"] = None
        automation["source_circuit_reason"] = None
        return False

    streak = int(worker.get("consecutive_source_limited") or 0) + 1
    worker["consecutive_source_limited"] = streak
    threshold = max(2, int(automation.get("source_circuit_threshold") or _SOURCE_CIRCUIT_THRESHOLD))
    if streak < threshold:
        return False

    opens = max(0, int(automation.get("source_circuit_open_count") or 0)) + 1
    delay = _SOURCE_CIRCUIT_DELAYS_SECONDS[min(opens - 1, len(_SOURCE_CIRCUIT_DELAYS_SECONDS) - 1)]
    automation["source_circuit_open_count"] = opens
    automation["source_circuit_last_open_at"] = _now()
    automation["source_circuit_retry_after"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    automation["source_circuit_reason"] = _clean(reason)[:900] or "Repeated source-limited research results"
    worker["status"] = "SOURCE_CIRCUIT_OPEN"
    worker["last_error"] = (
        f"Global source circuit opened after {streak} consecutive source-limited jobs; "
        f"autopilot will retry after {automation['source_circuit_retry_after']}."
    )
    return True


def _infer_source_retry_job(item: Mapping[str, Any]) -> str | None:
    current = _clean(item.get("next_job")).upper()
    if current in JOB_ORDER:
        return current
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    for row in reversed(history):
        job = _clean(row.get("job")).upper()
        if job in JOB_ORDER:
            return job
    return "BASELINE" if _clean(item.get("auto_status")).upper() == "SOURCE_LIMITED" else None


def _migrate_source_retry_state(item: dict[str, Any]) -> bool:
    changed = False
    for key, default in (
        ("source_retry_count", 0),
        ("source_retry_after", None),
        ("source_retry_job", None),
        ("source_retry_reason", None),
        ("source_last_limited_at", None),
    ):
        if key not in item:
            item[key] = default
            changed = True
    if _clean(item.get("auto_status")).upper() != "SOURCE_LIMITED":
        return changed
    job = _infer_source_retry_job(item)
    if job and _clean(item.get("next_job")).upper() != job:
        item["next_job"] = job
        item["next_question"] = f"來源恢復後重跑 {job}；舊版來源不足紀錄不能當成已完成研究。"
        changed = True
    if job and _clean(item.get("source_retry_job")).upper() != job:
        item["source_retry_job"] = job
        changed = True
    if not _clean(item.get("source_retry_after")):
        item["source_retry_after"] = _now()
        changed = True
    history = [row for row in (item.get("history") or []) if isinstance(row, dict)]
    if history and job:
        latest = history[-1]
        if _clean(latest.get("job")).upper() == job and latest.get("coverage_complete") is not False:
            latest["coverage_complete"] = False
            latest["coverage_reason"] = "MIGRATED_SOURCE_LIMITED_NOT_COMPLETE"
            changed = True
    return changed


def _emptyish(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _slug_key(value: str) -> str:
    text = _clean(value).lower()
    words = _WORD_RE.findall(text)
    return " ".join(words[:24])


def _sha_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:18]


def _default_store() -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "items": {},
        "order": [],
        "worker": {
            "status": "IDLE",
            "started_at": None,
            "finished_at": None,
            "current_item_id": None,
            "current_job": None,
            "jobs_completed": 0,
            "jobs_requested": 0,
            "last_error": None,
            "stop_requested": False,
            "retry_attempts": 0,
            "consecutive_source_limited": 0,
            "session_jobs_completed": 0,
            "batches_completed": 0,
            "batch_size": 0,
            "session_job_cap": 0,
            "safety_cap_reached": False,
            "pending_after_session": False,
            "active_jobs": [],
            "active_count": 0,
            "max_concurrency": _DEFAULT_RESEARCH_CONCURRENCY,
            "queued_jobs_estimate": 0,
            "last_wave_started_at": None,
            "last_wave_completed_at": None,
        },
        "automation": {
            "auto_run_enabled": True,
            "paused_by_founder": False,
            "last_auto_start_at": None,
            "last_founder_resume_at": None,
            "last_founder_pause_at": None,
            "last_live_sync_at": None,
            "idle_poll_seconds": 60,
            "continuous_batch_size": 500,
            "session_job_cap": 5000,
            "source_circuit_open_count": 0,
            "source_circuit_retry_after": None,
            "source_circuit_last_open_at": None,
            "source_circuit_reason": None,
            "source_circuit_threshold": _SOURCE_CIRCUIT_THRESHOLD,
            "initial_baseline_wave_complete": False,
            "post_initial_new_since_deep": 0,
            "post_initial_new_burst_limit": _POST_INITIAL_NEW_BURST,
            "research_concurrency": _DEFAULT_RESEARCH_CONCURRENCY,
            "freshness_enabled": True,
            "review_ready_refresh_seconds": _REVIEW_READY_FRESHNESS_SECONDS,
            "parked_weak_refresh_seconds": _PARKED_WEAK_FRESHNESS_SECONDS,
            "parked_no_signal_refresh_seconds": _PARKED_NO_SIGNAL_FRESHNESS_SECONDS,
        },
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def _store_path(repo: str | Path = ".") -> Path:
    return Path(repo).resolve() / STORE_PATH


def _legacy_store_path(repo: str | Path = ".") -> Path:
    return Path(repo).resolve() / LEGACY_STORE_PATH


def _store_backup_path(repo: str | Path = ".") -> Path:
    path = _store_path(repo)
    return path.with_name(path.name + ".bak")


def _read_store_mapping(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _repair_worker(store: dict[str, Any]) -> None:
    worker = store.setdefault("worker", {})
    items = store.get("items") if isinstance(store.get("items"), dict) else {}
    worker_status = _clean(worker.get("status")).upper()
    interrupted_item_id = _clean(worker.get("current_item_id"))
    interrupted_job = _clean(worker.get("current_job")).upper()
    active_jobs = [row for row in (worker.get("active_jobs") or []) if isinstance(row, Mapping)]
    repaired_ids: list[str] = []

    def infer_job(item: Mapping[str, Any], *, preferred: str = "") -> str:
        for value in (preferred, item.get("next_job"), item.get("source_retry_job")):
            job = _clean(value).upper()
            if job in JOB_ORDER:
                return job
        latest_change = _clean(item.get("latest_change")).upper()
        match = re.match(r"^RESEARCH_(.+)_STARTED$", latest_change)
        if match and match.group(1) in JOB_ORDER:
            return match.group(1)
        history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
        completed = {
            _clean(row.get("job")).upper()
            for row in history
            if _clean(row.get("job")).upper() in JOB_ORDER and row.get("coverage_complete") is not False
        }
        for candidate in JOB_ORDER:
            if candidate not in completed:
                return candidate
        return "BASELINE"

    def requeue(item_id: str, *, preferred_job: str = "") -> None:
        if not item_id or item_id in repaired_ids:
            return
        item = items.get(item_id)
        if not isinstance(item, dict):
            return
        job = infer_job(item, preferred=preferred_job)
        item["auto_status"] = "NEW" if job == "BASELINE" else "AUTO_RESEARCH"
        item["next_job"] = job
        item["next_question"] = _next_question(job)
        item["current_call"] = "上次研究被 API 重啟中斷，已自動排回佇列"
        item["why"] = "研究途中 API process 中斷；這不是市場結果，SignalForge 會重跑同一 research lane。"
        item["needs_founder"] = False
        item["latest_change"] = f"RESEARCH_{job}_INTERRUPTED_REQUEUED"
        item["updated_at"] = _now()
        repaired_ids.append(item_id)

    # HOTFIX11 can have multiple process-local in-flight jobs. Requeue every persisted reservation,
    # then keep the old single-job marker as a backwards-compatible fallback.
    if worker_status == "RUNNING":
        for row in active_jobs:
            requeue(_clean(row.get("item_id")), preferred_job=_clean(row.get("job")).upper())
        requeue(interrupted_item_id, preferred_job=interrupted_job)

    # A crash between reserving a job and persisting worker metadata can still leave orphan
    # RESEARCHING items. Repair all of them conservatively.
    for item_id, item in items.items():
        if not isinstance(item, dict) or item_id in repaired_ids:
            continue
        if _clean(item.get("auto_status")).upper() != "RESEARCHING":
            continue
        job = infer_job(item)
        item["auto_status"] = "NEW" if job == "BASELINE" else "AUTO_RESEARCH"
        item["next_job"] = job
        item["next_question"] = _next_question(job)
        item["current_call"] = "偵測到孤兒研究狀態，已自動排回佇列"
        item["why"] = "沒有活著的 process-local worker 對應這個 RESEARCHING 狀態；為避免永久卡死，重跑同一 research lane。"
        item["needs_founder"] = False
        item["latest_change"] = f"RESEARCH_{job}_ORPHAN_REQUEUED"
        item["updated_at"] = _now()
        repaired_ids.append(str(item_id))

    if worker_status == "RUNNING" or repaired_ids:
        worker["status"] = "INTERRUPTED"
        worker["finished_at"] = _now()
        worker["current_item_id"] = None
        worker["current_job"] = None
        worker["active_jobs"] = []
        worker["active_count"] = 0
        worker["stop_requested"] = False
        if not worker.get("last_error"):
            worker["last_error"] = "Previous API process stopped while parallel research was running; in-flight work was requeued."
        worker["recovered_item_ids"] = repaired_ids[-40:]


def _migrate_curated_legacy_store(repo: str | Path) -> dict[str, Any] | None:
    """Create the active Founder-opportunity store from the old mixed V1.4 backlog.

    The legacy file is never changed. Only items that were explicitly submitted/curated by the
    Founder or an AI discussion are promoted. Automatic ProblemCandidate / Opportunity rows stay
    available in the legacy file as research material, but are not active opportunities.
    """
    legacy_path = _legacy_store_path(repo)
    legacy = _read_store_mapping(legacy_path) if legacy_path.exists() else None
    if not isinstance(legacy, dict):
        return None

    old_items = legacy.get("items") if isinstance(legacy.get("items"), dict) else {}
    old_order = list(legacy.get("order") or old_items.keys())
    migrated = _default_store()
    migrated_items: dict[str, Any] = {}
    migrated_order: list[str] = []
    excluded = 0
    preserved = 0

    for item_id in old_order:
        item = old_items.get(item_id)
        if not isinstance(item, Mapping):
            continue
        source_kind = _clean(item.get("source_kind")).upper()
        if source_kind not in CURATED_SOURCE_KINDS:
            excluded += 1
            continue
        copied = copy.deepcopy(dict(item))
        copied["source_kind"] = source_kind or "FOUNDER_OPPORTUNITY"
        migrated_items[str(item_id)] = copied
        migrated_order.append(str(item_id))
        preserved += 1

    migrated["items"] = migrated_items
    migrated["order"] = migrated_order
    migrated["legacy_archive_summary"] = {
        "legacy_path": str(LEGACY_STORE_PATH),
        "legacy_total_items": len(old_items),
        "preserved_curated_items": preserved,
        "excluded_automatic_items": excluded,
        "meaning": "LEGACY_AUTOMATIC_CANDIDATES_PRESERVED_NOT_ACTIVE_RESEARCH_TARGETS",
        "migrated_at": _now(),
    }
    migrated["migration_note"] = (
        "V1.5 active backlog contains only Founder/AI-curated opportunities; "
        "the old mixed V1.4 backlog remains untouched."
    )
    return migrated



def _migrate_v16_full_founder_research(item: dict[str, Any]) -> bool:
    """Resume V1.5 Founder opportunities that were prematurely parked after paid-dissatisfaction.

    The Founder explicitly submitted these opportunities for broad research. V1.6 keeps the paid
    evidence absence as an observation but continues to buyer/payer and counterevidence lanes.
    """
    if _clean(item.get("auto_status")).upper() != "PARKED_WEAK_SIGNAL":
        return False
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    if not history:
        return False
    latest = history[-1]
    if _clean(latest.get("job")).upper() != "PAID_DISSATISFACTION":
        return False
    item["auto_status"] = "AUTO_RESEARCH"
    item["current_call"] = "SignalForge 繼續完整研究"
    item["why"] = (
        "V1.6 不再因 paid dissatisfaction 沒找到直接證據就提前停掉 Founder 商機；"
        "保留該負面結果，繼續獨立查 buyer / payer / pricing / switching 與反證。"
    )
    item["next_job"] = "BUYER_PAYER_WTP"
    item["next_question"] = _next_question("BUYER_PAYER_WTP")
    item["needs_founder"] = False
    item["latest_change"] = "V1_6_FULL_RESEARCH_RESUMED_AFTER_PAID_GAP"
    item["updated_at"] = _now()
    _clear_source_retry(item)
    return True

_ROUTING_TRUST_MIGRATION = "V1_6_ROUTING_TRUST_HOTFIX2"


def _migrate_v16_routing_trust(item: dict[str, Any]) -> bool:
    """Re-open research lanes whose old trace proves the query router did not really execute.

    Evidence/history is preserved. We only mark affected lane snapshots incomplete and schedule the
    earliest affected lane again. This repairs two V1.6 defects observed in real use:
      * SEARCH_FAILED with zero successful AND zero failed source attempts;
      * deep research lanes that reused the generic query instead of a lane-specific executed query.
    """
    if _clean(item.get("routing_trust_migration")).upper() == _ROUTING_TRUST_MIGRATION:
        return False

    history = [row for row in (item.get("history") or []) if isinstance(row, dict)]
    if not history:
        item["routing_trust_migration"] = _ROUTING_TRUST_MIGRATION
        return True

    affected_jobs: set[str] = set()
    changed = False
    for row in history:
        job = _clean(row.get("job")).upper()
        if job not in JOB_ORDER:
            continue
        trace = row.get("research_trace") if isinstance(row.get("research_trace"), Mapping) else {}
        successful = [x for x in (trace.get("successful_sources") or row.get("successful_sources") or []) if _clean(x)]
        failed = [x for x in (trace.get("failed_sources") or row.get("failed_sources") or []) if isinstance(x, Mapping)]
        attempts = [x for x in (trace.get("source_attempts") or []) if isinstance(x, Mapping)]
        query_runs = [x for x in (trace.get("query_runs") or []) if isinstance(x, Mapping)]
        status = _clean(row.get("status")).upper()

        zero_attempt_bug = status == "SEARCH_FAILED" and not successful and not failed and not attempts
        lane_query_bug = False
        if job != "BASELINE" and row.get("coverage_complete") is not False:
            expected_prefix = f"LANE_FOCUS_{job}"
            labels = {_clean(run.get("label")).upper() for run in query_runs}
            lane_query_bug = expected_prefix not in labels

        if not zero_attempt_bug and not lane_query_bug:
            continue
        affected_jobs.add(job)
        new_reason = (
            "LEGACY_ZERO_SOURCE_ATTEMPT_ROUTING_BUG"
            if zero_attempt_bug
            else "LEGACY_DEEP_LANE_QUERY_NOT_LANE_SPECIFIC"
        )
        if row.get("coverage_complete") is not False or _clean(row.get("coverage_reason")) != new_reason:
            row["coverage_complete"] = False
            row["coverage_reason"] = new_reason
            changed = True

    item["routing_trust_migration"] = _ROUTING_TRUST_MIGRATION
    item["routing_trust_migrated_at"] = _now()
    changed = True

    if not affected_jobs:
        return changed

    next_job = next((job for job in JOB_ORDER if job in affected_jobs), "BASELINE")
    item["auto_status"] = "NEW" if next_job == "BASELINE" else "AUTO_RESEARCH"
    item["current_call"] = "SignalForge 重新研究舊版 routing 不可信的 lane"
    item["why"] = (
        "舊版 research trace 顯示有 lane 沒有真正送出任何來源，或 deep lane 沒有使用自己的查詢；"
        "舊 evidence/history 保留，但該 lane 不再算完成，從最早受影響的研究重新跑。"
    )
    item["next_job"] = next_job
    item["next_question"] = _next_question(next_job)
    item["needs_founder"] = False
    item["latest_change"] = "V1_6_ROUTING_TRUST_STALE_LANES_REQUEUED"
    item["updated_at"] = _now()
    item["routing_trust_stale_jobs"] = [job for job in JOB_ORDER if job in affected_jobs]
    _clear_source_retry(item)
    return True


_EVIDENCE_TRUST_MIGRATION = "V1_6_FACET_BINDING_HOTFIX10"
_EVIDENCE_TRUST_RECEIPTS = (
    (".signalforge_r8_research_backlog_v1_6_evidence_trust_hotfix3_install.json", "R8_RESEARCH_BACKLOG_V1_6_EVIDENCE_TRUST_HOTFIX3_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_research_coverage_hotfix4_install.json", "R8_RESEARCH_BACKLOG_V1_6_RESEARCH_COVERAGE_HOTFIX4_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_source_grounding_hotfix5_install.json", "R8_RESEARCH_BACKLOG_V1_6_SOURCE_GROUNDING_HOTFIX5_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_serper_web_hotfix6_install.json", "R8_RESEARCH_BACKLOG_V1_6_SERPER_WEB_HOTFIX6_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_claim_trust_hotfix7_install.json", "R8_RESEARCH_BACKLOG_V1_6_CLAIM_TRUST_HOTFIX7_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_handoff_quality_hotfix8_install.json", "R8_RESEARCH_BACKLOG_V1_6_HANDOFF_QUALITY_HOTFIX8_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_direct_evidence_hotfix9_install.json", "R8_RESEARCH_BACKLOG_V1_6_DIRECT_EVIDENCE_HOTFIX9_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_facet_binding_hotfix10_install.json", "R8_RESEARCH_BACKLOG_V1_6_FACET_BINDING_HOTFIX10_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_parallel_freshness_hotfix11_install.json", "R8_RESEARCH_BACKLOG_V1_6_PARALLEL_FRESHNESS_HOTFIX11_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_parallel_freshness_hotfix11_fix1_install.json", "R8_RESEARCH_BACKLOG_V1_6_PARALLEL_FRESHNESS_HOTFIX11_FIX1_APPLIED"),
    (".signalforge_r8_research_backlog_v1_6_parallel_freshness_hotfix11_fix2_install.json", "R8_RESEARCH_BACKLOG_V1_6_PARALLEL_FRESHNESS_HOTFIX11_FIX2_APPLIED"),
)
# Backward-compatible single-receipt aliases used by acceptance tooling.
_EVIDENCE_TRUST_RECEIPT = ".signalforge_r8_research_backlog_v1_6_parallel_freshness_hotfix11_fix2_install.json"
_EVIDENCE_TRUST_RECEIPT_STATUS = "R8_RESEARCH_BACKLOG_V1_6_PARALLEL_FRESHNESS_HOTFIX11_FIX2_APPLIED"


def _evidence_trust_activation_ready(repo: str | Path) -> bool:
    """Any cumulative release that contains Evidence Trust may activate the reversible migration."""
    base = Path(repo)
    for receipt_name, expected_status in _EVIDENCE_TRUST_RECEIPTS:
        receipt = base / receipt_name
        if not receipt.exists():
            continue
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, Mapping) and _clean(data.get("status")).upper() == expected_status:
            return True
    return False


def _migrate_v16_evidence_trust(item: dict[str, Any]) -> bool:
    """Re-adjudicate stored compact evidence without deleting the old search record.

    Pre-HOTFIX3 cards are copied into evidence_trust_legacy_raw before the countable card arrays are
    replaced by trust-qualified versions.  This is intentionally reversible/auditable: search
    history remains, but old unqualified noise no longer inflates Founder evidence totals.
    """
    if _clean(item.get("evidence_trust_migration")).upper() == _EVIDENCE_TRUST_MIGRATION:
        return False
    history = [row for row in (item.get("history") or []) if isinstance(row, dict)]
    for row in history:
        job = _clean(row.get("job")).upper()
        if job not in JOB_ORDER:
            continue
        raw_backup = row.get("evidence_trust_legacy_raw")
        if not isinstance(raw_backup, Mapping):
            raw_backup = {
                history_key: copy.deepcopy(list(row.get(history_key) or []))
                for history_key in _EVIDENCE_HISTORY_KEYS.values()
            }
            row["evidence_trust_legacy_raw"] = raw_backup
        # HOTFIX7 re-adjudicates from the immutable pre-trust backup when available. This avoids
        # compounding earlier false positives/false negatives and keeps migration reversible.
        pseudo_brief = {
            "summary": {},
            "human_comments": copy.deepcopy(list(raw_backup.get("human_comments") or [])),
            "similar_products": copy.deepcopy(list(raw_backup.get("products") or [])),
            "repo_solutions": copy.deepcopy(list(raw_backup.get("repos") or [])),
            "supporting_evidence": copy.deepcopy(list(raw_backup.get("supporting") or [])),
            "counter_evidence": copy.deepcopy(list(raw_backup.get("counterevidence") or [])),
            "gaps": copy.deepcopy(list(row.get("gaps") or [])),
        }
        pseudo = {
            "status": row.get("status"),
            "research_brief": pseudo_brief,
            "research_trace": copy.deepcopy(dict(row.get("research_trace") or {})),
            "successful_sources": copy.deepcopy(list(row.get("successful_sources") or [])),
            "failed_sources": copy.deepcopy(list(row.get("failed_sources") or [])),
            "original_page_checks": copy.deepcopy(list((row.get("research_trace") or {}).get("original_page_checks") or [])) if isinstance(row.get("research_trace"), Mapping) else [],
        }
        qualified = _quality_filter_result(item, job, pseudo)
        qb = _brief(qualified)
        row["human_comments"] = [_compact_card(x) for x in (qb.get("human_comments") or []) if isinstance(x, Mapping)]
        row["products"] = [_compact_card(x) for x in (qb.get("similar_products") or []) if isinstance(x, Mapping)]
        row["repos"] = [_compact_card(x) for x in (qb.get("repo_solutions") or []) if isinstance(x, Mapping)]
        row["supporting"] = [_compact_card(x) for x in (qb.get("supporting_evidence") or []) if isinstance(x, Mapping)]
        row["counterevidence"] = [_compact_card(x) for x in (qb.get("counter_evidence") or []) if isinstance(x, Mapping)]
        row["counts"] = _counts(qualified)
        row["explicit_paid_dissatisfaction"] = _explicit_paid_dissatisfaction_cards(qualified, 6)
        row["explicit_paid_dissatisfaction_count"] = len(row["explicit_paid_dissatisfaction"])
        row["traceability_gate"] = copy.deepcopy(dict(qualified.get("traceability_gate") or {}))
        row["evidence_trust_gate"] = copy.deepcopy(dict(qualified.get("evidence_trust_gate") or {}))
        row["evidence_trust_version"] = _EVIDENCE_TRUST_VERSION

    item["evidence_trust_migration"] = _EVIDENCE_TRUST_MIGRATION
    item["evidence_trust_migrated_at"] = _now()
    item["latest_change"] = "V1_6_EVIDENCE_TRUST_REQUALIFIED"

    # A Founder opportunity that was automatically parked before the trust boundary existed gets
    # one fresh pass. Manual STOPPED remains untouched.
    status = _clean(item.get("auto_status")).upper()
    if _clean(item.get("source_kind")).upper() in CURATED_SOURCE_KINDS and status in {
        "PARKED_NO_PUBLIC_SIGNAL", "PARKED_WEAK_SIGNAL"
    }:
        item["auto_status"] = "NEW"
        item["current_call"] = "SignalForge 重新研究：舊 evidence 尚未經 trust gate"
        item["why"] = "舊版曾用未經 opportunity+lane qualification 的結果做自動暫停；history 保留，重新從 BASELINE 驗證。"
        item["next_job"] = "BASELINE"
        item["next_question"] = _next_question("BASELINE")
        item["needs_founder"] = False
        _clear_source_retry(item)

    _refresh_accumulated_state(item)

    # Existing REVIEW_READY decisions were made on raw pre-trust counts. Revalidate that terminal
    # state against the qualified evidence and required high-value lanes instead of grandfathering
    # a noisy decision forever. CURRENT_SOLUTIONS is optional when BASELINE already found solutions.
    if _clean(item.get("auto_status")).upper() == "REVIEW_READY":
        coverage = _coverage_for_item(item)
        completed = set(coverage.get("completed_jobs") or [])
        required = {"BASELINE", "PAID_DISSATISFACTION", "BUYER_PAYER_WTP", "COUNTEREVIDENCE"}
        missing = [job for job in JOB_ORDER if job in required and job not in completed]
        qualified_total = int(coverage.get("unique_evidence") or 0)
        if missing:
            item["auto_status"] = "AUTO_RESEARCH"
            item["current_call"] = "SignalForge 補跑 evidence-trust 後仍缺的研究 lane"
            item["why"] = "舊 REVIEW_READY 在 evidence trust 重算後缺少必要高價值 lane；保留 history，從最早缺口繼續。"
            item["next_job"] = missing[0]
            item["next_question"] = _next_question(missing[0])
            item["needs_founder"] = False
        elif qualified_total <= 0:
            item["auto_status"] = "PARKED_NO_PUBLIC_SIGNAL"
            item["current_call"] = "先暫停：沒有合格 evidence"
            item["why"] = "舊 REVIEW_READY 的 raw evidence 經 opportunity+lane qualification 後沒有合格材料；不再用雜訊維持需要看。"
            item["next_job"] = None
            item["needs_founder"] = False
        else:
            gate = coverage.get("review_ready_evidence_gate") if isinstance(coverage.get("review_ready_evidence_gate"), Mapping) else _review_ready_evidence_gate(coverage)
            if not bool(gate.get("passed")):
                item["auto_status"] = "PARKED_WEAK_SIGNAL"
                item["current_call"] = "弱訊號暫緩：證據組合還不夠決策"
                item["why"] = "Evidence Trust 重算後雖有合格材料，但仍缺直接問題訊號與獨立旁證的組合；完成 lanes 不再自動等於 REVIEW_READY。"
                item["next_job"] = None
                item["needs_founder"] = False
        _refresh_accumulated_state(item)

    item["updated_at"] = _now()
    return True


def load_store(repo: str | Path = ".", *, repair_worker: bool = False) -> dict[str, Any]:
    path = _store_path(repo)
    backup_path = _store_backup_path(repo)
    with _LOCK:
        if not path.exists():
            migrated = _migrate_curated_legacy_store(repo)
            if migrated is not None:
                _atomic_write(path, migrated)
                return migrated
            return _default_store()
        raw = _read_store_mapping(path)
        recovered_from_backup = False
        if raw is None:
            backup = _read_store_mapping(backup_path) if backup_path.exists() else None
            if backup is None:
                blocked = _default_store()
                blocked["storage_recovery_required"] = True
                blocked["storage_error"] = (
                    "Persistent backlog JSON is unreadable and no valid backup exists. "
                    "Writes are blocked so research history is not silently replaced."
                )
                blocked["worker"]["status"] = "STORE_RECOVERY_REQUIRED"
                blocked["worker"]["last_error"] = blocked["storage_error"]
                return blocked
            raw = backup
            recovered_from_backup = True
            raw["storage_recovered_from_backup_at"] = _now()
            raw["storage_error"] = "Primary backlog JSON was unreadable; recovered the previous valid snapshot from .bak."
            # Restore a readable primary immediately. Do not call save_store here because the
            # corrupt primary must not replace the known-good backup.
            _atomic_write(path, raw)
        version_changed = _clean(raw.get("engine_version")) != ENGINE_VERSION
        raw["engine_version"] = ENGINE_VERSION
        raw.setdefault("items", {})
        raw.setdefault("order", list((raw.get("items") or {}).keys()))
        raw.setdefault("worker", _default_store()["worker"])
        worker_defaults = _default_store()["worker"]
        worker = raw.get("worker") if isinstance(raw.get("worker"), dict) else {}
        for key, value in worker_defaults.items():
            worker.setdefault(key, copy.deepcopy(value))
        raw["worker"] = worker
        raw.setdefault("automation", _default_store()["automation"])
        automation = raw.get("automation") if isinstance(raw.get("automation"), dict) else {}
        for key, value in _default_store()["automation"].items():
            automation.setdefault(key, value)
        raw["automation"] = automation
        raw.setdefault("legacy_archive_summary", {})
        raw.setdefault("market_truth_writes", 0)
        raw.setdefault("truth_boundary", TRUTH_BOUNDARY)
        raw.pop("storage_recovery_required", None)
        migration_changed = bool(version_changed)
        items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
        routing_trust_changed = False
        for item in items.values():
            if not isinstance(item, dict):
                continue
            if _migrate_source_retry_state(item):
                migration_changed = True
            if _migrate_v16_full_founder_research(item):
                migration_changed = True
            if _migrate_v16_routing_trust(item):
                migration_changed = True
                routing_trust_changed = True
            if _evidence_trust_activation_ready(repo) and _migrate_v16_evidence_trust(item):
                migration_changed = True
        if routing_trust_changed:
            worker = raw.setdefault("worker", {})
            worker["consecutive_source_limited"] = 0
            automation = raw.setdefault("automation", {})
            automation["source_circuit_open_count"] = 0
            automation["source_circuit_retry_after"] = None
            automation["source_circuit_reason"] = None
            automation["source_circuit_last_open_at"] = None
        worker_before = copy.deepcopy(raw.get("worker"))
        if repair_worker:
            _repair_worker(raw)
        if migration_changed or raw.get("worker") != worker_before or recovered_from_backup:
            raw["updated_at"] = _now()
            _atomic_write(path, raw)
        return raw


def save_store(repo: str | Path, store: Mapping[str, Any]) -> None:
    path = _store_path(repo)
    backup_path = _store_backup_path(repo)
    with _LOCK:
        if bool(store.get("storage_recovery_required")):
            raise RuntimeError("persistent backlog store requires recovery; refusing to overwrite unreadable history")
        payload = copy.deepcopy(dict(store))
        payload["engine_version"] = ENGINE_VERSION
        payload["updated_at"] = _now()
        payload["market_truth_writes"] = 0
        payload["truth_boundary"] = TRUTH_BOUNDARY
        payload.pop("storage_recovery_required", None)
        # Keep one previous known-good snapshot. If the primary was externally corrupted, do
        # not copy those bad bytes over the backup.
        if path.exists():
            previous = _read_store_mapping(path)
            if previous is not None:
                _atomic_write(backup_path, previous)
            elif not (backup_path.exists() and _read_store_mapping(backup_path) is not None):
                raise RuntimeError("persistent backlog JSON is unreadable and no valid backup exists; refusing destructive overwrite")
        _atomic_write(path, payload)


def _context_dict(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, str):
            value = _clean(value)
        if _emptyish(value):
            continue
        out[field] = copy.deepcopy(value)
    return out


def _seed_from_candidate(row: Mapping[str, Any], rank: int) -> dict[str, Any] | None:
    candidate_id = row.get("id")
    title = _clean(row.get("title"))
    description = _clean(row.get("problem_statement") or row.get("description"))
    if candidate_id in {None, ""} or len(title) < 2:
        return None
    canonical = _clean(row.get("canonical_key")) or _slug_key(f"{title} {description}")
    item_id = f"candidate-{candidate_id}"
    source_context = _context_dict(row, (
        "actor", "actor_category", "task", "object", "failure_mode",
        "consequence", "buyer_context", "workaround",
    ))
    return {
        "id": item_id,
        "source_kind": "PROBLEM_CANDIDATE",
        "source_ref": str(candidate_id),
        "canonical_key": canonical,
        "title": title,
        "description": description,
        "import_rank": int(rank),
        "source_context": source_context,
        "legacy": {
            "stage": _clean(row.get("stage")),
            "founder_status": _clean(row.get("founder_status")),
            "market_score": row.get("market_score"),
            "confidence_score": row.get("confidence_score"),
            "community_evidence_count": row.get("community_evidence_count"),
            "community_user_count": row.get("community_user_count"),
        },
    }


def _seed_from_opportunity(row: Mapping[str, Any], rank: int) -> dict[str, Any] | None:
    opportunity_id = row.get("id")
    title = _clean(row.get("title"))
    description = _clean(row.get("problem_statement") or row.get("description"))
    if opportunity_id in {None, ""} or len(title) < 2:
        return None
    canonical = _clean(row.get("canonical_key")) or _slug_key(f"{title} {description}")
    source_context = _context_dict(row, (
        "who_has_problem", "why_now", "workarounds", "existing_solutions", "buyer_signals",
    ))
    return {
        "id": f"opportunity-{opportunity_id}",
        "source_kind": "OPPORTUNITY",
        "source_ref": str(opportunity_id),
        "canonical_key": canonical,
        "title": title,
        "description": description,
        "import_rank": int(rank),
        "source_context": source_context,
        "legacy": {
            "status": _clean(row.get("status")),
            "opportunity_score": row.get("opportunity_score"),
            "confidence_score": row.get("confidence_score"),
            "independent_users": row.get("independent_users"),
            "evidence_count": row.get("evidence_count"),
        },
    }


def _seed_from_idea(row: Mapping[str, Any], rank: int) -> dict[str, Any] | None:
    description = _clean(row.get("description") or row.get("problem") or row.get("problem_statement"))
    title = _clean(row.get("title") or row.get("name"))
    if len(title) < 2 and description:
        title = description[:160].rstrip(" .,:;|-—")
    if len(title) < 2:
        return None
    if not description:
        description = title
    canonical = _clean(row.get("canonical_key")) or _slug_key(f"{title} {description}")
    item_id = _clean(row.get("id")) or f"idea-{_sha_key(canonical or title)}"
    if not item_id.startswith(("idea-", "candidate-", "opportunity-")):
        item_id = f"idea-{_sha_key(item_id)}"
    return {
        "id": item_id,
        "source_kind": _clean(row.get("source_kind")) or "FOUNDER_OPPORTUNITY",
        "source_ref": _clean(row.get("source_ref")) or None,
        "canonical_key": canonical,
        "title": title,
        "description": description,
        "import_rank": int(rank),
        "source_context": dict(row.get("source_context") or {}) if isinstance(row.get("source_context"), Mapping) else {},
        "legacy": {},
    }

def _new_item(seed: Mapping[str, Any]) -> dict[str, Any]:
    now = _now()
    return {
        **dict(seed),
        "created_at": now,
        "updated_at": now,
        "auto_status": "NEW",
        "current_call": "尚未研究",
        "why": "已進 Backlog，等待 SignalForge 自動做第一輪市場掃描。",
        "known": [],
        "unknown": ["公開市場訊號尚未掃描。"],
        "counterevidence": [],
        "research_coverage": {"completed_jobs": [], "unique_evidence": 0, "unique_human": 0, "unique_solutions": 0, "unique_counter": 0},
        "review_priority": 0,
        "next_job": "BASELINE",
        "next_question": JOB_QUESTIONS["BASELINE"],
        "history": [],
        "source_retry_count": 0,
        "source_retry_after": None,
        "source_retry_job": None,
        "source_retry_reason": None,
        "source_last_limited_at": None,
        "latest_change": "IMPORTED",
        "needs_founder": False,
        "founder_reviewed_at": None,
        "founder_reviewed_research_count": 0,
        "founder_reviewed_handoff_hash": None,
        "market_truth_writes": 0,
    }


def _reopen_after_material_upstream_change(item: dict[str, Any], reason: str) -> bool:
    """Re-open completed/parked research when the upstream opportunity itself materially changes.

    Imported context is still UNVALIDATED. Re-opening only means the public research should be
    refreshed against the new wording/workflow clues; it does not upgrade market truth.
    """
    status = _clean(item.get("auto_status")).upper()
    if status not in {"PARKED_NO_PUBLIC_SIGNAL", "PARKED_WEAK_SIGNAL", "REVIEW_READY"}:
        return False
    history = item.get("history") if isinstance(item.get("history"), list) else []
    for entry in history:
        if isinstance(entry, dict) and not bool(entry.get("coverage_superseded", False)):
            entry["coverage_superseded"] = True
            entry["coverage_superseded_reason"] = "MATERIAL_UPSTREAM_CONTEXT_CHANGED"
    item["research_refresh_count"] = max(0, int(item.get("research_refresh_count") or 0)) + 1
    item["research_refresh_reason"] = _clean(reason)[:900]
    item["auto_status"] = "AUTO_RESEARCH"
    item["current_call"] = "上游方向有實質更新，SignalForge 重新做 baseline"
    item["why"] = _clean(reason)[:900] or "上游方向的研究脈絡有實質更新；舊研究保留，但先重新確認公開市場訊號。"
    item["next_job"] = "BASELINE"
    item["next_question"] = JOB_QUESTIONS["BASELINE"]
    item["needs_founder"] = False
    item["latest_change"] = "UPSTREAM_CONTEXT_CHANGED_RESEARCH_REOPENED"
    _clear_source_retry(item)
    return True


def sync_backlog(
    repo: str | Path,
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    opportunities: Sequence[Mapping[str, Any]] = (),
    ideas: Sequence[Mapping[str, Any]] = (),
    sync_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge explicit Founder/AI-curated opportunities into the active backlog.

    `candidates` and `opportunities` remain accepted for backward compatibility but are ignored
    as active targets. Automatic DB rows belong to the evidence/discovery layer, not the Founder
    opportunity queue. Active research targets must come from explicit `ideas`.
    """
    store = load_store(repo, repair_worker=False)
    items = store.setdefault("items", {})
    order = list(store.setdefault("order", []))
    added = 0
    refreshed = 0
    skipped_duplicate = 0
    added_ids: list[str] = []
    refreshed_ids: list[str] = []
    dirty = False

    if _clean(store.get("engine_version")) != ENGINE_VERSION:
        store["engine_version"] = ENGINE_VERSION
        dirty = True

    canonical_to_id: dict[str, str] = {}
    for item_id in order:
        item = items.get(item_id)
        if isinstance(item, Mapping):
            key = _clean(item.get("canonical_key"))
            if key:
                canonical_to_id.setdefault(key, item_id)

    seeds: list[dict[str, Any]] = []
    ignored_automatic_inputs = (
        sum(1 for row in candidates if isinstance(row, Mapping))
        + sum(1 for row in opportunities if isinstance(row, Mapping))
    )
    for offset, row in enumerate(ideas):
        if isinstance(row, Mapping):
            seed = _seed_from_idea(row, len(order) + offset)
            if seed:
                seeds.append(seed)

    for seed in seeds:
        item_id = str(seed["id"])
        canonical = _clean(seed.get("canonical_key"))
        existing = items.get(item_id)
        if isinstance(existing, dict):
            # Refresh source metadata only when bytes/values actually changed. A minute-by-minute
            # live sync over an unchanged DB must not rewrite every item's updated_at or the whole store.
            previous_canonical = _clean(existing.get("canonical_key"))
            item_changed = False
            research_context_changed = False
            for key in ("title", "description", "canonical_key", "import_rank", "legacy", "source_kind", "source_ref"):
                value = seed.get(key)
                if value is None or value == "":
                    continue
                copied = copy.deepcopy(value)
                if existing.get(key) != copied:
                    existing[key] = copied
                    item_changed = True
                    if key in {"title", "description"}:
                        research_context_changed = True

            # source_context can already contain fields merged from an Opportunity alias. Never
            # replace the whole mapping with the smaller ProblemCandidate snapshot on every sync;
            # update only meaningful incoming fields and preserve richer context from other sources.
            incoming_context = seed.get("source_context") if isinstance(seed.get("source_context"), Mapping) else {}
            merged_existing_context = dict(existing.get("source_context") or {})
            for ctx_key, ctx_value in incoming_context.items():
                if _emptyish(ctx_value):
                    continue
                copied_ctx = copy.deepcopy(ctx_value)
                if merged_existing_context.get(ctx_key) != copied_ctx:
                    merged_existing_context[ctx_key] = copied_ctx
                    item_changed = True
                    research_context_changed = True
            if merged_existing_context != dict(existing.get("source_context") or {}):
                existing["source_context"] = merged_existing_context
            refreshed_canonical = _clean(existing.get("canonical_key"))
            if previous_canonical and previous_canonical != refreshed_canonical and canonical_to_id.get(previous_canonical) == item_id:
                canonical_to_id.pop(previous_canonical, None)
            if refreshed_canonical:
                canonical_to_id[refreshed_canonical] = item_id
            if research_context_changed:
                _reopen_after_material_upstream_change(
                    existing,
                    "上游 ProblemCandidate / Opportunity 的標題、問題描述或 workflow context 有實質更新；保留舊歷史並重新確認 baseline。",
                )
            if item_changed:
                existing["updated_at"] = _now()
                refreshed += 1
                refreshed_ids.append(item_id)
                dirty = True
            continue
        duplicate_id = canonical_to_id.get(canonical) if canonical else None
        if duplicate_id and duplicate_id in items:
            # Preserve one research thread for the same canonical opportunity. Record aliases
            # and merge richer source context without rewriting accumulated research history.
            target = items[duplicate_id]
            target_changed = False
            research_context_changed = False
            aliases = target.setdefault("aliases", [])
            alias = {"id": item_id, "source_kind": seed.get("source_kind"), "source_ref": seed.get("source_ref"), "title": seed.get("title")}
            if alias not in aliases:
                aliases.append(alias)
                target_changed = True
            merged_context = dict(target.get("source_context") or {})
            for key, value in dict(seed.get("source_context") or {}).items():
                if key not in merged_context or _emptyish(merged_context.get(key)):
                    merged_context[key] = copy.deepcopy(value)
            if merged_context != dict(target.get("source_context") or {}):
                target["source_context"] = merged_context
                target_changed = True
                research_context_changed = True
            if not _clean(target.get("description")) and _clean(seed.get("description")):
                target["description"] = _clean(seed.get("description"))
                target_changed = True
                research_context_changed = True
            if research_context_changed:
                _reopen_after_material_upstream_change(
                    target,
                    "同一 canonical direction 從新的上游來源補進了 workflow / buyer / workaround context；保留舊歷史並重新確認 baseline。",
                )
            if target_changed:
                target["updated_at"] = _now()
                dirty = True
            skipped_duplicate += 1
            continue
        items[item_id] = _new_item(seed)
        order.append(item_id)
        if canonical:
            canonical_to_id[canonical] = item_id
        added += 1
        added_ids.append(item_id)
        dirty = True

    # In-place migration is non-destructive. Recompute accumulated state, but persist only when
    # the derived state actually differs; repeated live-sync polls over unchanged history stay no-op.
    for value in items.values():
        if isinstance(value, dict) and value.get("history"):
            before = {
                "research_coverage": copy.deepcopy(value.get("research_coverage")),
                "review_priority": value.get("review_priority"),
                "known": copy.deepcopy(value.get("known")),
                "unknown": copy.deepcopy(value.get("unknown")),
                "counterevidence": copy.deepcopy(value.get("counterevidence")),
            }
            _refresh_accumulated_state(value)
            after = {
                "research_coverage": value.get("research_coverage"),
                "review_priority": value.get("review_priority"),
                "known": value.get("known"),
                "unknown": value.get("unknown"),
                "counterevidence": value.get("counterevidence"),
            }
            if before != after:
                dirty = True

    if sync_metadata is not None:
        normalized_metadata = {
            "source_counts": {},
            "import_warnings": [_clean(x) for x in (sync_metadata.get("import_warnings") or []) if _clean(x)],
        }
        current_metadata = store.get("sync_metadata") if isinstance(store.get("sync_metadata"), Mapping) else {}
        current_comparable = {
            "source_counts": dict(current_metadata.get("source_counts") or {}) if isinstance(current_metadata.get("source_counts"), Mapping) else {},
            "import_warnings": list(current_metadata.get("import_warnings") or []),
        }
        if current_comparable != normalized_metadata:
            store["sync_metadata"] = normalized_metadata
            dirty = True

    store["order"] = order
    if dirty:
        automation = store.setdefault("automation", dict(_default_store()["automation"]))
        automation["last_live_sync_at"] = _now()
        save_store(repo, store)

    return {
        "status": "SYNCED",
        "added": added,
        "refreshed": refreshed,
        "merged_duplicates": skipped_duplicate,
        "added_ids": added_ids,
        "refreshed_ids": refreshed_ids,
        "ignored_automatic_inputs": ignored_automatic_inputs,
        "total": len(order),
        "persisted": dirty,
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def _brief(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = result.get("research_brief")
    return value if isinstance(value, Mapping) else {}


def _summary(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _brief(result).get("summary")
    return value if isinstance(value, Mapping) else {}


def _search(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _brief(result).get("search")
    return value if isinstance(value, Mapping) else {}


def _counts(result: Mapping[str, Any]) -> dict[str, int]:
    s = _summary(result)
    return {
        "useful": int(s.get("useful_result_count") or 0),
        "human": int(s.get("human_comment_count") or 0),
        "products": int(s.get("product_or_service_count") or 0),
        "repos": int(s.get("repo_solution_count") or 0),
        "supporting": int(s.get("supporting_evidence_count") or 0),
        "counter": int(s.get("counter_evidence_count") or 0),
    }


_PAID_CUES = (
    "paid", "paying", "we pay", "subscription", "subscribed", "license", "licence",
    "pro plan", "team plan", "enterprise plan", "purchased", "billed", "billing",
    "付費", "付款", "訂閱", "授權", "買了", "花錢", "付錢",
)
_DISSATISFACTION_CUES = (
    "still", "but still", "manual", "manually", "cancel", "switch", "switching",
    "frustrat", "noise", "false positive", "not worth", "doesn't", "does not", "don't",
    "workaround", "rework", "slow", "仍然", "還是", "手動", "取消", "換工具", "不值得", "返工",
)


def _contains_any(text: str, cues: Sequence[str]) -> bool:
    low = _clean(text).lower()
    return any(cue in low for cue in cues)


def _explicit_paid_dissatisfaction_cards(result: Mapping[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    """Conservative routing signal: human trace must mention both pay/investment and unresolved friction."""
    rows = _brief(result).get("human_comments")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        text = f"{row.get('title')} {row.get('excerpt')}"
        if _contains_any(text, _PAID_CUES) and _contains_any(text, _DISSATISFACTION_CUES):
            out.append(_compact_card(row))
            if len(out) >= limit:
                break
    return out


def _baseline_is_weak_single_trace(result: Mapping[str, Any]) -> bool:
    counts = _counts(result)
    solutions = counts["products"] + counts["repos"]
    return counts["useful"] == 1 and counts["human"] == 0 and counts["supporting"] == 0 and solutions <= 1


def _research_transport_limited(result: Mapping[str, Any]) -> bool:
    status = _clean(result.get("status")).upper()
    successful = _successful_sources(result)
    failed = _failed_sources(result)
    return status == "SEARCH_FAILED" or (not successful and bool(failed))


def _negative_decision_coverage_limited(result: Mapping[str, Any]) -> bool:
    """Return True when missing evidence is unsafe to interpret as a negative signal.

    ResearchCoverage HOTFIX4 closes the last cross-domain trust hole: specialist communities
    such as HN/GitHub/StackOverflow can produce excellent positive traces, but their silence does
    not prove that an arbitrary SMB/consumer/education market is empty.  A negative/PARK/finish
    decision therefore requires at least one mature general-web provider (Serper, Tavily, or Brave), plus
    enough healthy coverage to avoid converting outages into market conclusions.
    """
    status = _clean(result.get("status")).upper()
    successful = _successful_sources(result)
    failed = _failed_sources(result)
    unique_successful = {_clean(source).upper() for source in successful if _clean(source)}
    general_web = bool(unique_successful & {"SERPER_WEB_SEARCH", "TAVILY_WEB_SEARCH", "BRAVE_WEB_SEARCH"})
    if status == "SEARCH_FAILED" or (not unique_successful and failed):
        return True
    if not general_web:
        return True
    return bool(failed) and len(unique_successful) < 2


def _rank_value(value: Any, default: int = 10**9) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


_RELEVANCE_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "could", "does", "doing",
    "fail", "fails", "failed", "failure", "issue", "issues", "problem", "problems", "thing", "things",
    "from", "have", "into", "just", "more", "most", "need", "needs", "other", "over", "same", "some",
    "than", "that", "their", "them", "then", "there", "these", "they", "this", "those", "through",
    "tool", "tools", "software", "system", "systems", "user", "users", "using", "with", "without", "would",
    "market", "solution", "solutions", "product", "products", "people", "workflow", "workflows", "work",
    "and", "for", "can", "why", "none", "artificial", "intelligence", "generative", "model", "models", "llm", "llms", "ai",
}

_RELEVANCE_EXPANSIONS: dict[str, set[str]] = {
    "context": {"memory", "remember", "forget", "forgot", "state"},
    "retain": {"remember", "memory", "persist", "persistent"},
    "instruction": {"instructions", "rules", "prompt", "prompts", "directive", "directives"},
    "instructions": {"instruction", "rules", "prompt", "prompts", "directive", "directives", "guardrail", "guardrails"},
    "rule": {"rules", "instruction", "instructions", "prompt", "guardrail", "guardrails"},
    "rules": {"rule", "instruction", "instructions", "prompt", "guardrail", "guardrails"},
    "memory": {"remember", "forget", "forgot", "amnesia", "context", "persist", "persistent"},
    "session": {"sessions", "amnesia", "context", "memory"},
    "amnesia": {"session", "memory", "forget", "context"},
    "credit": {"credits", "remaining", "balance"},
    "credits": {"credit", "remaining", "balance"},
    "attendance": {"absence", "absent", "makeup", "reschedule"},
    "booking": {"schedule", "scheduling", "appointment", "appointments", "reservation"},
    "scheduling": {"schedule", "booking", "appointment", "appointments"},
}


def _term_stem(token: str) -> str:
    value = token.lower().strip("-_ ")
    if len(value) > 5 and value.endswith("ies"):
        value = value[:-3] + "y"
    elif len(value) > 5 and value.endswith("ing"):
        value = value[:-3]
    elif len(value) > 4 and value.endswith("ed"):
        value = value[:-2]
    elif len(value) > 4 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]
    return value


def _latin_relevance_terms(text: Any) -> set[str]:
    raw = _clean(text).lower()
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", raw)
    out: set[str] = set()
    for token in tokens:
        stem = _term_stem(token)
        if len(stem) < 3 or stem in _RELEVANCE_STOPWORDS:
            continue
        out.add(stem)
        for extra in _RELEVANCE_EXPANSIONS.get(stem, set()):
            extra_stem = _term_stem(extra)
            if extra_stem and extra_stem not in _RELEVANCE_STOPWORDS:
                out.add(extra_stem)
    return out


def _latin_literal_terms(text: Any) -> set[str]:
    """Literal evidence-side terms with no synonym expansion.

    Query/thesis expansion is useful for retrieval recall, but using those same expansions on a
    candidate card manufactures evidence that the source never said.  For example, the word
    "context" used to expand into "forget/amnesia/memory", which let an unrelated llama.cpp context
    window answer look like session-amnesia evidence.  Trust adjudication therefore expands only
    the thesis/query side and keeps source-card terms literal.
    """
    raw = _clean(text).lower()
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", raw)
    out: set[str] = set()
    for token in tokens:
        stem = _term_stem(token)
        if len(stem) < 3 or stem in _RELEVANCE_STOPWORDS:
            continue
        out.add(stem)
    return out


def _baseline_relevance_terms(item: Mapping[str, Any]) -> set[str]:
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    context_text = " ".join(
        _clean(value)
        for key, value in context.items()
        if key in {"actor", "task", "object", "failure_mode", "consequence", "workaround"} and not _emptyish(value)
    )
    return _latin_relevance_terms(f"{item.get('title')} {item.get('description')} {context_text}")


def _baseline_card_is_relevant(row: Mapping[str, Any], idea_terms: set[str]) -> bool:
    # For non-English / very short ideas, keep the upstream FIX5 behavior rather than inventing a
    # brittle lexical veto. The deterministic gate is only used when the Founder idea provides
    # enough distinctive Latin terms to make an objective overlap check meaningful.
    if len(idea_terms) < 3:
        return True
    card_terms = _latin_literal_terms(
        f"{row.get('title')} {row.get('excerpt')} {row.get('solution_type')} {row.get('match_level')}"
    )
    overlap = idea_terms & card_terms
    if len(overlap) >= 2:
        return True
    match_level = _clean(row.get("match_level")).lower()
    if len(overlap) == 1 and any(marker in match_level for marker in ("exact", "direct", "strong")):
        return True
    return False



# Evidence Trust HOTFIX3 deliberately reuses the older SignalForge U17/U18 adjudication contract:
# evidence must match BOTH the Founder opportunity and the atomic research lane.  The production
# backlog remains deterministic/no-extra-LLM by default; ambiguous material is preserved in the
# trust audit but is not allowed to inflate counts or advance REVIEW_READY.
_EVIDENCE_TRUST_VERSION = "V1_6_FACET_BINDING_HOTFIX10"
_EVIDENCE_LANE_KEYS = (
    "human_comments",
    "similar_products",
    "repo_solutions",
    "supporting_evidence",
    "counter_evidence",
)
_EVIDENCE_HISTORY_KEYS = {
    "human_comments": "human_comments",
    "similar_products": "products",
    "repo_solutions": "repos",
    "supporting_evidence": "supporting",
    "counter_evidence": "counterevidence",
}
_EVIDENCE_LANE_GENERIC_TERMS = {
    "baseline", "current", "solution", "supply", "paid", "pay", "payer", "buyer", "buy",
    "pricing", "price", "spend", "budget", "purchase", "payment", "wtp", "willing", "counter",
    "counterevidence", "falsify", "evidence", "research", "focus", "reality", "dissatisfaction",
    "public", "market", "software", "product", "service", "tool", "repo", "github", "user", "users",
    "team", "teams", "workflow", "workflows", "business", "small", "existing", "alternative",
    "subscription", "subscribed", "billing", "billed", "plan", "monthly", "annual", "enterprise",
    "cost", "dollar", "dollars", "solved", "solve", "already", "native", "built", "included",
    "rare", "fixed", "resolved", "workaround", "adoption", "adopt", "switching", "switch",
}

# Deep-lane evidence needs more than ecosystem/entity overlap.  These generic actor/brand/category
# tokens are useful for retrieval but cannot prove that a result discusses the SAME atomic pain.
# This is a lightweight deterministic first-stage guard; ambiguous candidates remain auditable and
# can later be benchmarked against a mature CrossEncoder/NLI verifier without changing workflow.
_ATOMIC_PROBLEM_GENERIC_TERMS = _EVIDENCE_LANE_GENERIC_TERMS | {
    "agent", "agents", "coding", "code", "cod", "coder", "developer", "developers", "vibe", "claude", "cursor",
    "codex", "gemini", "copilot", "anthropic", "openai", "mcp", "api", "cli", "app", "apps",
    "excel", "google", "line", "saas", "crm", "studio", "studios", "class", "classes", "course",
    "courses", "tutor", "tutoring", "lesson", "lessons", "education", "academy", "coach", "coaching",
}

# Phrases, not loose substrings.  In HOTFIX6 the single word `native` falsely promoted Git-worktree
# tooling as counterevidence.  Counterevidence now requires an explicit claim that the atomic pain is
# solved/tolerable/rare/bundled or no longer important.
_COUNTER_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(?:problem|issue|pain)\s+(?:is|was|has been)\s+(?:solved|resolved|fixed)\b",
    r"\b(?:solved|resolved|fixed)\s+(?:this|that|the)\s+(?:problem|issue|pain)\b",
    r"\bno longer (?:a )?(?:problem|issue|pain|need)\b",
    r"\b(?:works fine|works well|good enough)\b",
    r"\b(?:do not|don['’]t) need\b",
    r"\bnot needed\b",
    r"\b(?:built[ -]?in|native) (?:support|memory|context|rules?|feature|capability)\b",
    r"\balready (?:handles|supports|solves|persists|remembers)\b",
    r"\bnot worth (?:building|buying|paying|switching|solving)\b",
    r"\b(?:rare|obsolete|disappearing) (?:problem|issue|pain|need)\b",
    r"(?:已經?|早已)(?:解決|處理|內建|支援)",
    r"(?:不再|已不)(?:是問題|需要|困擾)",
    r"(?:夠用|原生支援|內建支援)",
))
_BUYER_MONEY_CUES = (
    "paid", "paying", "we pay", "i pay", "subscription", "subscribed", "purchase", "purchased",
    "spend", "spent", "budget", "billed", "billing", "license", "licence", "pricing", "price",
    "per month", "/month", "/mo", "monthly", "annual", "per year", "/year", "enterprise plan",
    "team plan", "pro plan", "付費", "付款", "付錢", "訂閱", "購買", "買了", "花錢", "預算", "價格", "月費", "年費",
)
_WTP_CUES = (
    "willing to pay", "would pay", "i'd pay", "i would pay", "we would pay", "worth paying",
    "願意付", "願意花", "可以付", "願付",
)
# Generic words such as `subscription` or `pricing` only prove that *something* costs money.
# They do not prove willingness to pay for the atomic pain being researched.  Buyer/Payer/WTP
# therefore requires either an amount/WTP statement or explicit purchase/spend behaviour.
_BUYER_BEHAVIOR_CUES = (
    "we pay", "i pay", "we paid", "i paid", "paid for", "paying for", "purchased", "purchase of",
    "bought", "we spend", "i spend", "spent on", "budget approved", "approved budget", "procurement",
    "renewed", "renewal", "switched to", "migrated to", "upgraded to",
    "我們付", "我付", "已付費", "付錢買", "購買了", "採購", "核准預算", "換到", "升級到",
)
_SOLUTION_CUES = (
    "workaround", "we use", "i use", "using", "switched to", "migrated to", "solves", "solve",
    "handles", "automates", "automation", "plugin", "extension", "service", "platform", "repo",
    "open source", "built", "implemented", "解法", "替代", "改用", "使用", "自動", "工具", "系統",
)
_COUNTER_STRONG_CUES = (
    "solved", "resolved", "fixed", "no longer", "not a problem", "isn't a problem", "rare",
    "works fine", "works well", "good enough", "don't need", "do not need", "not needed",
    "built in", "built-in", "native", "included", "already handles", "already supports",
    "not worth", "cheap to tolerate", "easy workaround", "obsolete", "disappearing",
    "已解決", "解掉", "不再需要", "不是問題", "很少發生", "夠用", "內建", "原生支援", "已包含", "不值得",
)
_AMOUNT_RE = re.compile(
    r"(?i)(?:[$€£¥]\s?\d|(?:USD|US\$|TWD|NT\$|EUR|GBP|JPY)\s?\d|"
    r"\d+(?:\.\d+)?\s?(?:usd|dollars?|per\s+month|/month|/mo|monthly|per\s+year|/year|元|美元|台幣))"
)

# Some technical nouns are too polysemous to prove the *same* pain on their own. Real HOTFIX8
# acceptance exposed this with llama.cpp/model-memory answers and generic context-window tooling:
# they shared "context"/"memory" tokens but did not discuss forgotten project rules or cross-session
# state. A direct-evidence match therefore needs at least one non-ambiguous atomic anchor whenever
# enough anchors are available. This is still deterministic and domain-agnostic: the set only
# contains broadly overloaded infrastructure words, not product/market-specific keywords.
_AMBIGUOUS_ATOMIC_ANCHORS = {
    "context", "memory", "state", "file", "comment", "readme", "prompt",
}

# Common paraphrases of losing continuity / having to redo work.  These are intentionally phrase
# level rather than synonym-expanding every evidence token: the source must literally express a
# continuity/rework symptom before the phrase can strengthen an otherwise ambiguous anchor match.
_DIRECT_PAIN_RESTATEMENT_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\bforget(?:s|ting|ten)?\b",
    r"\bforgot(?:ten)?\b",
    r"\bamnesia\b",
    r"\blos(?:e|es|ing|t) (?:the )?(?:thread|context|state|history|instructions?|rules?)\b",
    r"\bstart(?:s|ed|ing)? (?:all )?over\b",
    r"\bstart(?:s|ed|ing)? from scratch\b",
    r"\bre[- ]?explain(?:s|ed|ing)?\b",
    r"\brepeat(?:s|ed|ing)? (?:the )?(?:same )?(?:instructions?|rules?|context|work)\b",
    r"\bremind(?:s|ed|ing)? (?:it|the agent|them) again\b",
    r"\brework\b",
    r"\bredo\b",
    r"\brediscover(?:s|ed|ing)?\b",
    r"\bdrift(?:s|ed|ing)? (?:away|outside)\b",
))

# HOTFIX10: atomic relevance must bind the evidence to the *role + workflow/pain*, not merely to
# a broad industry/topic word.  Real 199-opportunity production runs exposed false positives such
# as hard-drive warranty/RMA discussions being counted as repair-shop reimbursement pain, and
# generic construction/environmental-review comments being counted as subcontractor change-order
# evidence.  Imported Founder hypotheses already carry structured actor/task/failure/consequence
# context.  We use those facets deterministically and keep raw cards in the audit when rejected.
_FACET_GENERIC_TERMS = _ATOMIC_PROBLEM_GENERIC_TERMS | {
    "owner", "owners", "manager", "managers", "lead", "leader", "staff", "worker", "workers",
    "employee", "employees", "people", "person", "company", "companies", "customer", "customers",
    "client", "clients", "provider", "providers", "operator", "operators", "business", "businesses",
    "independent", "specialized", "specialist", "professional", "professionals", "project", "projects",
    "process", "processes", "task", "tasks", "work", "working", "manual", "review", "check", "verification",
}


def _facet_terms(text: Any) -> set[str]:
    terms = _latin_relevance_terms(text)
    terms.difference_update(_FACET_GENERIC_TERMS)
    return terms


def _structured_problem_facets(item: Mapping[str, Any]) -> dict[str, set[str]]:
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    if not context:
        return {}
    actor_text = " ".join(_clean(context.get(key)) for key in ("actor", "buyer_context") if not _emptyish(context.get(key)))
    pain_text = " ".join(_clean(context.get(key)) for key in ("task", "failure_mode", "consequence") if not _emptyish(context.get(key)))
    workaround_text = _clean(context.get("workaround"))
    description = _clean(item.get("description"))
    title = _clean(item.get("title"))

    actor_terms = _facet_terms(actor_text)
    pain_terms = _facet_terms(f"{pain_text} {description}")
    workaround_terms = _facet_terms(workaround_text)
    title_terms = _facet_terms(title)
    context_specific = set(pain_terms | workaround_terms)
    context_specific.difference_update(title_terms)
    return {
        "actor": actor_terms,
        "pain": pain_terms,
        "workaround": workaround_terms,
        "title": title_terms,
        "context_specific": context_specific,
    }


def _structured_facet_match(item: Mapping[str, Any], row: Mapping[str, Any], lane_key: str) -> dict[str, Any]:
    facets = _structured_problem_facets(item)
    if not facets:
        return {"passed": True, "basis": "NO_STRUCTURED_FACETS_FALLBACK"}
    actor_terms = facets.get("actor", set())
    pain_terms = facets.get("pain", set())
    specific_terms = facets.get("context_specific", set())
    # If the imported context contains too little English/translated material for a deterministic
    # role/workflow check, preserve the HOTFIX9 atomic boundary instead of inventing a rejection.
    if len(pain_terms) < 2 or (not actor_terms and not specific_terms):
        return {
            "passed": True,
            "basis": "INSUFFICIENT_STRUCTURED_FACETS_FALLBACK",
            "actor_terms": sorted(actor_terms)[:16],
            "pain_terms": sorted(pain_terms)[:20],
            "context_specific_terms": sorted(specific_terms)[:20],
        }

    card_terms = _latin_literal_terms(_evidence_card_text(row))
    actor_overlap = sorted(actor_terms & card_terms)
    pain_overlap = sorted(pain_terms & card_terms)
    specific_overlap = sorted(specific_terms & card_terms)

    # Human/problem/counter/solution evidence must bind across facets.  A card is not direct evidence
    # just because it says "warranty" or "construction".  It must also connect to the relevant actor
    # or to a context-specific workflow/failure term. Supporting pages are allowed a slightly looser
    # workflow-existence path, but they never become human problem evidence.
    if lane_key == "supporting_evidence":
        passed = bool(
            (actor_overlap and pain_overlap)
            or (specific_overlap and pain_overlap)
            or len(specific_overlap) >= 2
        )
        basis = "STRUCTURED_SUPPORTING_WORKFLOW_BINDING"
    else:
        passed = bool(
            (actor_overlap and pain_overlap)
            or (specific_overlap and len(pain_overlap) >= 2)
            or len(specific_overlap) >= 2
        )
        basis = "STRUCTURED_ACTOR_PAIN_BINDING"

    return {
        "passed": passed,
        "basis": basis,
        "actor_terms": sorted(actor_terms)[:16],
        "pain_terms": sorted(pain_terms)[:20],
        "context_specific_terms": sorted(specific_terms)[:20],
        "actor_overlap": actor_overlap[:12],
        "pain_overlap": pain_overlap[:16],
        "context_specific_overlap": specific_overlap[:16],
    }


def _evidence_card_text(row: Mapping[str, Any]) -> str:
    return _clean(
        f"{row.get('title')} {row.get('excerpt')} {row.get('solution_type')} "
        f"{row.get('match_level')} {row.get('source')}"
    )


def _subject_terms_for_result(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> set[str]:
    """Build thesis/object terms from queries that actually executed, not from generic lane labels.

    This mirrors the old U18 thesis-conditioned evidence idea: payment/counter/adoption words never
    establish semantic match by themselves.  Executed query terms matter especially for Chinese
    Founder ideas whose V1.6 query bridge already produced bounded English market terms.
    """
    trace = _result_research_trace(result)
    queries: list[str] = []
    expected = f"LANE_FOCUS_{_clean(job).upper()}"
    runs = [x for x in (trace.get("query_runs") or []) if isinstance(x, Mapping)]
    for run in runs:
        label = _clean(run.get("label")).upper()
        if label == expected:
            queries.append(_clean(run.get("retrieval_query")))
    queries.extend([
        _clean(trace.get("retrieval_query")),
        _clean(trace.get("relevance_query")),
    ])
    # Public floor often carries useful translated object/mechanism terms for non-English ideas.
    for run in runs:
        label = _clean(run.get("label")).upper()
        if label in {"PRIMARY", "PUBLIC_DISCOVERY_FLOOR"}:
            queries.append(_clean(run.get("retrieval_query")))

    terms: set[str] = set()
    for query in queries:
        if query:
            terms.update(_latin_relevance_terms(query))
    terms.difference_update(_EVIDENCE_LANE_GENERIC_TERMS)
    if len(terms) < 4:
        terms.update(_baseline_relevance_terms(item))
        terms.difference_update(_EVIDENCE_LANE_GENERIC_TERMS)
    return terms


def _problem_anchor_terms(item: Mapping[str, Any], result: Mapping[str, Any]) -> set[str]:
    trace = _result_research_trace(result)
    terms: set[str] = set()
    # The relevance query is intentionally compact and is the best available deterministic proxy
    # for the atomic pain. Founder text and executed queries then add synonyms/mechanism terms.
    for text in (
        _clean(trace.get("relevance_query")),
        _clean(item.get("title")),
        _clean(item.get("description")),
    ):
        if text:
            terms.update(_latin_relevance_terms(text))
    for run in (trace.get("query_runs") or []):
        if not isinstance(run, Mapping):
            continue
        label = _clean(run.get("label")).upper()
        if label in {"PRIMARY", "GENERAL_WEB", "PUBLIC_DISCOVERY_FLOOR"}:
            terms.update(_latin_relevance_terms(run.get("retrieval_query")))
    terms.difference_update(_ATOMIC_PROBLEM_GENERIC_TERMS)
    return terms


def _atomic_problem_match(item: Mapping[str, Any], result: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    anchors = _problem_anchor_terms(item, result)
    card_terms = _latin_literal_terms(_evidence_card_text(row))
    overlap = sorted(anchors & card_terms)
    # When we genuinely do not have enough Latin/translated anchors, do not pretend lexical
    # certainty. The upstream opportunity gate remains authoritative and the trace stays auditable.
    if len(anchors) < 2:
        return {
            "passed": True,
            "anchor_terms": sorted(anchors)[:24],
            "anchor_overlap": overlap[:16],
            "strong_anchor_overlap": [],
            "basis": "INSUFFICIENT_ATOMIC_ANCHORS_FALLBACK",
        }
    # One mechanism anchor is enough for small hypotheses; broader hypotheses need two total.
    # HOTFIX9 additionally requires at least one *non-ambiguous* anchor. Words such as
    # "context"/"memory"/"state" are common across unrelated technical topics and caused real
    # Founder-visible false positives even after HOTFIX8. They may support a match, but cannot be
    # the only reason a card is called evidence for the same pain.
    required = 1 if len(anchors) <= 5 else 2
    strong_overlap = sorted((anchors - _AMBIGUOUS_ATOMIC_ANCHORS) & card_terms)
    literal_text = _evidence_card_text(row)
    direct_restatement = any(pattern.search(literal_text) for pattern in _DIRECT_PAIN_RESTATEMENT_PATTERNS)
    passed = (
        (len(overlap) >= required and bool(strong_overlap))
        or (len(overlap) >= 1 and direct_restatement)
    )
    return {
        "passed": passed,
        "anchor_terms": sorted(anchors)[:24],
        "anchor_overlap": overlap[:16],
        "strong_anchor_overlap": strong_overlap[:16],
        "direct_pain_restatement": direct_restatement,
        "required": required,
        "basis": "ATOMIC_PROBLEM_ANCHORS_WITH_DIRECT_SIGNAL",
    }


def _counter_claim_present(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _COUNTER_PATTERNS)


def _core_opportunity_match(
    item: Mapping[str, Any],
    job: str,
    result: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, Any]:
    subject = _subject_terms_for_result(item, job, result)
    card_terms = _latin_literal_terms(_evidence_card_text(row))
    overlap = sorted(subject & card_terms)
    if len(subject) >= 4:
        denominator = max(1, min(len(subject), 10))
        ratio = len(overlap) / denominator
        passed = len(overlap) >= 3 or (len(overlap) >= 2 and ratio >= 0.34)
        if not passed:
            # Broad retrieval queries can dilute a genuinely direct card.  Structured Founder
            # facets provide a safer rescue path than lowering the lexical threshold globally:
            # the card must bind to actor/workflow/pain, not merely share topic words.
            facet_rescue = _structured_facet_match(item, row, "human_comments")
            if facet_rescue.get("passed") and facet_rescue.get("basis") == "STRUCTURED_ACTOR_PAIN_BINDING":
                return {
                    "passed": True,
                    "subject_terms": sorted(subject)[:24],
                    "subject_overlap": overlap[:16],
                    "overlap_ratio": round(ratio, 3),
                    "basis": "STRUCTURED_FACET_THESIS_RESCUE",
                }
        return {
            "passed": passed,
            "subject_terms": sorted(subject)[:24],
            "subject_overlap": overlap[:16],
            "overlap_ratio": round(ratio, 3),
            "basis": "EXECUTED_QUERY_THESIS_CONTEXT",
        }

    idea_terms = _baseline_relevance_terms(item)
    if len(idea_terms) >= 3:
        passed = _baseline_card_is_relevant(row, idea_terms)
        overlap = sorted(idea_terms & card_terms)
        return {
            "passed": passed,
            "subject_terms": sorted(idea_terms)[:24],
            "subject_overlap": overlap[:16],
            "overlap_ratio": round(len(overlap) / max(1, min(len(idea_terms), 10)), 3),
            "basis": "FOUNDER_TEXT_FALLBACK",
        }

    return {
        "passed": False,
        "subject_terms": sorted(subject)[:24],
        "subject_overlap": overlap[:16],
        "overlap_ratio": 0.0,
        "basis": "INSUFFICIENT_THESIS_CONTEXT",
    }


def _lane_contract(job: str, lane_key: str, row: Mapping[str, Any]) -> tuple[bool, str, str]:
    job = _clean(job).upper()
    text = _evidence_card_text(row).lower()
    # Upstream source classification is not trusted by itself. A card labeled counterevidence must
    # actually weaken the thesis even during BASELINE; this blocks cases such as Git-wt being
    # promoted to counterevidence merely because it is an adjacent AI-coding tool.
    if lane_key == "counter_evidence":
        if _counter_claim_present(text):
            return True, "DIRECT_FALSIFICATION_CUE", "Relevant trace directly weakens the opportunity thesis."
        return False, "NO_FALSIFICATION_CLAIM", "Counterevidence label without an actual falsification claim does not count."
    if job == "BASELINE":
        return True, "BASELINE_RELEVANT", "Opportunity match is sufficient for baseline evidence."
    if job == "CURRENT_SOLUTIONS":
        if lane_key in {"similar_products", "repo_solutions"}:
            return True, "DIRECT_SOLUTION_OBJECT", "Relevant product/service/repo is solution-supply evidence."
        if _contains_any(text, _SOLUTION_CUES):
            return True, "WORKAROUND_OR_SOLUTION_CUE", "Relevant human/supporting trace describes a workaround or solution."
        return False, "NO_SOLUTION_BEHAVIOR", "Relevant to the opportunity, but does not show a current solution/workaround."
    if job == "PAID_DISSATISFACTION":
        if _contains_any(text, _PAID_CUES) and _contains_any(text, _DISSATISFACTION_CUES):
            return True, "PAID_PLUS_UNRESOLVED_FRICTION", "Explicit paid/invested cue and unresolved friction appear in the same relevant trace."
        return False, "NO_DIRECT_PAID_PLUS_FRICTION", "Paid dissatisfaction requires both explicit paid/invested and unresolved-friction evidence."
    if job == "BUYER_PAYER_WTP":
        amount = bool(_AMOUNT_RE.search(text))
        wtp = _contains_any(text, _WTP_CUES)
        buyer_behavior = _contains_any(text, _BUYER_BEHAVIOR_CUES)
        solution_price = amount and (
            lane_key in {"similar_products", "repo_solutions"}
            or _contains_any(text, _SOLUTION_CUES)
        )
        if wtp:
            return True, "EXPLICIT_WTP", "Relevant trace explicitly states willingness to pay for the same atomic pain."
        if buyer_behavior:
            return True, "EXPLICIT_PURCHASE_OR_SPEND_BEHAVIOR", "Relevant trace states concrete purchase/spend/switching behaviour for the same atomic pain."
        if solution_price:
            return True, "EXPLICIT_SAME_PAIN_SOLUTION_PRICE", "A same-pain solution/product has an explicit monetary amount; this is a price signal, not inferred willingness to pay."
        return False, "NO_DIRECT_BUYER_PAYMENT_WTP", "A generic subscription, quota complaint, or unrelated price is not buyer/WTP evidence. Count only explicit WTP, concrete purchase/spend/switching, or an explicit price attached to a same-pain solution."
    if job == "COUNTEREVIDENCE":
        if _counter_claim_present(text):
            return True, "DIRECT_FALSIFICATION_CUE", "Relevant trace directly says the problem is solved/tolerable/rare/bundled or no longer important."
        return False, "NO_FALSIFICATION_CLAIM", "A relevant adjacent tool/product is not counterevidence unless it actually weakens the opportunity thesis."
    return True, "GENERIC_RELEVANT", "No additional lane contract."


def _normalize_evidence_text(row: Mapping[str, Any]) -> str:
    raw = _clean(f"{row.get('title')} {row.get('excerpt')}").lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", raw).strip()


def _canonical_evidence_url(value: Any) -> str:
    url = _traceable_url(value)
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in tracking]
        normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query, doseq=True), ""))
        return normalized.lower()
    except Exception:
        return url.lower().split("#", 1)[0].rstrip("/")


def _near_duplicate_rows(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    lu = _canonical_evidence_url(left.get("url"))
    ru = _canonical_evidence_url(right.get("url"))
    if lu and ru and lu == ru:
        return True
    lt = _normalize_evidence_text(left)
    rt = _normalize_evidence_text(right)
    if not lt or not rt:
        return False
    if lt == rt:
        return True
    # Cross-posts often change only the title while reusing the same body.  SequenceMatcher is a
    # mature stdlib implementation; candidate sets here are small, so quadratic comparison is safe.
    if min(len(lt), len(rt)) >= 140:
        ratio = difflib.SequenceMatcher(None, lt[:1800], rt[:1800], autojunk=False).ratio()
        if ratio >= 0.90:
            return True
    return False


def _trust_summary_card(row: Mapping[str, Any], *, lane: str, verdict: str, reason: str) -> dict[str, Any]:
    return {
        "lane": lane,
        "source": _clean(row.get("source")),
        "title": _clean(row.get("title"))[:240],
        "excerpt": _clean(row.get("excerpt"))[:700],
        "url": _traceable_url(row.get("url")) or None,
        "verdict": verdict,
        "reason": reason[:360],
    }


def _evidence_trust_filter_result(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else None
    if not isinstance(brief, Mapping):
        return result
    filtered = copy.deepcopy(dict(result))
    fb = filtered.get("research_brief")
    if not isinstance(fb, dict):
        return result

    before: dict[str, int] = {}
    after: dict[str, int] = {}
    rejected: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []
    duplicate_count = 0

    for lane_key in _EVIDENCE_LANE_KEYS:
        rows = fb.get(lane_key)
        if not isinstance(rows, list):
            continue
        before[lane_key] = len(rows)
        kept: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            core = _core_opportunity_match(item, job, filtered, row)
            if not core.get("passed"):
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="MISMATCH",
                    reason=(
                        "Opportunity/thesis mismatch; overlap="
                        + ",".join(core.get("subject_overlap") or [])
                        + f" basis={core.get('basis')}"
                    ),
                ))
                continue
            atomic = _atomic_problem_match(item, filtered, row)
            # HOTFIX8 closes the last handoff-quality hole exposed by real opportunities: BASELINE
            # used to accept ecosystem-adjacent products (for example an AI debugger) even when they
            # did not discuss the Founder pain.  The same atomic-pain boundary now applies to every
            # lane.  When translated/Latin anchors are genuinely unavailable, _atomic_problem_match
            # keeps the auditable fallback rather than inventing a negative.
            if not atomic.get("passed"):
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="SAME_ECOSYSTEM_DIFFERENT_PROBLEM",
                    reason=(
                        "Same product/ecosystem but not the atomic pain; anchor overlap="
                        + ",".join(atomic.get("anchor_overlap") or [])
                    ),
                ))
                continue
            facet = _structured_facet_match(item, row, lane_key)
            if not facet.get("passed"):
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="TOPIC_MATCH_WITHOUT_ROLE_WORKFLOW_BINDING",
                    reason=(
                        "Topic/industry overlap did not bind to the Founder actor + workflow/pain; "
                        "actor=" + ",".join(facet.get("actor_overlap") or [])
                        + " pain=" + ",".join(facet.get("pain_overlap") or [])
                        + " specific=" + ",".join(facet.get("context_specific_overlap") or [])
                    ),
                ))
                continue
            lane_ok, lane_code, lane_reason = _lane_contract(job, lane_key, row)
            if not lane_ok:
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="RELATED_BUT_NOT_EVIDENCE",
                    reason=lane_reason,
                ))
                continue
            duplicate_of = next((prior for prior in accepted_rows if _near_duplicate_rows(prior, row)), None)
            if duplicate_of is not None:
                duplicate_count += 1
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="DEPENDENT_DUPLICATE",
                    reason=f"Near-duplicate of already accepted evidence: {_clean(duplicate_of.get('title'))[:160]}",
                ))
                continue
            row["evidence_trust"] = {
                "version": _EVIDENCE_TRUST_VERSION,
                "verdict": "QUALIFIED",
                "thesis_match": "MATCH",
                "lane_match": lane_code,
                "subject_overlap": list(core.get("subject_overlap") or [])[:16],
                "overlap_ratio": core.get("overlap_ratio"),
                "basis": core.get("basis"),
                "atomic_problem_match": atomic.get("basis"),
                "atomic_anchor_overlap": list(atomic.get("anchor_overlap") or [])[:16],
                "atomic_strong_anchor_overlap": list(atomic.get("strong_anchor_overlap") or [])[:16],
                "atomic_direct_pain_restatement": bool(atomic.get("direct_pain_restatement")),
                "facet_binding": facet.get("basis"),
                "facet_actor_overlap": list(facet.get("actor_overlap") or [])[:12],
                "facet_pain_overlap": list(facet.get("pain_overlap") or [])[:16],
                "facet_context_specific_overlap": list(facet.get("context_specific_overlap") or [])[:16],
                "source_grounding": copy.deepcopy(dict(row.get("source_grounding") or {})) if isinstance(row.get("source_grounding"), Mapping) else {},
                "rationale": lane_reason[:360],
            }
            kept.append(row)
            accepted_rows.append(row)
        fb[lane_key] = kept
        after[lane_key] = len(kept)

    if _clean(job).upper() == "COUNTEREVIDENCE":
        direct_counter: list[dict[str, Any]] = []
        for key in _EVIDENCE_LANE_KEYS:
            for row in (fb.get(key) or []):
                if isinstance(row, Mapping):
                    direct_counter.append(dict(row))
        for key in _EVIDENCE_LANE_KEYS:
            fb[key] = []
        fb["counter_evidence"] = direct_counter
        after = {key: len(fb.get(key) or []) for key in _EVIDENCE_LANE_KEYS}

    _recount_brief_summary(fb)
    filtered["evidence_trust_gate"] = {
        "version": _EVIDENCE_TRUST_VERSION,
        "status": "THESIS_AND_LANE_QUALIFIED",
        "job": _clean(job).upper(),
        "before": before,
        "after": after,
        "qualified": sum(after.values()),
        "rejected": max(0, sum(before.values()) - sum(after.values())),
        "near_duplicates_collapsed": duplicate_count,
        "rejected_examples": rejected[:40],
        "truth_boundary": "EVIDENCE_MUST_MATCH_BOTH_OPPORTUNITY_AND_RESEARCH_LANE",
        "meaning": "RELATED_MISMATCH_OR_DEPENDENT_DUPLICATE_TRACES_ARE_PRESERVED_IN_AUDIT_BUT_DO_NOT_COUNT",
    }
    return filtered


def _traceable_url(value: Any) -> str:
    url = _clean(value)
    if not url:
        return ""
    low = url.lower()
    if not (low.startswith("https://") or low.startswith("http://")):
        return ""
    return url


def _recount_brief_summary(brief: dict[str, Any]) -> None:
    summary = brief.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        brief["summary"] = summary
    human = len(brief.get("human_comments") or [])
    products = len(brief.get("similar_products") or [])
    repos = len(brief.get("repo_solutions") or [])
    supporting = len(brief.get("supporting_evidence") or [])
    counter = len(brief.get("counter_evidence") or [])
    summary["human_comment_count"] = human
    summary["product_or_service_count"] = products
    summary["repo_solution_count"] = repos
    summary["supporting_evidence_count"] = supporting
    summary["counter_evidence_count"] = counter
    summary["useful_result_count"] = human + products + repos + supporting + counter


def _traceability_filter_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Evidence shown to Founder must have a public original URL.

    Unlinked search snippets stay visible only in the research trace/debug metadata; they are not
    allowed to inflate evidence counts or advance a lane as if the Founder could verify them.
    """
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else None
    if not isinstance(brief, Mapping):
        return result
    filtered_result = copy.deepcopy(dict(result))
    filtered_brief = filtered_result.get("research_brief")
    if not isinstance(filtered_brief, dict):
        return result
    lane_keys = (
        "human_comments",
        "similar_products",
        "repo_solutions",
        "supporting_evidence",
        "counter_evidence",
    )
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    dropped: list[dict[str, Any]] = []
    for key in lane_keys:
        rows = filtered_brief.get(key)
        if not isinstance(rows, list):
            continue
        before[key] = len(rows)
        kept = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            url = _traceable_url(row.get("url"))
            if url:
                copied = dict(row)
                copied["url"] = url
                kept.append(copied)
            else:
                dropped.append({
                    "lane": key,
                    "source": _clean(row.get("source")),
                    "title": _clean(row.get("title"))[:220],
                    "reason": "NO_PUBLIC_ORIGINAL_URL",
                })
        filtered_brief[key] = kept
        after[key] = len(kept)
    _recount_brief_summary(filtered_brief)
    filtered_result["traceability_gate"] = {
        "status": "PUBLIC_ORIGINAL_URL_REQUIRED",
        "before": before,
        "after": after,
        "filtered_unlinked": max(0, sum(before.values()) - sum(after.values())),
        "dropped": dropped[:20],
        "meaning": "UNLINKED_SEARCH_TRACES_DO_NOT_COUNT_AS_FOUNDER_EVIDENCE",
    }
    return filtered_result



def _source_grounding_filter_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Reject only explicit source-content mismatches; access failures remain uncertainty, not absence.

    This follows the retrieve -> curate -> extract pattern used by mature research systems. Search
    snippets can nominate evidence, but a substantial original-page extraction with zero content
    overlap is not allowed to become Founder-visible evidence. 403/JS/login failures are preserved
    as unverified rather than treated as negative market evidence.
    """
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else None
    checks = result.get("original_page_checks") if isinstance(result.get("original_page_checks"), list) else []
    if not isinstance(brief, Mapping) or not checks:
        return result
    filtered = copy.deepcopy(dict(result))
    fb = filtered.get("research_brief")
    if not isinstance(fb, dict):
        return result
    by_url: dict[str, Mapping[str, Any]] = {}
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        key = _canonical_evidence_url(check.get("url"))
        if key:
            by_url[key] = check
    if not by_url:
        return filtered
    dropped: list[dict[str, Any]] = []
    verified = uncertain = open_failed = 0
    for lane_key in _EVIDENCE_LANE_KEYS:
        rows = fb.get(lane_key)
        if not isinstance(rows, list):
            continue
        kept: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            key = _canonical_evidence_url(row.get("url"))
            check = by_url.get(key) if key else None
            if not isinstance(check, Mapping):
                row["source_grounding"] = {"status": "NOT_CHECKED", "countable": True}
                uncertain += 1
                kept.append(row)
                continue
            verification = check.get("content_verification") if isinstance(check.get("content_verification"), Mapping) else {}
            status = _clean(verification.get("status") or ("OPENED_UNVERIFIED" if check.get("ok") else "OPEN_FAILED")).upper()
            mode = _clean(verification.get("mode") or ((check.get("provider_extract") or {}).get("mode") if isinstance(check.get("provider_extract"), Mapping) else "DIRECT_HTTP"))
            grounding = {
                "status": status,
                "mode": mode or "DIRECT_HTTP",
                "original_page_opened": bool(check.get("ok")),
                "http_status": check.get("status"),
                "source_text_chars": int(check.get("source_text_chars") or 0),
                "overlap_ratio": verification.get("overlap_ratio"),
                "countable": status != "MISMATCH",
            }
            if status == "MISMATCH":
                dropped.append({
                    "lane": lane_key,
                    "source": _clean(row.get("source")),
                    "title": _clean(row.get("title"))[:220],
                    "url": row.get("url"),
                    "reason": "ORIGINAL_PAGE_CONTENT_MISMATCH",
                    "grounding": grounding,
                })
                continue
            row["source_grounding"] = grounding
            if status == "MATCH":
                verified += 1
            elif status == "OPEN_FAILED":
                open_failed += 1
            else:
                uncertain += 1
            kept.append(row)
        fb[lane_key] = kept
    _recount_brief_summary(fb)
    filtered["source_grounding_gate"] = {
        "status": "SEARCH_THEN_ORIGINAL_SOURCE_GROUNDING",
        "verified": verified,
        "uncertain_but_not_rejected": uncertain,
        "open_failed_but_not_interpreted_as_absence": open_failed,
        "explicit_mismatches_rejected": len(dropped),
        "dropped": dropped[:20],
        "meaning": "SEARCH_SNIPPETS_NOMINATE;_EXPLICIT_ORIGINAL_CONTENT_MISMATCHES_DO_NOT_COUNT;_ACCESS_FAILURE_IS_UNCERTAINTY",
    }
    return filtered

def _result_research_trace(result: Mapping[str, Any]) -> dict[str, Any]:
    bridge = result.get("query_bridge") if isinstance(result.get("query_bridge"), Mapping) else {}
    explicit = result.get("research_trace") if isinstance(result.get("research_trace"), Mapping) else {}
    search = _search(result)
    trace: dict[str, Any] = {
        "mode": _clean(explicit.get("mode") or result.get("mode") or "IDEA_RESEARCH_BATCH"),
        "retrieval_query": _clean(explicit.get("retrieval_query") or bridge.get("retrieval_query")),
        "relevance_query": _clean(explicit.get("relevance_query") or bridge.get("relevance_query")),
        "query_bridge_status": _clean(explicit.get("query_bridge_status") or bridge.get("status")),
        "query_bridge_api_calls": int(explicit.get("query_bridge_api_calls") or bridge.get("api_calls") or 0),
        "successful_sources": _successful_sources(result),
        "failed_sources": _failed_sources(result),
        "source_attempts": list(explicit.get("source_attempts") or [])[:24] if isinstance(explicit.get("source_attempts"), list) else [],
        "query_runs": list(explicit.get("query_runs") or [])[:12] if isinstance(explicit.get("query_runs"), list) else [],
        "original_page_checks": list(result.get("original_page_checks") or [])[:20] if isinstance(result.get("original_page_checks"), list) else [],
        "source_grounding_gate": copy.deepcopy(dict(result.get("source_grounding_gate") or {})) if isinstance(result.get("source_grounding_gate"), Mapping) else {},
        "search_metadata": {
            key: search.get(key)
            for key in ("collection_status", "source_count", "raw_result_count", "useful_result_count")
            if key in search
        },
    }
    return trace

def _quality_filter_result(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Founder-visible evidence must be traceable, opportunity-matched, lane-qualified and independent.

    HOTFIX3 ports the old U17/U18 evidence boundary into the Research Backlog instead of adding more
    ad-hoc lane heuristics.  Raw search traces remain in the research audit; only qualified cards
    are allowed to affect counts, history aggregation, REVIEW_READY, or the ChatGPT handoff.
    """
    result = _traceability_filter_result(result)
    result = _source_grounding_filter_result(result)
    return _evidence_trust_filter_result(item, job, result)


def _compact_card(row: Mapping[str, Any]) -> dict[str, Any]:
    card = {
        "source": row.get("source"),
        "title": _clean(row.get("title"))[:280],
        "excerpt": _clean(row.get("excerpt"))[:700],
        "url": _traceable_url(row.get("url")) or None,
        "author": row.get("author"),
        "profile_url": row.get("profile_url"),
        "source_published_at": row.get("source_published_at") or row.get("published_at") or row.get("created_at") or row.get("date"),
        "match_level": row.get("match_level"),
        "solution_type": row.get("solution_type"),
        "tracking_family": row.get("tracking_family"),
        "search_query": row.get("search_query"),
    }
    grounding = row.get("source_grounding") if isinstance(row.get("source_grounding"), Mapping) else None
    if grounding:
        card["source_grounding"] = copy.deepcopy(dict(grounding))
    trust = row.get("evidence_trust") if isinstance(row.get("evidence_trust"), Mapping) else None
    if trust:
        card["evidence_trust"] = copy.deepcopy(dict(trust))
    return card


def _top_cards(result: Mapping[str, Any], key: str, limit: int = 4) -> list[dict[str, Any]]:
    rows = _brief(result).get(key)
    if not isinstance(rows, list):
        return []
    return [_compact_card(row) for row in rows[:limit] if isinstance(row, Mapping)]


def _failed_sources(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _search(result).get("failed_sources")
    if not isinstance(rows, list):
        return []
    return [dict(x) for x in rows[:8] if isinstance(x, Mapping)]


def _successful_sources(result: Mapping[str, Any]) -> list[str]:
    rows = _search(result).get("successful_sources")
    if not isinstance(rows, list):
        return []
    return [_clean(x) for x in rows if _clean(x)]


def _context_lines(item: Mapping[str, Any]) -> list[str]:
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    labels = {
        "actor": "Actor",
        "actor_category": "Actor category",
        "task": "Task",
        "object": "Object",
        "failure_mode": "Failure mode",
        "consequence": "Consequence",
        "buyer_context": "Buyer context",
        "workaround": "Current workaround",
        "who_has_problem": "Who has the problem",
        "why_now": "Why now",
        "workarounds": "Known workarounds",
        "existing_solutions": "Existing solutions",
        "buyer_signals": "Buyer signals",
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = context.get(key)
        if _emptyish(value):
            continue
        if isinstance(value, (list, tuple)):
            text = "; ".join(_clean(x) for x in value[:8] if _clean(x))
        elif isinstance(value, Mapping):
            parts = []
            for k, v in list(value.items())[:8]:
                if _clean(v):
                    parts.append(f"{_clean(k)}={_clean(v)}")
            text = "; ".join(parts)
        else:
            text = _clean(value)
        if text:
            lines.append(f"{label}: {text[:900]}")
    return lines


def _research_base(item: Mapping[str, Any]) -> str:
    description = _clean(item.get("description"))
    context_lines = _context_lines(item)
    chunks = [description] if description else []
    if context_lines:
        chunks.append(
            "Imported backlog context (UNVALIDATED, use only to make the search specific; do not treat as market truth):\n"
            + "\n".join(context_lines)
        )
    return "\n\n".join(chunks)




def _research_context_anchors(item: Mapping[str, Any], job: str, *, limit: int = 8) -> list[str]:
    """Carry diverse retrieved clues forward into the next research lane.

    These are search anchors only. They remain UNVALIDATED traces and must never be restated as
    market truth. Round-robin across evidence types so eight products cannot crowd out the human
    wording or paid-friction clue that makes the next search materially more specific.
    """
    job = _clean(job).upper()
    lane_preferences: dict[str, tuple[str, ...]] = {
        "CURRENT_SOLUTIONS": ("human_comments", "supporting"),
        "PAID_DISSATISFACTION": ("products", "repos", "human_comments", "supporting"),
        "BUYER_PAYER_WTP": ("explicit_paid_dissatisfaction", "products", "human_comments"),
        "COUNTEREVIDENCE": ("products", "repos", "explicit_paid_dissatisfaction", "human_comments", "supporting"),
    }
    lanes = lane_preferences.get(job, ())
    if not lanes:
        return []

    lane_cards = {
        lane: _aggregate_history_cards(item, (lane,), limit=max(limit * 2, 12), newest_first=True)
        for lane in lanes
    }
    out: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(out) < limit:
        progressed = False
        for lane in lanes:
            rows = lane_cards.get(lane) or []
            if depth >= len(rows):
                continue
            progressed = True
            card = rows[depth]
            title = _clean(card.get("title"))
            excerpt = _clean(card.get("excerpt"))
            source = _clean(card.get("source"))
            phrase = title or excerpt
            if title and excerpt and excerpt.lower() not in title.lower():
                phrase = f"{title} — {excerpt[:180]}"
            phrase = _clean(phrase)[:260]
            key = phrase.lower()
            if not phrase or key in seen:
                continue
            seen.add(key)
            out.append((f"[{source}] " if source else "") + phrase)
            if len(out) >= limit:
                break
        if not progressed:
            break
        depth += 1
    return out

def _research_context_block(item: Mapping[str, Any], job: str) -> str:
    anchors = _research_context_anchors(item, job)
    if not anchors:
        return ""
    return (
        "Previously retrieved research anchors (UNVALIDATED; use only to target the next search, "
        "do not repeat them as facts):\n"
        + "\n".join(f"- {anchor}" for anchor in anchors)
    )

def _next_question(job: str | None) -> str:
    key = _clean(job).upper()
    return JOB_QUESTIONS.get(key, "目前沒有下一個自動研究問題；請只根據累積 evidence 決定是否值得取得真人市場證據。")



_TRACKING_SEARCH_BOILERPLATE = (
    "research hypothesis", "研究假設", "這些都是待驗證假設", "待驗證假設",
    "signalforge 應研究", "signalforge should research", "do not treat as market truth",
    "imported backlog context", "unvalidated", "market truth", "source expansion mode",
)


def _tracking_clean_seed_text(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    # Old opportunity imports contain instructions to the former autonomous-research workflow.
    # Those instructions are metadata, not search terms. Stop at the first known boilerplate marker.
    lower = text.lower()
    cut = len(text)
    for needle in _TRACKING_SEARCH_BOILERPLATE:
        idx = lower.find(needle.lower())
        if idx >= 0:
            cut = min(cut, idx)
    text = text[:cut]
    text = re.sub(r"(?:^|[；;。.!?])\s*(?:目前可能透過)?\s*待驗證[:：]?", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -—–:：;；。")
    return text[:1200]


def _tracking_search_seed(item: Mapping[str, Any]) -> str:
    """Build a compact search-only seed from the actual opportunity facets.

    This is intentionally not a market summary. It avoids carrying old workflow instructions such
    as UNVALIDATED / SignalForge 應研究 into search queries, which previously diluted retrieval.
    """
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    parts: list[str] = []
    title = _tracking_clean_seed_text(item.get("title"))
    if title:
        parts.append(title)
    for key in ("actor", "task", "failure_mode", "consequence", "buyer_context", "workaround", "current_workaround"):
        value = _tracking_clean_seed_text(context.get(key))
        if value and value.lower() not in {x.lower() for x in parts}:
            parts.append(value)
    if len(parts) < 3:
        desc = _tracking_clean_seed_text(item.get("description"))
        if desc:
            parts.append(desc)
    # Preserve multilingual phrases; the web route will build an English bridge separately.
    return " | ".join(parts)[:2200]


def _tracking_family_yields(item: Mapping[str, Any], *, history_limit: int = 8) -> dict[str, int]:
    counts: dict[str, int] = {family: 0 for family in _TRACKING_SOURCE_FAMILIES}
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    for row in history[-history_limit:]:
        family_counts = row.get("tracking_family_counts") if isinstance(row.get("tracking_family_counts"), Mapping) else {}
        for family, raw in family_counts.items():
            if family not in counts:
                continue
            try:
                counts[family] += int(raw or 0)
            except Exception:
                pass
    return counts


def _preferred_tracking_families(item: Mapping[str, Any]) -> list[str]:
    """Pick refresh families from actual related-material yield, not raw search hit volume."""
    yields = _tracking_family_yields(item)
    ranked = sorted(
        (family for family in _TRACKING_SOURCE_FAMILIES if family not in {"general_web", "local_language", "related_products"}),
        key=lambda family: (-int(yields.get(family) or 0), _TRACKING_SOURCE_FAMILIES.index(family)),
    )
    positive = [family for family in ranked if int(yields.get(family) or 0) > 0]
    fallback = [
        "public_discussions", "vendor_support_communities", "product_reviews", "manual_workarounds",
        "behavior_routines", "category_language", "switching_signals",
        "related_products", "app_marketplaces", "research_cases", "academic_sources", "b2b_operational_signals",
    ]
    out: list[str] = []
    for family in positive + fallback:
        if family not in out:
            out.append(family)
        if len(out) >= 3:
            break
    return out


def _tracking_material_family_stats(item: Mapping[str, Any]) -> dict[str, int]:
    stats: dict[str, int] = {}
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    for category in _TRACKING_CATEGORIES:
        for row in (library.get(category) or []):
            if not isinstance(row, Mapping):
                continue
            family = _clean(row.get("tracking_family")) or "legacy_or_specialist"
            stats[family] = stats.get(family, 0) + 1
    return dict(sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])))


def _job_prompt(item: Mapping[str, Any], job: str) -> tuple[str, str]:
    title = _clean(item.get("title"))
    base = _research_base(item)
    if job == "BASELINE":
        return title, base
    prior_context = _research_context_block(item, job)
    research_base = base + ("\n\n" + prior_context if prior_context else "")
    if job == "CURRENT_SOLUTIONS":
        return title, (
            f"{research_base}\n\nResearch focus: how people solve this today. Find real workarounds, manual workflows, "
            "existing products/services/open-source tools, and what part of the original job each alternative actually covers. "
            "Do not treat generic adjacent tools as exact alternatives."
        )
    if job == "PAID_DISSATISFACTION":
        return title, (
            f"{research_base}\n\nResearch focus: paid dissatisfaction. Look for teams or users already paying for or materially investing in "
            "the current solution/workflow but still doing manual work, complaining, switching, adding another tool, or accepting rework. "
            "Ordinary free-user complaints are weaker evidence and should not be upgraded into willingness to pay."
        )
    if job == "BUYER_PAYER_WTP":
        return title, (
            f"{research_base}\n\nResearch focus: buyer and payer reality. Look for who owns this workflow, who approves spend, current pricing/spend evidence, "
            "purchase or switching behavior, and concrete willingness-to-pay signals. Do not estimate spend or WTP when no source states it."
        )
    if job == "COUNTEREVIDENCE":
        return title, (
            f"{research_base}\n\nResearch focus: try to falsify the opportunity. Find evidence that the problem is rare, cheap to tolerate, already solved well enough, "
            "bundled into existing products, rapidly disappearing, or not important enough to buy separately."
        )
    return title, base


def _next_job_after(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> tuple[str | None, str, str, bool]:
    counts = _counts(result)
    status = _clean(result.get("status")).upper()
    successful = _successful_sources(result)
    failed = _failed_sources(result)
    founder_submitted = _clean(item.get("source_kind")).upper() in CURATED_SOURCE_KINDS

    if status == "SEARCH_FAILED" or (not successful and failed):
        return None, "SOURCE_LIMITED", "公開來源這輪搜尋失敗或受限；不能把找不到結果解讀成市場不存在。", False
    if job == "BASELINE" and counts["useful"] == 0:
        if _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "第一輪沒有合格 evidence，而且來源 coverage 不完整；先重試來源，不做市場否定。", False
        if founder_submitted:
            return "CURRENT_SOLUTIONS", "AUTO_RESEARCH", "Founder 明確送進來的商機在第一輪沒有合格 evidence；不再因單一 lane 直接 PARK，繼續查現有方案／workaround 後再判斷。", False
        return None, "PARKED_NO_PUBLIC_SIGNAL", "第一輪在足夠成功來源都沒有找到合格材料；先暫停自動深挖，不等於市場不存在。", False
    if job == "BASELINE" and _baseline_is_weak_single_trace(result):
        if _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "第一輪只有單一合格弱 trace，而且來源 coverage 不完整；先重試來源。", False
        return "CURRENT_SOLUTIONS", "AUTO_RESEARCH", "第一輪只有單一合格弱 trace；繼續查現有方案與 workaround，避免用薄證據提前定型。", False
    if job == "BASELINE":
        if counts["products"] + counts["repos"] == 0:
            return "CURRENT_SOLUTIONS", "AUTO_RESEARCH", "第一輪已有合格真人／旁證，但現有替代方案仍不清楚，先補 current-solutions lane。", False
        return "PAID_DISSATISFACTION", "AUTO_RESEARCH", "第一輪已有合格公開訊號與替代方案，下一輪查已投入成本但仍不滿的直接證據。", False
    if job == "CURRENT_SOLUTIONS":
        if counts["products"] + counts["repos"] == 0 and _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "現有方案專題沒有找到合格替代方案，而且來源 coverage 太薄；先重試同一 lane。", False
        return "PAID_DISSATISFACTION", "AUTO_RESEARCH", "現有方案這格已掃過；下一輪只查同一商機中付費／投入後仍未解的直接證據。", False
    if job == "PAID_DISSATISFACTION":
        direct_paid = _explicit_paid_dissatisfaction_cards(result)
        if not direct_paid and _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "Paid dissatisfaction 沒找到合格 paid + friction，而且來源 coverage 不完整；先重試同一 lane。", False
        if not direct_paid:
            return "BUYER_PAYER_WTP", "AUTO_RESEARCH", "沒有找到同一商機的直接 paid + unresolved-friction；這個缺口保留，下一輪獨立查 buyer / payer / price / spend / WTP。", False
        return "BUYER_PAYER_WTP", "AUTO_RESEARCH", f"找到 {len(direct_paid)} 筆合格 paid + unresolved-friction evidence；下一輪查 buyer / payer / spend / WTP。", False
    if job == "BUYER_PAYER_WTP":
        if counts["useful"] == 0 and _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "Buyer / payer / WTP 沒找到合格材料且來源 coverage 不完整；先重試。", False
        return "COUNTEREVIDENCE", "AUTO_RESEARCH", "Buyer / payer / WTP 已完成一輪合格性過濾；最後主動找真正會削弱這個商機的反證。", False
    if job == "COUNTEREVIDENCE":
        if counts["counter"] == 0 and _negative_decision_coverage_limited(result):
            return None, "SOURCE_LIMITED", "反證專題沒有找到合格反面材料且來源 coverage 不完整；先重試。", False
        # History is appended before the persisted state derivation, so coverage already includes
        # this counterevidence lane. Do not add current counts a second time.
        coverage = _coverage_for_item(item)
        qualified_total = int(coverage.get("unique_evidence") or 0)
        if qualified_total <= 0:
            return None, "PARKED_NO_PUBLIC_SIGNAL", "五個 lanes 都跑過後仍沒有合格、可核對且與商機直接相關的 evidence；先暫停，不把 0 解讀成市場不存在。", False
        gate = coverage.get("review_ready_evidence_gate") if isinstance(coverage.get("review_ready_evidence_gate"), Mapping) else _review_ready_evidence_gate(coverage)
        if not bool(gate.get("passed")):
            return None, "PARKED_WEAK_SIGNAL", "五個 lanes 已掃過，但合格 evidence 仍太薄或集中在單一類型；先暫緩，不把完成搜尋誤寫成值得 Founder 決策，也不把公開資料不足解讀成沒有市場。", False
        return None, "REVIEW_READY", "主要 research lanes 已跑過，而且累積 evidence 同時具備問題訊號與獨立旁證；現在才值得 Founder / ChatGPT 看。", True
    return None, "REVIEW_READY", "目前沒有下一個自動研究工作。", True


def _merge_unique_text(existing: Sequence[str], additions: Sequence[str], limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *additions]:
        text = _clean(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _card_identity(row: Mapping[str, Any]) -> str:
    url = _canonical_evidence_url(row.get("url"))
    if url:
        return "url:" + url
    return "text:" + _normalize_evidence_text(row)[:1200]


def _aggregate_history_cards(
    item: Mapping[str, Any],
    lanes: Sequence[str],
    *,
    limit: int = 60,
    newest_first: bool = False,
) -> list[dict[str, Any]]:
    history = list(item.get("history") or [])
    entries = list(reversed(history)) if newest_first else history
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        job = _clean(entry.get("job")).upper()
        for lane in lanes:
            rows = entry.get(lane) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                trust = row.get("evidence_trust") if isinstance(row.get("evidence_trust"), Mapping) else {}
                # New and migrated snapshots explicitly qualify cards.  Unmigrated raw legacy rows
                # are never silently upgraded into trusted evidence.
                if _clean(trust.get("verdict")).upper() != "QUALIFIED":
                    continue
                key = _card_identity(row)
                if not key or key in seen:
                    continue
                if any(_near_duplicate_rows(existing, row) for existing in out):
                    continue
                seen.add(key)
                card = dict(row)
                card["research_job"] = job
                out.append(card)
                if len(out) >= limit:
                    return out
    return out


def _handoff_accumulated_cards(item: Mapping[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    """Representative, trust-qualified, independent evidence across research lanes."""
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    evidence_lanes = ("human_comments", "products", "repos", "supporting")
    preferred_jobs = ("BASELINE", "CURRENT_SOLUTIONS", "PAID_DISSATISFACTION", "BUYER_PAYER_WTP")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_from_entry(entry: Mapping[str, Any], quota: int) -> int:
        added = 0
        for lane in evidence_lanes:
            rows = entry.get(lane) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                trust = row.get("evidence_trust") if isinstance(row.get("evidence_trust"), Mapping) else {}
                if _clean(trust.get("verdict")).upper() != "QUALIFIED":
                    continue
                key = _card_identity(row)
                if not key or key in seen or any(_near_duplicate_rows(existing, row) for existing in out):
                    continue
                seen.add(key)
                card = dict(row)
                card["research_job"] = _clean(entry.get("job")).upper()
                out.append(card)
                added += 1
                if len(out) >= limit or added >= quota:
                    return added
        return added

    for job in preferred_jobs:
        for entry in reversed(history):
            if _clean(entry.get("job")).upper() != job:
                continue
            before = len(out)
            add_from_entry(entry, 2)
            if len(out) > before or len(out) >= limit:
                break
        if len(out) >= limit:
            return out[:limit]
    for entry in reversed(history):
        add_from_entry(entry, max(1, limit - len(out)))
        if len(out) >= limit:
            break
    return out[:limit]


_SOLUTION_SUPPLY_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(?:booking|scheduling|management|tutoring|attendance|memory|context) (?:software|system|platform|app)\b",
    r"\b(?:software|platform|app|plugin|extension|service|crm) (?:for|to)\b",
    r"\b(?:open[ -]?source|repo(?:sitory)?|context engine|memory tool|booking system|scheduling software|management software)\b",
    r"\b(?:we use|i use|using|switched to|migrated to)\b",
    r"(?:預約|排課|堂數|出缺席|記憶|上下文).{0,12}(?:系統|軟體|平台|工具|服務)",
))


def _looks_like_solution_supply(card: Mapping[str, Any]) -> bool:
    """Recognize solution-supply evidence even when an upstream retriever filed it as supporting.

    Search providers often return product/review pages in a generic supporting bucket.  If the card
    already passed thesis + atomic-pain qualification, explicit solution language is enough to count
    it as landscape evidence; this does not claim the product fully solves the Founder pain.
    """
    trust = card.get("evidence_trust") if isinstance(card.get("evidence_trust"), Mapping) else {}
    lane_match = _clean(trust.get("lane_match")).upper()
    if lane_match in {"DIRECT_SOLUTION_OBJECT", "WORKAROUND_OR_SOLUTION_CUE"}:
        return True
    text = _evidence_card_text(card)
    return any(pattern.search(text) for pattern in _SOLUTION_SUPPLY_PATTERNS)


def _review_ready_evidence_gate(coverage: Mapping[str, Any]) -> dict[str, Any]:
    """REVIEW_READY is a Founder-attention gate, not a reward for merely attempting five lanes.

    A handoff is useful when it contains an actual problem signal and at least one independent
    corroborating dimension (solution landscape / paid behaviour / buyer signal), or several
    independent human problem traces.  Thin product-only search results stay parked as weak public
    evidence; they are never converted into a market-negative conclusion.
    """
    total = int(coverage.get("unique_evidence") or 0)
    human = int(coverage.get("unique_human") or 0)
    solutions = int(coverage.get("unique_solutions") or 0)
    paid_direct = int(coverage.get("paid_dissatisfaction_direct") or 0)
    lane_useful = coverage.get("lane_useful") if isinstance(coverage.get("lane_useful"), Mapping) else {}
    buyer = int(lane_useful.get("BUYER_PAYER_WTP") or 0)

    reasons: list[str] = []
    if total < 3:
        reasons.append("fewer_than_3_independent_evidence")
    useful_mix = (
        human >= 3
        or (human >= 1 and solutions >= 1)
        or (human >= 1 and (paid_direct >= 1 or buyer >= 1))
        or (solutions >= 1 and paid_direct >= 1)
    )
    if not useful_mix:
        reasons.append("missing_problem_signal_plus_independent_corroboration")
    return {
        "passed": total >= 3 and useful_mix,
        "unique_evidence": total,
        "unique_human": human,
        "unique_solutions": solutions,
        "paid_dissatisfaction_direct": paid_direct,
        "buyer_payer_wtp_useful": buyer,
        "reasons": reasons,
        "meaning": "FOUNDER_REVIEW_REQUIRES_EVIDENCE_DIVERSITY_NOT_JUST_COMPLETED_SEARCH_LANES",
    }


def _coverage_for_item(item: Mapping[str, Any]) -> dict[str, Any]:
    history = [x for x in (item.get("history") or []) if isinstance(x, Mapping)]
    completed_set = {
        _clean(x.get("job")).upper()
        for x in history
        if (
            _clean(x.get("job")).upper() in JOB_ORDER
            and x.get("coverage_complete") is not False
            and not bool(x.get("coverage_superseded", False))
        )
    }
    completed_jobs = [job for job in JOB_ORDER if job in completed_set]
    humans = _aggregate_history_cards(item, ("human_comments",), limit=200)
    direct_solutions = _aggregate_history_cards(item, ("products", "repos"), limit=200)
    supporting = _aggregate_history_cards(item, ("supporting",), limit=200)
    counters = _aggregate_history_cards(item, ("counterevidence",), limit=200)
    all_rows = _aggregate_history_cards(item, ("human_comments", "products", "repos", "supporting", "counterevidence"), limit=500)

    # Provider/retriever schemas are imperfect: a clearly relevant booking software page can land
    # in `supporting`. Count such already-qualified cards as solution-landscape signals without
    # mutating the immutable raw search classification.
    solutions: list[dict[str, Any]] = []
    solution_seen: set[str] = set()
    for card in [*direct_solutions, *all_rows]:
        if not isinstance(card, Mapping):
            continue
        if card not in direct_solutions and not _looks_like_solution_supply(card):
            continue
        key = _card_identity(card)
        if not key or key in solution_seen or any(_near_duplicate_rows(existing, card) for existing in solutions):
            continue
        solution_seen.add(key)
        solutions.append(dict(card))
    # Lane summaries describe completed coverage only. A source-limited retry can still retain
    # useful evidence in the history, but it must not inflate the completed-lane summary.
    latest_completed: dict[str, Mapping[str, Any]] = {}
    for entry in history:
        job = _clean(entry.get("job")).upper()
        if (
            job in JOB_ORDER
            and entry.get("coverage_complete") is not False
            and not bool(entry.get("coverage_superseded", False))
        ):
            latest_completed[job] = entry
    lane_useful: dict[str, int] = {
        job: int((entry.get("counts") or {}).get("useful") or 0)
        for job, entry in latest_completed.items()
    }
    # Retried paid-dissatisfaction searches often rediscover the same comment. Count unique
    # evidence identities across history instead of summing per-snapshot counts.
    paid_direct_cards = _aggregate_history_cards(item, ("explicit_paid_dissatisfaction",), limit=200)
    paid_direct = len(paid_direct_cards)
    review_priority = (
        len(completed_jobs) * 10
        + min(len(humans), 6) * 3
        + min(len(solutions), 6) * 2
        + min(len(supporting), 4)
        + min(len(counters), 4)
        + (3 if lane_useful.get("PAID_DISSATISFACTION", 0) > 0 else 0)
        + (3 if lane_useful.get("BUYER_PAYER_WTP", 0) > 0 else 0)
    )
    coverage = {
        "completed_jobs": completed_jobs,
        "unique_evidence": len(all_rows),
        "unique_human": len(humans),
        "unique_solutions": len(solutions),
        "unique_supporting": len(supporting),
        "unique_counter": len(counters),
        "lane_useful": lane_useful,
        "paid_dissatisfaction_direct": paid_direct,
        "review_priority": review_priority,
        "meaning": "REVIEW_PRIORITY_ONLY_NOT_MARKET_SCORE",
    }
    coverage["review_ready_evidence_gate"] = _review_ready_evidence_gate(coverage)
    return coverage


def _refresh_accumulated_state(item: dict[str, Any]) -> None:
    coverage = _coverage_for_item(item)
    item["research_coverage"] = coverage
    item["review_priority"] = int(coverage.get("review_priority") or 0)
    completed_jobs = list(coverage.get("completed_jobs") or [])
    known: list[str] = []
    if completed_jobs:
        known.append(f"公開研究已完成 {len(completed_jobs)}/{len(JOB_ORDER)} 個主要 lanes：{', '.join(completed_jobs)}。")
    if int(coverage.get("unique_human") or 0):
        known.append(f"累積保留 {coverage['unique_human']} 組不重複真人討論材料；仍屬搜尋 trace，不等於需求已驗證。")
    if int(coverage.get("unique_solutions") or 0):
        known.append(f"累積保留 {coverage['unique_solutions']} 組不重複產品／服務／Repo 替代方案材料。")
    if "PAID_DISSATISFACTION" in completed_jobs:
        useful = int((coverage.get("lane_useful") or {}).get("PAID_DISSATISFACTION") or 0)
        direct = int(coverage.get("paid_dissatisfaction_direct") or 0)
        known.append(f"Paid dissatisfaction 專題已搜尋；該輪有 {useful} 筆可用材料，其中 {direct} 筆同時出現明確付費／投入與未解摩擦 cue；仍屬搜尋 trace。")
    if "BUYER_PAYER_WTP" in completed_jobs:
        useful = int((coverage.get("lane_useful") or {}).get("BUYER_PAYER_WTP") or 0)
        known.append(f"Buyer / payer / WTP 專題已搜尋；該輪有 {useful} 筆可用材料，沒有明示金額就不能自行推估 WTP。")
    item["known"] = known[:12]

    history = [x for x in (item.get("history") or []) if isinstance(x, Mapping)]
    latest = history[-1] if history else {}
    gaps = [_clean(x) for x in (latest.get("gaps") or []) if _clean(x)]
    # Do not show a stale generic gap that directly contradicts accumulated qualified evidence.
    filtered_gaps: list[str] = []
    for gap in gaps:
        if int(coverage.get("unique_human") or 0) > 0 and "真人" in gap:
            continue
        if int(coverage.get("unique_solutions") or 0) > 0 and ("現有產品" in gap or "替代方案" in gap):
            continue
        if int(coverage.get("unique_supporting") or 0) > 0 and ("市場／技術／新聞／職缺" in gap or "旁證" in gap):
            continue
        filtered_gaps.append(gap)
    unknown: list[str] = filtered_gaps[:5]
    next_job = _clean(item.get("next_job")).upper() or None
    if next_job:
        unknown.append(_next_question(next_job))
    elif _clean(item.get("auto_status")).upper() == "REVIEW_READY":
        unknown.append("公開搜尋仍不能直接證明實際採用、切換或付費；若要前進，這格必須靠真人／行為市場證據。")
    item["unknown"] = _merge_unique_text([], unknown or ["目前沒有新的明確 gap；不要自行補市場故事。"], limit=10)

    counter_cards = _aggregate_history_cards(item, ("counterevidence",), limit=10, newest_first=True)
    item["counterevidence"] = _merge_unique_text([], [
        _clean(card.get("title")) for card in counter_cards if _clean(card.get("title"))
    ], limit=10)


def _terminal_next_question(auto_status: str, job: str) -> str:
    status = _clean(auto_status).upper()
    job = _clean(job).upper()
    if status == "PARKED_NO_PUBLIC_SIGNAL":
        return (
            "目前最大未知不是 buyer/WTP，而是公開來源沒有訊號究竟代表需求真的很弱，"
            "還是討論存在於其他用語／私域場景；在拿到新的真人或來源入口前先不自動深挖。"
        )
    if status == "PARKED_WEAK_SIGNAL" and job == "BASELINE":
        return (
            "目前最大未知是這個方向能否找到第二個獨立真人／多來源問題訊號；"
            "只有單一產品、Repo 或文章 trace 還不值得往付費與 buyer 深挖。"
        )
    if status == "PARKED_WEAK_SIGNAL" and job == "PAID_DISSATISFACTION":
        return (
            "這是舊版停點；V1.6 會保留『未找到直接 paid + friction』的結果，"
            "但 Founder 明確提交的商機仍會繼續查 buyer / payer / pricing / switching 與反證。"
        )
    if status == "PARKED_WEAK_SIGNAL":
        return "目前公開研究已經掃過但證據組合仍太薄；下一份最高價值材料是同一工作流程的直接真人問題／實際使用行為，而不是再用泛搜尋湊更多產品頁。"
    if status == "REVIEW_READY":
        return (
            "公開資料主要 research lanes 已跑完；下一個真正高價值未知通常是實際 buyer 是否願意採用、"
            "切換或付費，需要真人／行為市場證據。"
        )
    return "目前沒有下一個自動研究問題；不要把研究停止狀態誤解成市場結論。"


def _derive_state(item: dict[str, Any], job: str, result: Mapping[str, Any]) -> None:
    next_job, auto_status, why, needs_founder = _next_job_after(item, job, result)
    if auto_status == "SOURCE_LIMITED":
        # Keep the same lane pending. A source outage is not a completed research step.
        next_job = job
        _schedule_source_retry(item, job, why)
    else:
        _clear_source_retry(item)
    item["auto_status"] = auto_status
    item["current_call"] = {
        "AUTO_RESEARCH": "SignalForge 繼續研究",
        "PARKED_NO_PUBLIC_SIGNAL": "先暫停：目前沒有公開訊號",
        "PARKED_WEAK_SIGNAL": "弱訊號暫緩：先不浪費研究成本",
        "SOURCE_LIMITED": "來源不足：先不要下結論",
        "REVIEW_READY": "公開研究已收斂到值得看",
    }.get(auto_status, auto_status)
    item["why"] = why
    item["next_job"] = next_job
    if auto_status == "SOURCE_LIMITED":
        item["next_question"] = f"來源恢復後重跑 {job}；這次搜尋不足不能當成沒有市場。"
    elif next_job:
        item["next_question"] = _next_question(next_job)
    else:
        item["next_question"] = _terminal_next_question(auto_status, job)
    item["needs_founder"] = bool(needs_founder)
    item["latest_change"] = f"RESEARCH_{job}_COMPLETED"
    item["updated_at"] = _now()
    _refresh_accumulated_state(item)


def _history_snapshot(job: str, result: Mapping[str, Any], started_at: str, completed_at: str) -> dict[str, Any]:
    trust_gate = dict(result.get("evidence_trust_gate") or {}) if isinstance(result.get("evidence_trust_gate"), Mapping) else {}
    return {
        "research_id": f"r-{_sha_key(started_at + job)}",
        "job": job,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": result.get("status"),
        "counts": _counts(result),
        "human_comments": _top_cards(result, "human_comments"),
        "products": _top_cards(result, "similar_products"),
        "repos": _top_cards(result, "repo_solutions"),
        "supporting": _top_cards(result, "supporting_evidence"),
        "counterevidence": _top_cards(result, "counter_evidence"),
        "explicit_paid_dissatisfaction": _explicit_paid_dissatisfaction_cards(result, 6),
        "explicit_paid_dissatisfaction_count": len(_explicit_paid_dissatisfaction_cards(result, 6)),
        "gaps": list(_brief(result).get("gaps") or [])[:8],
        "successful_sources": _successful_sources(result),
        "failed_sources": _failed_sources(result),
        "quality_gate": dict(result.get("quality_gate") or {}) if isinstance(result.get("quality_gate"), Mapping) else {},
        "traceability_gate": dict(result.get("traceability_gate") or {}) if isinstance(result.get("traceability_gate"), Mapping) else {},
        "evidence_trust_gate": trust_gate,
        "evidence_trust_version": trust_gate.get("version") or _EVIDENCE_TRUST_VERSION,
        "research_trace": _result_research_trace(result),
        "coverage_complete": not _research_transport_limited(result),
        "coverage_reason": (
            "SOURCE_TRANSPORT_LIMITED_NOT_COMPLETE"
            if _research_transport_limited(result)
            else "RESEARCH_RESULT_COMPLETED"
        ),
        "market_truth_writes": 0,
    }


def _item_for_view(
    item: Mapping[str, Any],
    *,
    include_history: bool = False,
    include_handoff: bool = True,
) -> dict[str, Any]:
    history = list(item.get("history") or [])
    latest = history[-1] if history else None
    handoff = build_handoff_text(item) if include_handoff else None
    handoff_hash = hashlib.sha256(handoff.encode("utf-8")).hexdigest()[:24] if handoff is not None else None
    row = {
        "id": item.get("id"),
        "source_kind": item.get("source_kind"),
        "source_ref": item.get("source_ref"),
        "canonical_key": item.get("canonical_key"),
        "title": item.get("title"),
        "description": item.get("description"),
        "source_context": dict(item.get("source_context") or {}),
        "aliases": list(item.get("aliases") or []),
        "import_rank": item.get("import_rank"),
        "auto_status": item.get("auto_status"),
        "current_call": item.get("current_call"),
        "why": item.get("why"),
        "known": list(item.get("known") or []),
        "unknown": list(item.get("unknown") or []),
        "counterevidence": list(item.get("counterevidence") or []),
        "next_job": item.get("next_job"),
        "next_question": item.get("next_question"),
        "needs_founder": bool(item.get("needs_founder")),
        "founder_reviewed_at": item.get("founder_reviewed_at"),
        "founder_reviewed_research_count": int(item.get("founder_reviewed_research_count") or 0),
        "research_count": len(history),
        "latest_research": latest,
        "latest_change": item.get("latest_change"),
        "research_coverage": dict(item.get("research_coverage") or {}),
        "review_priority": int(item.get("review_priority") or 0),
        "source_retry_count": int(item.get("source_retry_count") or 0),
        "source_retry_after": item.get("source_retry_after"),
        "source_retry_job": item.get("source_retry_job"),
        "source_retry_reason": item.get("source_retry_reason"),
        "legacy": dict(item.get("legacy") or {}),
        "updated_at": item.get("updated_at"),
        "market_truth_writes": 0,
    }
    if include_handoff:
        row["handoff"] = handoff
        row["handoff_hash"] = handoff_hash
    if include_history:
        row["history"] = history
    return row


def _item_for_list(item: Mapping[str, Any]) -> dict[str, Any]:
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    latest = history[-1] if history else None
    latest_compact = None
    if isinstance(latest, Mapping):
        latest_compact = {
            "research_id": latest.get("research_id"),
            "job": latest.get("job"),
            "status": latest.get("status"),
            "completed_at": latest.get("completed_at"),
            "counts": dict(latest.get("counts") or {}),
        }
    return {
        "id": item.get("id"),
        "source_kind": item.get("source_kind"),
        "source_ref": item.get("source_ref"),
        "title": item.get("title"),
        "description": item.get("description"),
        "import_rank": item.get("import_rank"),
        "auto_status": item.get("auto_status"),
        "current_call": item.get("current_call"),
        "why": item.get("why"),
        "next_job": item.get("next_job"),
        "next_question": item.get("next_question"),
        "needs_founder": bool(item.get("needs_founder")),
        "research_count": len(history),
        "latest_research": latest_compact,
        "review_priority": int(item.get("review_priority") or 0),
        "source_retry_count": int(item.get("source_retry_count") or 0),
        "source_retry_after": item.get("source_retry_after"),
        "source_retry_job": item.get("source_retry_job"),
        "updated_at": item.get("updated_at"),
        "market_truth_writes": 0,
    }


def _format_handoff_card(row: Mapping[str, Any]) -> str:
    title = _clean(row.get("title")) or "untitled"
    excerpt = _clean(row.get("excerpt"))[:420]
    url = _clean(row.get("url"))
    source = _clean(row.get("source"))
    job = _clean(row.get("research_job"))
    prefix = f"[{job}] " if job else ""
    line = f"- {prefix}{title}" + (f" [{source}]" if source else "")
    if excerpt:
        line += f"\n  {excerpt}"
    if url:
        line += f"\n  {url}"
    return line



def _format_research_trace_for_handoff(entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return "- 尚無 research trace。"
    lines: list[str] = []
    for entry in entries:
        trace = entry.get("research_trace") if isinstance(entry.get("research_trace"), Mapping) else {}
        retrieval = _clean(trace.get("retrieval_query"))
        relevance = _clean(trace.get("relevance_query"))
        successful = [str(x) for x in (trace.get("successful_sources") or []) if _clean(x)]
        failed = [x for x in (trace.get("failed_sources") or []) if isinstance(x, Mapping)]
        checks = [x for x in (trace.get("original_page_checks") or []) if isinstance(x, Mapping)]
        checked_ok = sum(1 for x in checks if bool(x.get("ok")))
        line = f"- {entry.get('job')} | sources ok={len(successful)} failed={len(failed)} | original pages opened={checked_ok}/{len(checks)}"
        lines.append(line)
        trust = entry.get("evidence_trust_gate") if isinstance(entry.get("evidence_trust_gate"), Mapping) else {}
        if trust:
            lines.append(
                "  evidence trust: qualified="
                f"{int(trust.get('qualified') or 0)} rejected={int(trust.get('rejected') or 0)} "
                f"near-duplicates={int(trust.get('near_duplicates_collapsed') or 0)}"
            )
        grounding = trace.get("source_grounding_gate") if isinstance(trace.get("source_grounding_gate"), Mapping) else {}
        if grounding:
            lines.append(
                "  source grounding: verified="
                f"{int(grounding.get('verified') or 0)} mismatches={int(grounding.get('explicit_mismatches_rejected') or 0)} "
                f"uncertain={int(grounding.get('uncertain_but_not_rejected') or 0)}"
            )
        if retrieval:
            lines.append(f"  retrieval query: {retrieval[:500]}")
        if relevance and relevance != retrieval:
            lines.append(f"  relevance query: {relevance[:500]}")
        if successful:
            lines.append("  successful: " + ", ".join(successful[:12]))
        if failed:
            compact_failed = []
            for row in failed[:8]:
                label = _clean(row.get("source") or row.get("name") or row.get("provider") or "source")
                reason = _clean(row.get("error") or row.get("reason") or row.get("status"))
                compact_failed.append(f"{label}({reason[:100]})" if reason else label)
            lines.append("  failed: " + ", ".join(compact_failed))
        query_runs = [x for x in (trace.get("query_runs") or []) if isinstance(x, Mapping)]
        for run in query_runs[:6]:
            run_label = _clean(run.get("label") or "QUERY")
            run_query = _clean(run.get("retrieval_query"))
            run_success = [str(x) for x in (run.get("successful_sources") or []) if _clean(x)]
            run_failed = [x for x in (run.get("failed_sources") or []) if isinstance(x, Mapping)]
            suffix = f"sources ok={len(run_success)} failed={len(run_failed)}"
            lines.append(f"  query run {run_label}: {run_query[:420] or '[empty]'} | {suffix}")
    return "\n".join(lines)

def build_handoff_text(item: Mapping[str, Any]) -> str:
    history = [x for x in (item.get("history") or []) if isinstance(x, Mapping)]
    latest = history[-1] if history else {}
    previous = history[-2] if len(history) >= 2 else {}
    coverage = _coverage_for_item(item)

    def bullets(values: Sequence[Any], fallback: str) -> str:
        cleaned = [_clean(x) for x in values if _clean(x)]
        return "\n".join(f"- {x}" for x in cleaned) if cleaned else f"- {fallback}"

    context_lines = _context_lines(item)
    source_kind = _clean(item.get("source_kind")).upper()
    founder_submitted = source_kind in CURATED_SOURCE_KINDS
    context_heading = "SUBMITTED OPPORTUNITY CONTEXT — UNVALIDATED" if founder_submitted else "IMPORTED BACKLOG CONTEXT — UNVALIDATED"
    context_text = "\n".join(f"- {line}" for line in context_lines) if context_lines else (
        "- 沒有額外提交脈絡。" if founder_submitted else "- 沒有額外 legacy context。"
    )

    accumulated = _handoff_accumulated_cards(item, limit=10)
    accumulated_text = "\n".join(_format_handoff_card(row) for row in accumulated) if accumulated else "- 目前沒有可列出的累積 evidence card。"

    counter_rows = _aggregate_history_cards(item, ("counterevidence",), limit=8, newest_first=True)
    counter_text = "\n".join(_format_handoff_card(row) for row in counter_rows) if counter_rows else "- 目前沒有列出的 counterevidence card；不代表不存在。"

    latest_rows: list[dict[str, Any]] = []
    if latest:
        for lane in ("human_comments", "products", "repos", "supporting", "counterevidence"):
            for row in (latest.get(lane) or [])[:2]:
                if not isinstance(row, Mapping):
                    continue
                card = dict(row)
                card["research_job"] = _clean(latest.get("job"))
                latest_rows.append(card)
                if len(latest_rows) >= 6:
                    break
            if len(latest_rows) >= 6:
                break
    latest_evidence_text = "\n".join(_format_handoff_card(row) for row in latest_rows) if latest_rows else "- 最新一輪沒有新的 evidence card。"

    previous_line = "這是第一次累積摘要。"
    if previous:
        previous_line = (
            f"上一輪：{previous.get('job')} / {previous.get('status')} / "
            f"useful={int((previous.get('counts') or {}).get('useful') or 0)}"
        )
    latest_line = "尚未執行研究。"
    if latest:
        latest_line = (
            f"最新：{latest.get('job')} / {latest.get('status')} / "
            f"useful={int((latest.get('counts') or {}).get('useful') or 0)} / "
            f"counter={int((latest.get('counts') or {}).get('counter') or 0)}"
        )

    timeline = []
    for entry in history[-8:]:
        cycle_tag = " | prior-cycle" if bool(entry.get("coverage_superseded", False)) else ""
        timeline.append(
            f"- {entry.get('job')} | {entry.get('status')}{cycle_tag} | useful={int((entry.get('counts') or {}).get('useful') or 0)} "
            f"human={int((entry.get('counts') or {}).get('human') or 0)} solutions={int((entry.get('counts') or {}).get('products') or 0) + int((entry.get('counts') or {}).get('repos') or 0)} "
            f"counter={int((entry.get('counts') or {}).get('counter') or 0)}"
        )
    timeline_text = "\n".join(timeline) if timeline else "- 尚無研究歷史。"

    return "\n".join([
        "SIGNALFORGE HANDOFF",
        "",
        "OPPORTUNITY",
        _clean(item.get("title")) or "Untitled",
        "",
        "PROBLEM / IDEA",
        _clean(item.get("description")) or "(未提供)",
        "",
        context_heading,
        context_text,
        "",
        "CURRENT STATE",
        f"{_clean(item.get('auto_status')) or 'NEW'} — {_clean(item.get('current_call')) or '尚未研究'}",
        "",
        "WHY",
        _clean(item.get("why")) or "尚未形成 research-state 說明。",
        "",
        "RESEARCH COVERAGE",
        f"completed={len(coverage.get('completed_jobs') or [])}/{len(JOB_ORDER)} | unique evidence={int(coverage.get('unique_evidence') or 0)} | "
        f"human={int(coverage.get('unique_human') or 0)} | solutions={int(coverage.get('unique_solutions') or 0)} | counter={int(coverage.get('unique_counter') or 0)}",
        "這只是 research coverage / review priority，不是 market score，也不是市場驗證。",
        "",
        "WHAT WE KNOW FROM RETRIEVED MATERIAL",
        bullets(list(item.get("known") or []), "尚未有可陳述的已知；不要自行補市場故事。"),
        "",
        "WHAT IS STILL UNKNOWN / GAPS",
        bullets(list(item.get("unknown") or []), "尚未整理。"),
        "",
        "ACCUMULATED IMPORTANT EVIDENCE",
        accumulated_text,
        "",
        "ACCUMULATED COUNTEREVIDENCE",
        counter_text,
        "",
        "RESEARCH HISTORY",
        timeline_text,
        "",
        "LATEST DELTA",
        previous_line,
        latest_line,
        latest_evidence_text,
        "",
        "RESEARCH TRACE / AUDIT",
        _format_research_trace_for_handoff(history[-5:]),
        "",
        "CURRENT BIGGEST QUESTION",
        _clean(item.get("next_question")) or "目前沒有自動研究下一題；請判斷是否需要真人市場驗證。",
        "",
        "INSTRUCTIONS FOR CHATGPT",
        "請只根據以上 SignalForge 累積狀態更新判斷，不要重新假設已完成的研究。",
        "清楚區分：直接證據、合理推論、未知、反面證據。",
        ("Submitted opportunity context 只是你／AI 提出的研究假設，不可當成已驗證市場事實。" if founder_submitted else "Imported backlog context 只是舊系統脈絡，不可當成已驗證市場事實。"),
        "不要把搜尋 trace 當成已驗證需求、WTP 或市場規模；沒有金額證據時不要估。",
        "如果目前還不足以做產品決策，請指出最值得取得的下一份外部市場證據。",
    ])


def backlog_view(
    repo: str | Path = ".",
    *,
    q: str = "",
    status: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    order = list(store.get("order") or [])
    query = _clean(q).lower()
    status_filter = _clean(status).upper()

    all_rows: list[dict[str, Any]] = []
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    for item_id in order:
        item = items.get(item_id)
        if isinstance(item, Mapping):
            row = _item_for_list(item)
            row["freshness"] = _freshness_state(item, automation)
            all_rows.append(row)

    # Founder items first, then active auto research, then new, then parked/source-limited.
    # REVIEW_READY ordering uses research completeness only; it intentionally does NOT resurrect
    # old market/opportunity scores as a new market judgment. NEW keeps import order so batch work
    # remains deterministic.
    priority = {
        "REVIEW_READY": 0,
        "AUTO_RESEARCH": 1,
        "RESEARCHING": 1,
        "NEW": 2,
        "SOURCE_LIMITED": 3,
        "PARKED_WEAK_SIGNAL": 4,
        "PARKED_NO_PUBLIC_SIGNAL": 5,
    }
    def row_sort_key(x: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            priority.get(_clean(x.get("auto_status")).upper(), 9),
            -int(x.get("review_priority") or 0) if _clean(x.get("auto_status")).upper() == "REVIEW_READY" else _rank_value(x.get("import_rank")),
            _clean(x.get("title")).lower(),
        )

    all_rows.sort(key=row_sort_key)
    rows = [
        row for row in all_rows
        if (not query or query in _clean(f"{row.get('title')} {row.get('description')}").lower())
        and (not status_filter or _clean(row.get("auto_status")).upper() == status_filter)
    ]

    counts: dict[str, int] = {}
    for item in items.values():
        if isinstance(item, Mapping):
            key = _clean(item.get("auto_status")).upper() or "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1
    # Founder Inbox is a global work queue, not a view of the currently filtered list. Searching
    # or filtering the Backlog must never hide work that still needs Founder attention.
    founder_attention_total = sum(1 for row in all_rows if row.get("needs_founder"))
    founder_inbox = [row for row in all_rows if row.get("needs_founder")][:3]
    for row in founder_inbox:
        row["review_reason"] = (
            f"公開研究已完成 {len((row.get('research_coverage') or {}).get('completed_jobs') or [])}/{len(JOB_ORDER)} 個 lanes；"
            f"累積 {(row.get('research_coverage') or {}).get('unique_evidence', 0)} 組不重複材料。"
        )
    worker_view = dict(store.get("worker") or {})
    worker_view["active_count"] = len([row for row in (worker_view.get("active_jobs") or []) if isinstance(row, Mapping)])
    worker_view["queued_jobs_estimate"] = _pending_job_estimate(store)
    worker_view["max_concurrency"] = max(1, min(int(automation.get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY), _MAX_RESEARCH_CONCURRENCY))
    return {
        "engine_version": ENGINE_VERSION,
        "status": "OK",
        "total": len(items),
        "filtered": len(rows),
        "counts": counts,
        "founder_inbox": founder_inbox,
        "founder_attention_total": founder_attention_total,
        "items": rows[: max(1, min(int(limit or 1000), 2000))],
        "worker": worker_view,
        "automation": dict(automation),
        "legacy_archive_summary": dict(store.get("legacy_archive_summary") or {}),
        "import_warnings": list((store.get("sync_metadata") or {}).get("import_warnings") or []),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def backlog_detail(repo: str | Path, item_id: str) -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, Mapping):
        return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    row = _item_for_view(item, include_history=True, include_handoff=True)
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    row["freshness"] = _freshness_state(item, automation)
    return {"status": "OK", "item": row, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def add_ideas(repo: str | Path, ideas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return sync_backlog(repo, ideas=ideas)


def request_stop(repo: str | Path = ".") -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    worker = store.setdefault("worker", {})
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    worker["stop_requested"] = True
    automation["paused_by_founder"] = True
    automation["last_founder_pause_at"] = _now()
    save_store(repo, store)
    return {"status": "STOP_REQUESTED", "worker": dict(worker), "automation": dict(automation), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def resume_auto_run(repo: str | Path = ".") -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    worker = store.setdefault("worker", {})
    automation["auto_run_enabled"] = True
    automation["paused_by_founder"] = False
    automation["last_founder_resume_at"] = _now()
    worker["stop_requested"] = False
    save_store(repo, store)
    return {"status": "AUTO_RUN_RESUMED", "automation": dict(automation), "market_truth_writes": 0}


def auto_run_allowed(repo: str | Path = ".") -> bool:
    store = load_store(repo, repair_worker=False)
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    return (
        bool(automation.get("auto_run_enabled", True))
        and not bool(automation.get("paused_by_founder", False))
        and not _source_circuit_waiting(store)
    )


def has_pending_work(repo: str | Path = ".") -> bool:
    store = load_store(repo, repair_worker=False)
    return _select_next_item(store) is not None


def note_auto_start(repo: str | Path = ".") -> None:
    store = load_store(repo, repair_worker=False)
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    automation["last_auto_start_at"] = _now()
    save_store(repo, store)


def acknowledge_handoff(repo: str | Path, item_id: str, expected_hash: str | None = None) -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, dict):
        return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    handoff = build_handoff_text(item)
    handoff_hash = hashlib.sha256(handoff.encode("utf-8")).hexdigest()[:24]
    if not _clean(expected_hash):
        return {"status": "HANDOFF_HASH_REQUIRED", "id": item_id, "current_handoff_hash": handoff_hash, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    if _clean(expected_hash) != handoff_hash:
        return {"status": "STALE_HANDOFF", "id": item_id, "current_handoff_hash": handoff_hash, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    item["founder_reviewed_at"] = _now()
    item["founder_reviewed_research_count"] = len(item.get("history") or [])
    item["founder_reviewed_handoff_hash"] = handoff_hash
    item["needs_founder"] = False
    item["latest_change"] = "HANDOFF_COPIED_TO_FOUNDER"
    item["updated_at"] = _now()
    save_store(repo, store)
    return {"status": "ACKNOWLEDGED", "id": item_id, "handoff_hash": handoff_hash, "founder_reviewed_at": item["founder_reviewed_at"], "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}



def _latest_completed_research_at(item: Mapping[str, Any]) -> datetime | None:
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    for row in reversed(history):
        completed = _parse_time(row.get("completed_at"))
        if completed is not None:
            return completed
    return _parse_time(item.get("updated_at")) or _parse_time(item.get("created_at"))


def _freshness_policy_for_item(item: Mapping[str, Any], automation: Mapping[str, Any]) -> tuple[int, str] | None:
    if not bool(automation.get("freshness_enabled", True)):
        return None
    status = _clean(item.get("auto_status")).upper()
    if status == "REVIEW_READY":
        ttl = max(3600, int(automation.get("review_ready_refresh_seconds") or _REVIEW_READY_FRESHNESS_SECONDS))
        # REVIEW_READY already has a complete five-lane history. A focused counterevidence refresh
        # is the cheapest way to catch new native features/incumbents/"already solved" changes.
        return ttl, "COUNTEREVIDENCE"
    if status == "PARKED_WEAK_SIGNAL":
        ttl = max(3600, int(automation.get("parked_weak_refresh_seconds") or _PARKED_WEAK_FRESHNESS_SECONDS))
        return ttl, "BASELINE"
    if status == "PARKED_NO_PUBLIC_SIGNAL":
        ttl = max(3600, int(automation.get("parked_no_signal_refresh_seconds") or _PARKED_NO_SIGNAL_FRESHNESS_SECONDS))
        return ttl, "BASELINE"
    return None


def _freshness_state(item: Mapping[str, Any], automation: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    policy = _freshness_policy_for_item(item, automation)
    latest = _latest_completed_research_at(item)
    if policy is None:
        return {
            "status": "NOT_SCHEDULED",
            "last_research_at": latest.isoformat() if latest else None,
            "next_refresh_after": None,
            "refresh_job": None,
        }
    ttl, job = policy
    base = latest or datetime.now(timezone.utc)
    next_after = base + timedelta(seconds=ttl)
    current = now or datetime.now(timezone.utc)
    return {
        "status": "STALE_RECHECK_DUE" if next_after <= current else "FRESH",
        "last_research_at": latest.isoformat() if latest else None,
        "next_refresh_after": next_after.isoformat(),
        "refresh_job": job,
        "ttl_seconds": ttl,
    }


def _select_stale_refresh(store: Mapping[str, Any], *, now: datetime | None = None) -> tuple[str, str] | None:
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    order = list(store.get("order") or [])
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    current = now or datetime.now(timezone.utc)
    best: tuple[datetime, str, str] | None = None
    for item_id in order:
        item = items.get(item_id)
        if not isinstance(item, Mapping):
            continue
        state = _freshness_state(item, automation, now=current)
        if state.get("status") != "STALE_RECHECK_DUE":
            continue
        job = _clean(state.get("refresh_job")).upper()
        due = _parse_time(state.get("next_refresh_after"))
        if job not in JOB_ORDER or due is None:
            continue
        candidate = (due, str(item_id), job)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return (best[1], best[2]) if best else None


def _pending_job_estimate(store: Mapping[str, Any]) -> int:
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    now = datetime.now(timezone.utc)
    count = 0
    for item in items.values():
        if not isinstance(item, Mapping):
            continue
        status = _clean(item.get("auto_status")).upper()
        if status in {"NEW", "AUTO_RESEARCH"}:
            count += 1
        elif status == "SOURCE_LIMITED" and _source_retry_due(item, now=now):
            count += 1
        elif _freshness_state(item, store.get("automation") if isinstance(store.get("automation"), Mapping) else {}, now=now).get("status") == "STALE_RECHECK_DUE":
            count += 1
    return count


def _select_next_item(store: Mapping[str, Any]) -> tuple[str, str] | None:
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    order = list(store.get("order") or [])
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}

    new_choice: tuple[str, str] | None = None
    auto_choice: tuple[str, str] | None = None
    auto_stage = len(JOB_ORDER) + 1
    for item_id in order:
        item = items.get(item_id)
        if not isinstance(item, Mapping):
            continue
        status = _clean(item.get("auto_status")).upper()
        if new_choice is None and status == "NEW":
            new_choice = (item_id, "BASELINE")
        if status == "AUTO_RESEARCH":
            job = _clean(item.get("next_job")).upper()
            if job in JOB_ORDER:
                stage = JOB_ORDER.index(job)
                if auto_choice is None or stage < auto_stage:
                    auto_choice = (item_id, job)
                    auto_stage = stage

    # Initial import contract is unchanged: every direction gets one baseline before any one
    # direction is deepened. Deep research is also breadth-first by lane: lower-stage jobs run
    # across eligible opportunities before an earlier item can consume the next lane as well.
    # Once that initial wave has drained at least once, newly arriving
    # candidates may jump in only as a bounded burst. Otherwise a continuously growing upstream
    # candidate feed can starve already-promising opportunities forever.
    initial_complete = bool(automation.get("initial_baseline_wave_complete", False))
    if not initial_complete and new_choice is not None:
        return new_choice

    if initial_complete and new_choice is not None and auto_choice is not None:
        burst_limit = max(1, int(automation.get("post_initial_new_burst_limit") or _POST_INITIAL_NEW_BURST))
        new_since_deep = max(0, int(automation.get("post_initial_new_since_deep") or 0))
        return new_choice if new_since_deep < burst_limit else auto_choice
    if auto_choice is not None:
        return auto_choice
    if new_choice is not None:
        return new_choice

    # Source-limited lanes are retried only after their cooldown and only after current promising
    # auto-research/new-arrival work has been drained. Cooldown is a minimum wait, not a deadline.
    now = datetime.now(timezone.utc)
    for item_id in order:
        item = items.get(item_id)
        if isinstance(item, Mapping) and _source_retry_due(item, now=now):
            job = _clean(item.get("next_job")).upper()
            if job in JOB_ORDER:
                return item_id, job

    # Market-state freshness is intentionally lowest priority. Finish newly submitted/deep research
    # first, then spend spare capacity rechecking terminal opportunities whose public-market view
    # is stale. Historical evidence is preserved; only the current market state is refreshed.
    stale = _select_stale_refresh(store, now=now)
    if stale is not None:
        return stale
    return None


def _record_scheduler_progress(store: dict[str, Any], *, job: str, was_new: bool, initial_complete_before: bool) -> None:
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    if not bool(automation.get("initial_baseline_wave_complete", False)):
        has_pending_baseline = any(
            isinstance(item, Mapping)
            and (
                _clean(item.get("auto_status")).upper() == "NEW"
                or (
                    _clean(item.get("auto_status")).upper() == "RESEARCHING"
                    and _clean(item.get("latest_change")).upper() == "RESEARCH_BASELINE_STARTED"
                )
            )
            for item in items.values()
        )
        if not has_pending_baseline:
            automation["initial_baseline_wave_complete"] = True
            automation["post_initial_new_since_deep"] = 0

    # Count only baselines that arrived after the initial all-directions wave was already done.
    # A deep lane resets the burst budget so both streams make bounded progress.
    if _clean(job).upper() != "BASELINE":
        automation["post_initial_new_since_deep"] = 0
    elif initial_complete_before and was_new:
        automation["post_initial_new_since_deep"] = max(0, int(automation.get("post_initial_new_since_deep") or 0)) + 1


async def run_batch(
    repo: str | Path,
    *,
    research_fn: Callable[[str, str], Awaitable[Mapping[str, Any]]],
    max_jobs: int = 200,
    delay_seconds: float = 0.15,
    concurrency: int | None = None,
) -> dict[str, Any]:
    """Run a bounded research batch with a small parallel worker pool.

    HOTFIX11 reserves a wave atomically in the persistent store, executes only the network/retrieval
    portion concurrently, then commits completed results back serially. This keeps one JSON source of
    truth while avoiding the old one-job-at-a-time bottleneck.
    """
    repo = str(Path(repo).resolve())
    max_jobs = max(1, min(int(max_jobs or 200), 1000))

    store = load_store(repo, repair_worker=True)
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    configured = int(automation.get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY)
    concurrency = configured if concurrency is None else int(concurrency)
    concurrency = max(1, min(concurrency, _MAX_RESEARCH_CONCURRENCY, max_jobs))
    worker = store.setdefault("worker", {})
    worker.update({
        "status": "RUNNING",
        "started_at": _now(),
        "finished_at": None,
        "current_item_id": None,
        "current_job": None,
        "jobs_completed": 0,
        "jobs_requested": max_jobs,
        "last_error": None,
        "stop_requested": False,
        "retry_attempts": 0,
        "active_jobs": [],
        "active_count": 0,
        "max_concurrency": concurrency,
        "queued_jobs_estimate": _pending_job_estimate(store),
        "last_wave_started_at": None,
        "last_wave_completed_at": None,
    })
    worker.setdefault("consecutive_source_limited", 0)
    save_store(repo, store)

    completed = 0
    try:
        while completed < max_jobs:
            store = load_store(repo, repair_worker=False)
            worker = store.setdefault("worker", {})
            automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
            if worker.get("stop_requested") or bool(automation.get("paused_by_founder", False)):
                worker["status"] = "STOPPED"
                worker["finished_at"] = _now()
                worker["current_item_id"] = None
                worker["current_job"] = None
                worker["active_jobs"] = []
                worker["active_count"] = 0
                worker["queued_jobs_estimate"] = _pending_job_estimate(store)
                save_store(repo, store)
                break

            wave_limit = min(concurrency, max_jobs - completed)
            reserved: list[dict[str, Any]] = []
            first_job: str | None = None
            wave_started = _now()

            # Reserve one breadth-first lane per wave. This preserves the existing scheduler
            # invariant: every opportunity gets its baseline before deep lanes race ahead, and
            # lower-stage deep research is spread across opportunities before the next stage.
            while len(reserved) < wave_limit:
                selected = _select_next_item(store)
                if not selected:
                    break
                item_id, job = selected
                if first_job is not None and job != first_job:
                    break
                item = (store.get("items") or {}).get(item_id)
                if not isinstance(item, dict):
                    break
                first_job = job if first_job is None else first_job
                automation_before = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
                initial_complete_before = bool(automation_before.get("initial_baseline_wave_complete", False))
                original_status = _clean(item.get("auto_status")).upper()
                was_new = original_status == "NEW"
                freshness = _freshness_state(item, automation_before)
                is_freshness_refresh = freshness.get("status") == "STALE_RECHECK_DUE"

                item["auto_status"] = "RESEARCHING"
                item["current_call"] = "SignalForge 正在更新市場狀態" if is_freshness_refresh else "SignalForge 正在研究"
                item["needs_founder"] = False
                item["latest_change"] = f"RESEARCH_{job}_STARTED"
                item["updated_at"] = _now()
                if is_freshness_refresh:
                    item["freshness_refresh_started_at"] = wave_started
                    item["freshness_refresh_job"] = job

                title, description = _job_prompt(item, job)
                reserved.append({
                    "item_id": item_id,
                    "job": job,
                    "title": title,
                    "description": description,
                    "started_at": _now(),
                    "was_new": was_new,
                    "initial_complete_before": initial_complete_before,
                    "freshness_refresh": is_freshness_refresh,
                })

            if not reserved:
                worker["status"] = "IDLE"
                worker["finished_at"] = _now()
                worker["current_item_id"] = None
                worker["current_job"] = None
                worker["active_jobs"] = []
                worker["active_count"] = 0
                worker["queued_jobs_estimate"] = _pending_job_estimate(store)
                save_store(repo, store)
                break

            worker["active_jobs"] = [
                {"item_id": row["item_id"], "job": row["job"], "started_at": row["started_at"]}
                for row in reserved
            ]
            worker["active_count"] = len(reserved)
            worker["max_concurrency"] = concurrency
            worker["current_item_id"] = reserved[0]["item_id"]
            worker["current_job"] = reserved[0]["job"]
            worker["last_wave_started_at"] = wave_started
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            save_store(repo, store)

            async def execute_one(entry: Mapping[str, Any]) -> dict[str, Any]:
                result: Mapping[str, Any] | None = None
                last_exc: Exception | None = None
                retry_count = 0
                max_attempts = 2
                for attempt in range(max_attempts):
                    try:
                        candidate = await research_fn(str(entry["title"]), str(entry["description"]))
                        if not isinstance(candidate, Mapping):
                            raise RuntimeError("research_fn returned non-mapping result")
                        candidate = _quality_filter_result(
                            (load_store(repo, repair_worker=False).get("items") or {}).get(str(entry["item_id"])) or {},
                            str(entry["job"]),
                            candidate,
                        )
                        result = candidate
                        if not _research_transport_limited(candidate) or attempt + 1 >= max_attempts:
                            break
                        retry_count += 1
                        await asyncio.sleep(max(0.0, delay_seconds) + 0.2 * (2 ** attempt))
                    except Exception as exc:
                        last_exc = exc
                        if attempt + 1 < max_attempts:
                            retry_count += 1
                            await asyncio.sleep(max(0.0, delay_seconds) + 0.2 * (2 ** attempt))
                            continue
                        break
                return {
                    "result": result,
                    "exception": last_exc,
                    "retry_count": retry_count,
                    "completed_at": _now(),
                }

            outcomes = await asyncio.gather(*(execute_one(row) for row in reserved))

            # Commit the whole wave against the latest store so a concurrent Founder pause/import
            # cannot be overwritten by a stale pre-network snapshot.
            store = load_store(repo, repair_worker=False)
            worker = store.setdefault("worker", {})
            circuit_opened = False
            for entry, outcome in zip(reserved, outcomes):
                item_id = str(entry["item_id"])
                job = str(entry["job"])
                live_item = (store.get("items") or {}).get(item_id)
                worker["retry_attempts"] = int(worker.get("retry_attempts") or 0) + int(outcome.get("retry_count") or 0)
                result = outcome.get("result")

                if result is None:
                    exc = outcome.get("exception") or RuntimeError("research execution failed without a result")
                    if isinstance(live_item, dict):
                        live_item["auto_status"] = "SOURCE_LIMITED"
                        live_item["current_call"] = "來源不足：先不要下結論"
                        live_item["why"] = f"研究執行失敗（已 bounded retry）：{type(exc).__name__}: {exc}"
                        live_item["next_job"] = job
                        live_item["next_question"] = "等來源恢復後重跑同一 research lane；不能把這次失敗當成沒有市場。"
                        _schedule_source_retry(live_item, job, live_item["why"])
                        live_item["needs_founder"] = False
                        live_item["latest_change"] = f"RESEARCH_{job}_FAILED_AFTER_RETRY"
                        live_item["updated_at"] = _now()
                    worker["last_error"] = f"{type(exc).__name__}: {exc}"
                    circuit_opened = _record_source_health(store, limited=True, reason=worker["last_error"]) or circuit_opened
                else:
                    assert isinstance(result, Mapping)
                    if isinstance(live_item, dict):
                        history = live_item.setdefault("history", [])
                        _, predicted_status, _, _ = _next_job_after(live_item, job, result)
                        snapshot = _history_snapshot(job, result, str(entry["started_at"]), str(outcome.get("completed_at") or _now()))
                        if predicted_status == "SOURCE_LIMITED":
                            snapshot["coverage_complete"] = False
                            snapshot["coverage_reason"] = "SOURCE_COVERAGE_INSUFFICIENT_NOT_COMPLETE"
                        if bool(entry.get("freshness_refresh")):
                            snapshot["freshness_refresh"] = True
                            snapshot["freshness_refresh_reason"] = "TERMINAL_MARKET_STATE_RECHECK"
                        history.append(snapshot)
                        while len(history) > 24:
                            drop_index = next((i for i, row in enumerate(history) if isinstance(row, Mapping) and row.get("coverage_complete") is False), 0)
                            del history[drop_index]
                        _derive_state(live_item, job, result)
                        if bool(entry.get("freshness_refresh")):
                            live_item["freshness_last_refresh_at"] = str(outcome.get("completed_at") or _now())
                            live_item["freshness_refresh_job"] = None
                    transport_limited_now = _research_transport_limited(result)
                    circuit_opened = _record_source_health(
                        store,
                        limited=bool(transport_limited_now),
                        reason=("transport/source outage while researching " + job if transport_limited_now else ""),
                    ) or circuit_opened

                completed += 1
                _record_scheduler_progress(
                    store,
                    job=job,
                    was_new=bool(entry.get("was_new")),
                    initial_complete_before=bool(entry.get("initial_complete_before")),
                )

            worker = store.setdefault("worker", {})
            worker["jobs_completed"] = completed
            worker["active_jobs"] = []
            worker["active_count"] = 0
            worker["current_item_id"] = None
            worker["current_job"] = None
            worker["last_wave_completed_at"] = _now()
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            paused_now = bool((store.get("automation") or {}).get("paused_by_founder", False))
            stopped_now = bool(worker.get("stop_requested"))
            if circuit_opened:
                worker["status"] = "SOURCE_CIRCUIT_OPEN"
            elif paused_now or stopped_now:
                worker["status"] = "STOPPED"
            else:
                worker["status"] = "RUNNING"
            save_store(repo, store)

            if circuit_opened or paused_now or stopped_now:
                break
            if completed < max_jobs:
                await asyncio.sleep(max(0.0, delay_seconds))

        store = load_store(repo, repair_worker=False)
        worker = store.setdefault("worker", {})
        if worker.get("status") == "RUNNING":
            worker["status"] = "BATCH_LIMIT_REACHED" if _select_next_item(store) else "IDLE"
            worker["finished_at"] = _now()
            worker["current_item_id"] = None
            worker["current_job"] = None
            worker["active_jobs"] = []
            worker["active_count"] = 0
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            save_store(repo, store)
        return {
            "status": worker.get("status"),
            "jobs_completed": completed,
            "max_concurrency": concurrency,
            "queued_jobs_estimate": int(worker.get("queued_jobs_estimate") or 0),
            "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        }
    except Exception as exc:
        store = load_store(repo, repair_worker=False)
        worker = store.setdefault("worker", {})
        worker["status"] = "FAILED"
        worker["finished_at"] = _now()
        worker["current_item_id"] = None
        worker["current_job"] = None
        worker["active_jobs"] = []
        worker["active_count"] = 0
        worker["queued_jobs_estimate"] = _pending_job_estimate(store)
        worker["last_error"] = f"{type(exc).__name__}: {exc}"
        save_store(repo, store)
        raise


async def run_continuous_session(
    repo: str | Path,
    *,
    research_fn: Callable[[str, str], Awaitable[Mapping[str, Any]]],
    batch_size: int = 500,
    session_job_cap: int = 5000,
    delay_seconds: float = 0.15,
) -> dict[str, Any]:
    """Drain the immediate queue across multiple bounded batches without Founder re-clicks.

    One session is capped so a runaway backlog cannot monopolize the API process forever.
    Pending work is intentionally preserved; an idle poll or later resume can start a fresh session.
    """
    repo = str(Path(repo).resolve())
    batch_size = max(1, min(int(batch_size or 500), 1000))
    session_job_cap = max(1, min(int(session_job_cap or 5000), 5000))
    total_completed = 0
    batches_completed = 0
    final_status = "IDLE"

    while total_completed < session_job_cap:
        store = load_store(repo, repair_worker=True)
        automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
        worker = store.setdefault("worker", {})
        if bool(automation.get("paused_by_founder", False)) or bool(worker.get("stop_requested")):
            final_status = "STOPPED"
            break
        if _select_next_item(store) is None:
            final_status = "IDLE"
            break

        remaining = session_job_cap - total_completed
        this_batch = min(batch_size, remaining)
        result = await run_batch(
            repo,
            research_fn=research_fn,
            max_jobs=this_batch,
            delay_seconds=delay_seconds,
        )
        done = int(result.get("jobs_completed") or 0)
        total_completed += done
        batches_completed += 1
        batch_status = str(result.get("status") or "IDLE")
        if done <= 0:
            final_status = batch_status
            break
        if batch_status == "SOURCE_CIRCUIT_OPEN":
            final_status = batch_status
            break

        store = load_store(repo, repair_worker=False)
        worker = store.setdefault("worker", {})
        worker["session_jobs_completed"] = total_completed
        worker["batches_completed"] = batches_completed
        worker["batch_size"] = batch_size
        worker["session_job_cap"] = session_job_cap
        worker["safety_cap_reached"] = False
        worker["pending_after_session"] = _select_next_item(store) is not None
        worker["queued_jobs_estimate"] = _pending_job_estimate(store)
        worker["max_concurrency"] = max(1, min(int((store.get("automation") or {}).get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY), _MAX_RESEARCH_CONCURRENCY))
        save_store(repo, store)

        if not worker["pending_after_session"]:
            final_status = "IDLE"
            break

    store = load_store(repo, repair_worker=False)
    worker = store.setdefault("worker", {})
    pending = _select_next_item(store) is not None
    cap_reached = total_completed >= session_job_cap and pending
    if cap_reached:
        final_status = "SAFETY_CAP_REACHED"
    elif final_status not in {"STOPPED", "FAILED"} and not pending:
        final_status = "IDLE"
    worker["status"] = final_status
    worker["finished_at"] = _now()
    worker["current_item_id"] = None
    worker["current_job"] = None
    worker["active_jobs"] = []
    worker["active_count"] = 0
    worker["queued_jobs_estimate"] = _pending_job_estimate(store)
    worker["max_concurrency"] = max(1, min(int((store.get("automation") or {}).get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY), _MAX_RESEARCH_CONCURRENCY))
    worker["jobs_completed"] = total_completed
    worker["jobs_requested"] = session_job_cap
    worker["session_jobs_completed"] = total_completed
    worker["batches_completed"] = batches_completed
    worker["batch_size"] = batch_size
    worker["session_job_cap"] = session_job_cap
    worker["safety_cap_reached"] = cap_reached
    worker["pending_after_session"] = pending
    save_store(repo, store)
    return {
        "status": final_status,
        "jobs_completed": total_completed,
        "batches_completed": batches_completed,
        "batch_size": batch_size,
        "session_job_cap": session_job_cap,
        "safety_cap_reached": cap_reached,
        "pending_after_session": pending,
        "max_concurrency": int(worker.get("max_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY),
        "queued_jobs_estimate": int(worker.get("queued_jobs_estimate") or 0),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def reset_store_for_acceptance(repo: str | Path) -> None:
    """Acceptance-only helper; never exposed as an API route."""
    path = _store_path(repo)
    with _LOCK:
        if path.exists():
            path.unlink()

# ============================================================================
# TRACKING PIVOT V2
# SignalForge is a continuous related-material collector, not a market analyst.
# The legacy V1.6 research machinery remains above for reversible history/audit
# compatibility, but the active scheduler/state/view contract below replaces it.
# ============================================================================

ENGINE_VERSION = "signalforge-behavior-trend-continuous-v1"
TRUTH_BOUNDARY = (
    "SIGNALFORGE_TRACKS_RELATED_PUBLIC_MATERIAL_ONLY;_"
    "RELEVANCE_FILTERING_IS_NOT_MARKET_ANALYSIS;_"
    "SIGNALFORGE_DOES_NOT_DECIDE_OPPORTUNITY_STRENGTH_WTP_OR_BUILD;_"
    "CHATGPT_AND_FOUNDER_OWN_ANALYSIS_AND_JUDGMENT"
)
_TRACKING_PIVOT_VERSION = "TRACKING_PIVOT_V2"
_TRACKING_SOURCE_EXPANSION_VERSION = "TRACKING_BEHAVIOR_TREND_V1"
_TRACKING_RELEVANCE_VERSION = "tracking-relevance-v2.5"
_TRACKING_BROAD_QUERY_FANOUT = 44
_TRACKING_REFRESH_QUERY_FANOUT = 20
_TRACKING_SOURCE_FAMILIES = (
    "general_web", "local_language", "public_discussions", "practitioner_communities",
    "vendor_support_communities", "domain_forums", "product_reviews", "app_marketplaces", "related_products",
    "manual_workarounds", "research_cases", "academic_sources",
    "b2b_operational_signals", "job_procurement_signals",
    "behavior_routines", "category_language", "switching_signals",
)
_TRACKING_INTERVAL_SECONDS = 12 * 3600
_TRACKING_MAX_LIBRARY_PER_CATEGORY = 500
_TRACKING_CATEGORIES = ("discussions", "products", "articles", "technical", "other")
_TRACKING_HISTORY_FIELDS = {
    "discussions": "human_comments",
    "products": "products",
    "articles": "supporting",
    "technical": "repos",
    "other": "counterevidence",
}
_TRACKING_BRIEF_FIELDS = {
    "discussions": "human_comments",
    "products": "similar_products",
    "articles": "supporting_evidence",
    "technical": "repo_solutions",
    "other": "counter_evidence",
}

_PRODUCT_CUES = (
    "software", "platform", "product", "tool", "service", "solution", "app", "saas",
    "pricing", "price", "plan", "subscription", "book a demo", "request a demo", "free trial",
)
_DISCUSSION_SOURCES = ("REDDIT", "HACKER_NEWS", "HACKER NEWS", "HN", "STACK_OVERFLOW", "FORUM", "DISCOURSE", "QUORA")
_TECHNICAL_SOURCES = ("GITHUB", "GITLAB", "STACK_OVERFLOW", "STACK OVERFLOW")
_ARTICLE_CUES = ("research", "study", "paper", "report", "case study", "news", "article", "journal", "survey")
_TRACKING_GENERIC_TERMS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "by", "can", "could", "do", "does", "for", "from",
    "have", "how", "in", "into", "is", "it", "may", "might", "of", "on", "or", "that", "the", "their", "this",
    "to", "use", "using", "with", "without", "work", "workflow", "process", "system", "data", "information", "problem",
    "issue", "manual", "build", "make", "manage", "management", "track", "tracking", "evidence", "package", "owner",
    "project", "lead", "business", "company", "customer", "user", "users", "people", "person",
}

_TRACKING_RESEARCH_QUALITY_VERSION = "TRACKING_RESEARCH_QUALITY_V2_5_5"
_TRACKING_AI_LINK_REQUIRED_FAMILIES = {
    "general_web", "public_discussions", "manual_workarounds",
    "related_products", "product_reviews", "research_cases",
}


def _tracking_profile_key_for_item(item: Mapping[str, Any]) -> str:
    """Retrieval/relevance profile only. Never a market-quality label."""
    text = " ".join((
        _clean(item.get("title")),
        _clean(item.get("description")),
        _research_base(item),
    )).lower()
    ai_anchor = any(x in text for x in (
        "chatgpt", "claude", "gemini", "llm", " ai ", "ai users", "ai assistant", "ai client",
    ))
    link_anchor = any(x in text for x in (
        "public link", "links", " link", "url", "webpage", "website", "youtube", "tiktok",
        "instagram", "reddit", "github issue", "hacker news", "pdf",
    ))
    access_anchor = any(x in text for x in (
        "can't access", "cannot access", "unable to access", "can't read", "cannot read",
        "read it", "read the", "context", "transcript", "copy-paste", "copy paste", "scraper",
        "browser extension", "mcp", "download", "upload",
    ))
    return "AI_PUBLIC_LINK_ACCESS" if ai_anchor and link_anchor and access_anchor else "GENERIC"


def _tracking_row_text_for_profile(row: Mapping[str, Any]) -> str:
    return " ".join(_clean(row.get(k)) for k in ("title", "excerpt", "snippet", "description", "text", "url")).lower()


def _tracking_ai_link_row_relevant(row: Mapping[str, Any]) -> bool:
    """High-recall thesis binding for AI/public-link access material."""
    text = _tracking_row_text_for_profile(row)
    ai = any(x in text for x in (
        "chatgpt", "openai", "claude", "anthropic", "gemini", "llm", "large language model", "ai assistant",
    ))
    source = any(x in text for x in (
        " link", "url", "webpage", "website", "youtube", "tiktok", "instagram", "reddit", "twitter", " x.com",
        "bluesky", "github", "hacker news", " pdf", "thread", "post",
    ))
    access = any(x in text for x in (
        "access", "read", "open", "browse", "fetch", "scrap", "extract", "summar", "context", "transcript",
        "caption", "copy paste", "copy-paste", "upload", "download", "extension", "mcp", "inaccessible", "blocked",
    ))
    return ai and source and access


def _tracking_quarantine_key(row: Mapping[str, Any]) -> str:
    return _tracking_card_key(row) or _sha_key(repr(sorted(row.items(), key=lambda kv: str(kv[0]))))


def _requalify_profile_material_library(item: dict[str, Any]) -> bool:
    """Move previously retained profile-mismatched rows out of the active material library.

    Rejected rows are preserved in a bounded quarantine for audit/history. They stop contributing to
    active counts and handoff material, but are not deleted from disk.
    """
    if _tracking_profile_key_for_item(item) != "AI_PUBLIC_LINK_ACCESS":
        return False
    if _clean(item.get("tracking_research_quality_version")) == _TRACKING_RESEARCH_QUALITY_VERSION:
        return False

    library = item.setdefault("material_library", _empty_material_library())
    quarantine = item.setdefault("material_quarantine", [])
    existing_q = {_tracking_quarantine_key(row) for row in quarantine if isinstance(row, Mapping)}
    changed = False
    rejected_count = 0
    now = _now()
    for category in _TRACKING_CATEGORIES:
        kept: list[dict[str, Any]] = []
        for raw in list(library.get(category) or []):
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            if _tracking_ai_link_row_relevant(row):
                kept.append(row)
                continue
            rejected_count += 1
            changed = True
            qrow = copy.deepcopy(row)
            qrow["quarantined_at"] = now
            qrow["quarantine_reason"] = "AI_PUBLIC_LINK_PROFILE_RELEVANCE_REJECTED"
            qrow["previous_category"] = category
            qrow["tracking_research_quality_version"] = _TRACKING_RESEARCH_QUALITY_VERSION
            qkey = _tracking_quarantine_key(qrow)
            if qkey not in existing_q:
                quarantine.append(qrow)
                existing_q.add(qkey)
        library[category] = kept

    if len(quarantine) > 300:
        del quarantine[: len(quarantine) - 300]
    item["tracking_research_quality_version"] = _TRACKING_RESEARCH_QUALITY_VERSION
    item["tracking_profile"] = "AI_PUBLIC_LINK_ACCESS"
    item["tracking_requalified_at"] = now
    item["tracking_requalified_rejected_count"] = rejected_count
    # The prior run used a broken truncated query. Queue exactly this affected direction for one
    # corrected source-expansion pass; do not globally requeue all tracked ideas.
    item["tracking_source_expansion_pending"] = True
    item["next_track_after"] = now
    if _clean(item.get("auto_status")).upper() not in {"SEARCHING", "SOURCE_LIMITED"}:
        item["auto_status"] = "TRACKING_DUE"
    item["current_call"] = "等待研究品質重跑"
    item["why"] = "V2.5.5 已撤出不相關舊材料，將用完整 AI×公開連結×讀取失敗×workaround facets 重新追蹤。"
    item["latest_change"] = "TRACKING_RESEARCH_QUALITY_V2_5_5_REQUALIFIED"
    item["updated_at"] = now
    _refresh_material_stats(item)
    return True


def _tracking_expansion_health(item: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """Decide whether source expansion really executed; never use evidence yield as market truth."""
    profile = _tracking_profile_key_for_item(item)
    trace = result.get("research_trace") if isinstance(result.get("research_trace"), Mapping) else {}
    runs = trace.get("query_runs") if isinstance(trace.get("query_runs"), list) else []
    attempted: set[str] = set()
    healthy: set[str] = set()
    for raw in runs:
        if not isinstance(raw, Mapping):
            continue
        family = _clean(raw.get("tracking_family"))
        if not family:
            continue
        attempted.add(family)
        status = _clean(raw.get("collection_status")).upper()
        successful = [x for x in (raw.get("successful_sources") or []) if _clean(x)]
        if status in {"PASS", "PARTIAL", "SUCCESS"} and successful:
            healthy.add(family)
    if profile == "AI_PUBLIC_LINK_ACCESS":
        required = set(_TRACKING_AI_LINK_REQUIRED_FAMILIES)
        missing_attempt = sorted(required - attempted)
        missing_healthy = sorted(required - healthy)
        complete = not missing_attempt and not missing_healthy
    else:
        required = set()
        missing_attempt = []
        missing_healthy = []
        # Preserve generic behavior: a completed bounded research result ends the one-time expansion.
        complete = True
    return {
        "profile": profile,
        "required_families": sorted(required),
        "attempted_families": sorted(attempted),
        "healthy_families": sorted(healthy),
        "missing_attempt_families": missing_attempt,
        "missing_healthy_families": missing_healthy,
        "complete": bool(complete),
        "meaning": "SOURCE_EXPANSION_EXECUTION_HEALTH_NOT_MARKET_VALIDATION",
    }


_v16_default_store = _default_store
_v16_load_store = load_store
_v16_new_item = _new_item
_v16_history_snapshot = _history_snapshot


def _default_store() -> dict[str, Any]:
    store = _v16_default_store()
    store["engine_version"] = ENGINE_VERSION
    store["truth_boundary"] = TRUTH_BOUNDARY
    automation = store.setdefault("automation", {})
    automation.update({
        "tracking_mode": "CONTINUOUS_RELATED_MATERIAL_DISCOVERY",
        "tracking_interval_seconds": _TRACKING_INTERVAL_SECONDS,
        "research_concurrency": _DEFAULT_RESEARCH_CONCURRENCY,
        "freshness_enabled": False,
        "source_expansion_version": _TRACKING_SOURCE_EXPANSION_VERSION,
        "broad_query_fanout": _TRACKING_BROAD_QUERY_FANOUT,
        "refresh_query_fanout": _TRACKING_REFRESH_QUERY_FANOUT,
        "source_families": list(_TRACKING_SOURCE_FAMILIES),
    })
    return store


def _empty_material_library() -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in _TRACKING_CATEGORIES}


def _tracking_card_key(row: Mapping[str, Any]) -> str:
    return _card_identity(row)


def _tracking_card(row: Mapping[str, Any], *, first_seen_at: str, last_seen_at: str | None = None) -> dict[str, Any]:
    card = _compact_card(row)
    card["first_seen_at"] = first_seen_at
    card["last_seen_at"] = last_seen_at or first_seen_at
    card["seen_count"] = max(1, int(row.get("seen_count") or 1))
    enriched = enrich_material(card, observed_at=last_seen_at or first_seen_at)
    return enriched


def _tracking_seen_cutoff(item: Mapping[str, Any]) -> datetime | None:
    return _parse_time(item.get("founder_reviewed_at") or item.get("tracking_last_reported_at"))


def _refresh_material_stats(item: dict[str, Any]) -> None:
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    cutoff = _tracking_seen_cutoff(item)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    counts: dict[str, int] = {}
    new_counts: dict[str, int] = {}
    today_counts: dict[str, int] = {}
    latest: datetime | None = None
    for category in _TRACKING_CATEGORIES:
        rows = [row for row in (library.get(category) or []) if isinstance(row, Mapping)]
        counts[category] = len(rows)
        new_count = 0
        today_count = 0
        for row in rows:
            first = _parse_time(row.get("first_seen_at"))
            if first is not None:
                if cutoff is None or first > cutoff:
                    new_count += 1
                if first >= day_ago:
                    today_count += 1
                if latest is None or first > latest:
                    latest = first
        new_counts[category] = new_count
        today_counts[category] = today_count
    total = sum(counts.values())
    new_total = sum(new_counts.values())
    today_total = sum(today_counts.values())
    direct_related = 0
    possibly_related = 0
    for category in _TRACKING_CATEGORIES:
        for row in (library.get(category) or []):
            if not isinstance(row, Mapping):
                continue
            level = _clean(row.get("match_level") or ((row.get("evidence_trust") or {}).get("verdict") if isinstance(row.get("evidence_trust"), Mapping) else "")).upper()
            if level in {"POSSIBLY_RELATED", "POSSIBLE"}:
                possibly_related += 1
            else:
                direct_related += 1
    item["material_stats"] = {
        **counts,
        "total": total,
        "direct_related": direct_related,
        "possibly_related": possibly_related,
        "new_total": new_total,
        "new_products": new_counts.get("products", 0),
        "today_total": today_total,
        "today_products": today_counts.get("products", 0),
        "latest_material_at": latest.isoformat() if latest is not None else None,
    }
    item["new_material_count"] = new_total
    item["new_product_count"] = new_counts.get("products", 0)
    item["has_new_data"] = new_total > 0


def _merge_material_card(item: dict[str, Any], category: str, raw: Mapping[str, Any], seen_at: str) -> bool:
    library = item.setdefault("material_library", _empty_material_library())
    if category not in _TRACKING_CATEGORIES:
        category = "other"
    rows = library.setdefault(category, [])
    key = _tracking_card_key(raw)
    if not key:
        return False

    # Search across all categories so one URL is not counted twice simply because an upstream
    # classifier called it both supporting material and a product.
    for existing_category in _TRACKING_CATEGORIES:
        existing_rows = library.setdefault(existing_category, [])
        for existing in existing_rows:
            if not isinstance(existing, dict):
                continue
            if _tracking_card_key(existing) != key and not _near_duplicate_rows(existing, raw):
                continue
            existing["last_seen_at"] = seen_at
            existing["seen_count"] = max(1, int(existing.get("seen_count") or 1)) + 1
            # Fill richer fields when a later trace has more useful context, but never erase the
            # first-seen record or original URL. Upgrade POSSIBLY_RELATED -> RELATED when a later
            # query/source provides stronger role/workflow binding.
            for field in ("title", "excerpt", "source", "author", "solution_type", "tracking_family", "search_query", "source_grounding"):
                value = raw.get(field)
                if _emptyish(existing.get(field)) and not _emptyish(value):
                    existing[field] = copy.deepcopy(value)
            old_level = _clean(existing.get("match_level")).upper()
            new_level = _clean(raw.get("match_level")).upper()
            if new_level == "RELATED" and old_level in {"", "POSSIBLY_RELATED", "POSSIBLE"}:
                existing["match_level"] = "RELATED"
                if isinstance(raw.get("evidence_trust"), Mapping):
                    existing["evidence_trust"] = copy.deepcopy(dict(raw.get("evidence_trust") or {}))
            elif _emptyish(existing.get("match_level")) and new_level:
                existing["match_level"] = new_level
                if isinstance(raw.get("evidence_trust"), Mapping):
                    existing["evidence_trust"] = copy.deepcopy(dict(raw.get("evidence_trust") or {}))

            # If an older cycle stored a review/marketplace row under products and a later, richer
            # classifier identifies it as discussion material, move the durable card instead of
            # keeping the stale category forever.
            if existing_category != category and category == "discussions":
                try:
                    existing_rows.remove(existing)
                    rows.append(existing)
                except ValueError:
                    pass
            return False

    card = _tracking_card(raw, first_seen_at=seen_at)
    rows.append(card)
    if len(rows) > _TRACKING_MAX_LIBRARY_PER_CATEGORY:
        del rows[: len(rows) - _TRACKING_MAX_LIBRARY_PER_CATEGORY]
    return True


def _tracking_category_for_row(default_category: str, row: Mapping[str, Any]) -> str:
    """Classify material by source/content type only; never infer market strength."""
    source = _clean(row.get("source")).upper()
    solution_type = _clean(row.get("solution_type")).upper()
    url = _clean(row.get("url")).lower()
    text = " ".join((_clean(row.get("title")), _clean(row.get("excerpt")), _clean(row.get("solution_type")))).lower()

    discussion_hosts = ("reddit.com/", "quora.com/", "news.ycombinator.com/", "stackoverflow.com/", "stackexchange.com/", "discourse.", "community.", "forum.", "youtube.com/watch",
        "practicalmachinist.com/", "plctalk.net/", "control.com/", "contractortalk.com/", "community.shopify.com/",
        "sellercentral.amazon.com/seller-forums", "thetruckersreport.com/", "teachers.net/", "newagtalk.com/")
    product_review_hosts = (
        "g2.com/", "capterra.com/", "getapp.com/", "trustpilot.com/", "producthunt.com/",
        "trustradius.com/", "softwareadvice.com/", "gartner.com/reviews/", "sourceforge.net/software/",
    )
    marketplace_hosts = (
        "apps.shopify.com/", "marketplace.atlassian.com/", "appexchange.salesforce.com/",
        "appsource.microsoft.com/", "workspace.google.com/marketplace/", "chromewebstore.google.com/",
        "wordpress.org/plugins/",
    )
    research_hosts = ("arxiv.org/", "pubmed.ncbi.nlm.nih.gov/", "ncbi.nlm.nih.gov/pmc/", "ssrn.com/", "researchgate.net/", "semanticscholar.org/", "doi.org/")
    if default_category == "technical" or "github.com/" in url or "gitlab.com/" in url or any(cue in source for cue in _TECHNICAL_SOURCES):
        return "technical"
    if any(host in url for host in product_review_hosts):
        return "discussions"
    if any(host in url for host in marketplace_hosts):
        if "review" in text or "/reviews" in url or "rating" in text:
            return "discussions"
        return "products"
    if default_category == "discussions" or any(host in url for host in discussion_hosts) or any(cue in source for cue in _DISCUSSION_SOURCES):
        return "discussions"
    if any(host in url for host in research_hosts):
        return "articles"
    if default_category == "products":
        return "products"
    if solution_type in {"PRODUCT", "SOFTWARE", "SAAS", "SERVICE", "TOOL", "PLATFORM", "MARKETPLACE", "VENDOR", "COMPETITOR", "COMMERCIAL"}:
        return "products"
    product_hits = sum(1 for cue in _PRODUCT_CUES if cue in text)
    if product_hits >= 2 or (product_hits >= 1 and any(cue in url for cue in ("/pricing", "/product", "/products", "/software", "/solutions"))):
        return "products"
    if default_category == "articles" or any(cue in text for cue in _ARTICLE_CUES):
        return "articles"
    return default_category if default_category in _TRACKING_CATEGORIES else "other"


def _merge_material_result(item: dict[str, Any], result: Mapping[str, Any], seen_at: str) -> dict[str, int]:
    brief = _brief(result)
    added = {key: 0 for key in _TRACKING_CATEGORIES}
    qualified_rows: list[Mapping[str, Any]] = []
    for default_category, source_key in _TRACKING_BRIEF_FIELDS.items():
        values = brief.get(source_key)
        if not isinstance(values, list):
            continue
        for row in values:
            if not isinstance(row, Mapping):
                continue
            trust = row.get("evidence_trust") if isinstance(row.get("evidence_trust"), Mapping) else {}
            verdict = _clean(trust.get("verdict")).upper()
            if verdict not in {"RELATED", "QUALIFIED"}:
                continue
            enriched = enrich_material(row, observed_at=seen_at)
            qualified_rows.append(enriched)
            category = _tracking_category_for_row(default_category, enriched)
            if _merge_material_card(item, category, enriched, seen_at):
                added[category] += 1
    behavior_cycle = record_behavior_cycle(item, qualified_rows, seen_at)
    _refresh_material_stats(item)
    item["last_tracking_delta"] = {
        **added,
        "total": sum(added.values()),
        "at": seen_at,
        "new_observations": int(behavior_cycle.get("new_observations") or 0),
        "known_actor_count": int(behavior_cycle.get("known_actor_count") or 0),
        "surfaced_pattern_count": int(behavior_cycle.get("surfaced_pattern_count") or 0),
    }
    return added


def _migrate_history_into_material_library(item: dict[str, Any]) -> None:
    item.setdefault("material_library", _empty_material_library())
    for entry in [row for row in (item.get("history") or []) if isinstance(row, Mapping)]:
        seen_at = _clean(entry.get("completed_at")) or _clean(entry.get("started_at")) or _clean(item.get("created_at")) or _now()
        for category, history_field in _TRACKING_HISTORY_FIELDS.items():
            values = entry.get(history_field)
            if not isinstance(values, list):
                continue
            for row in values:
                if not isinstance(row, Mapping):
                    continue
                trust = row.get("evidence_trust") if isinstance(row.get("evidence_trust"), Mapping) else {}
                # Preserve only evidence that had already cleared the previous relevance/grounding
                # boundary. Rejected raw traces stay in audit history and are not silently revived.
                if _clean(trust.get("verdict")).upper() != "QUALIFIED":
                    continue
                _merge_material_card(item, _tracking_category_for_row(category, row), row, seen_at)


def _reclassify_material_library(item: dict[str, Any]) -> bool:
    """Re-run type-only categorization without changing evidence truth or seen counters."""
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    rebuilt = _empty_material_library()
    seen: set[str] = set()
    changed = False
    for old_category in _TRACKING_CATEGORIES:
        for raw in (library.get(old_category) or []):
            if not isinstance(raw, Mapping):
                continue
            row = copy.deepcopy(dict(raw))
            key = _tracking_card_key(row) or _sha_key(repr(sorted(row.items(), key=lambda kv: str(kv[0]))))
            if key in seen:
                continue
            seen.add(key)
            new_category = _tracking_category_for_row(old_category, row)
            if new_category != old_category:
                changed = True
            rebuilt.setdefault(new_category, []).append(row)
    if changed:
        item["material_library"] = rebuilt
    return changed


def _migrate_tracking_pivot(store: dict[str, Any]) -> bool:
    changed = False
    automation = store.setdefault("automation", {})
    desired_auto = {
        "tracking_mode": "CONTINUOUS_RELATED_MATERIAL_DISCOVERY",
        "tracking_interval_seconds": _TRACKING_INTERVAL_SECONDS,
        "research_concurrency": _DEFAULT_RESEARCH_CONCURRENCY,
        "freshness_enabled": False,
        "source_expansion_version": _TRACKING_SOURCE_EXPANSION_VERSION,
        "broad_query_fanout": _TRACKING_BROAD_QUERY_FANOUT,
        "refresh_query_fanout": _TRACKING_REFRESH_QUERY_FANOUT,
        "source_families": list(_TRACKING_SOURCE_FAMILIES),
    }
    for key, value in desired_auto.items():
        if automation.get(key) != value:
            automation[key] = value
            changed = True

    items = store.get("items") if isinstance(store.get("items"), dict) else {}
    for item in items.values():
        if not isinstance(item, dict):
            continue
        if _clean(item.get("tracking_pivot_version")) != _TRACKING_PIVOT_VERSION:
            _migrate_history_into_material_library(item)
            item["tracking_pivot_version"] = _TRACKING_PIVOT_VERSION
            item["tracking_enabled"] = True
            item["tracking_cycle_count"] = int(item.get("tracking_cycle_count") or 0)
            if not item.get("last_checked_at"):
                _latest_tracking_dt = _latest_completed_research_at(item)
                item["last_checked_at"] = _latest_tracking_dt.isoformat() if _latest_tracking_dt is not None else None
            # Every existing direction gets one broad tracking pass immediately after the pivot.
            item["next_track_after"] = _now()
            item["auto_status"] = "TRACKING_NEW"
            item["current_call"] = "等待第一次新版自動追蹤"
            item["why"] = "SignalForge 只負責找與這個 idea 相關的公開資料；不再替你判斷商機強弱。"
            item["next_job"] = "BASELINE"
            item["next_question"] = "持續找相關討論、貼文、研究、文章、GitHub 與相關產品。"
            item["needs_founder"] = False
            item["review_priority"] = 0
            item["known"] = []
            item["unknown"] = []
            item["counterevidence"] = []
            item["latest_change"] = "TRACKING_PIVOT_MIGRATED"
            item["updated_at"] = _now()
            _refresh_material_stats(item)
            changed = True
        else:
            item.setdefault("tracking_enabled", True)
            item.setdefault("tracking_cycle_count", 0)
            item.setdefault("material_library", _empty_material_library())
            if _clean(item.get("tracking_source_expansion_version")) != _TRACKING_SOURCE_EXPANSION_VERSION:
                if _reclassify_material_library(item):
                    _refresh_material_stats(item)
                item["tracking_source_expansion_pending"] = True
                item["next_track_after"] = _now()
                if _clean(item.get("auto_status")).upper() not in {"SEARCHING", "SOURCE_LIMITED", "TRACKING_NEW"}:
                    item["auto_status"] = "TRACKING_DUE"
                item["current_call"] = "等待真人聲音補搜"
                item["why"] = "V2.5 會用更短、更像實務貼文的 pain/workflow query，加上產業論壇與本地語言分拆搜尋，優先補真人討論與 workaround。"
                item["latest_change"] = "TRACKING_HUMANVOICE_REFILL_QUEUED"
                item["updated_at"] = _now()
                changed = True
            item.setdefault("next_track_after", item.get("last_checked_at") or _now())
            if _requalify_profile_material_library(item):
                changed = True
            before_stats = copy.deepcopy(item.get("material_stats"))
            _refresh_material_stats(item)
            if before_stats != item.get("material_stats"):
                changed = True
        if migrate_behavior_state(item):
            changed = True
    return changed


def _repair_worker(store: dict[str, Any]) -> None:
    worker = store.setdefault("worker", {})
    items = store.get("items") if isinstance(store.get("items"), dict) else {}
    active_ids = {
        _clean(row.get("item_id"))
        for row in (worker.get("active_jobs") or [])
        if isinstance(row, Mapping) and _clean(row.get("item_id"))
    }
    current = _clean(worker.get("current_item_id"))
    if current:
        active_ids.add(current)
    repaired: list[str] = []
    if _clean(worker.get("status")).upper() == "RUNNING":
        for item_id in active_ids:
            item = items.get(item_id)
            if isinstance(item, dict):
                item["auto_status"] = "TRACKING_DUE"
                item["next_track_after"] = _now()
                item["current_call"] = "上次追蹤被 API 重啟中斷，已排回佇列"
                item["why"] = "追蹤途中 API process 中斷；資料未被判定為任何市場結論。"
                item["latest_change"] = "TRACKING_INTERRUPTED_REQUEUED"
                item["updated_at"] = _now()
                repaired.append(item_id)
    for item_id, item in items.items():
        if not isinstance(item, dict) or item_id in repaired:
            continue
        if _clean(item.get("auto_status")).upper() in {"SEARCHING", "RESEARCHING"}:
            item["auto_status"] = "TRACKING_DUE"
            item["next_track_after"] = _now()
            item["current_call"] = "偵測到孤兒追蹤狀態，已排回佇列"
            item["why"] = "沒有活著的 worker 對應這個搜尋狀態；重新執行同一個追蹤週期。"
            item["latest_change"] = "TRACKING_ORPHAN_REQUEUED"
            item["updated_at"] = _now()
            repaired.append(str(item_id))
    if repaired or _clean(worker.get("status")).upper() == "RUNNING":
        worker["status"] = "INTERRUPTED"
        worker["finished_at"] = _now()
        worker["current_item_id"] = None
        worker["current_job"] = None
        worker["active_jobs"] = []
        worker["active_count"] = 0
        worker["stop_requested"] = False
        worker["recovered_item_ids"] = repaired[-40:]
        if not worker.get("last_error"):
            worker["last_error"] = "Previous API process stopped while tracking; in-flight searches were requeued."


def load_store(repo: str | Path = ".", *, repair_worker: bool = False) -> dict[str, Any]:
    # Let the proven V1.6 loader keep corruption recovery and old immutable-history migrations.
    raw = _v16_load_store(repo, repair_worker=False)
    with _LOCK:
        changed = _migrate_tracking_pivot(raw)
        worker_before = copy.deepcopy(raw.get("worker"))
        if repair_worker:
            _repair_worker(raw)
        if changed or raw.get("worker") != worker_before:
            raw["engine_version"] = ENGINE_VERSION
            raw["truth_boundary"] = TRUTH_BOUNDARY
            raw["updated_at"] = _now()
            _atomic_write(_store_path(repo), raw)
        return raw


def _new_item(seed: Mapping[str, Any]) -> dict[str, Any]:
    item = _v16_new_item(seed)
    item.update({
        "tracking_pivot_version": _TRACKING_PIVOT_VERSION,
        "tracking_enabled": True,
        "tracking_cycle_count": 0,
        "tracking_source_expansion_version": None,
        "tracking_source_expansion_pending": True,
        "tracking_research_quality_version": None,
        "tracking_profile": None,
        "tracking_expansion_health": {},
        "material_library": _empty_material_library(),
        "material_quarantine": [],
        "material_stats": {key: 0 for key in _TRACKING_CATEGORIES} | {
            "total": 0, "new_total": 0, "new_products": 0, "today_total": 0, "today_products": 0, "latest_material_at": None,
        },
        "new_material_count": 0,
        "new_product_count": 0,
        "has_new_data": False,
        "last_checked_at": None,
        "next_track_after": _now(),
        "auto_status": "TRACKING_NEW",
        "current_call": "等待第一次自動追蹤",
        "why": "SignalForge 會持續找與這個 idea 相關的公開資料；分析與商機判斷交給 ChatGPT / Founder。",
        "next_job": "BASELINE",
        "next_question": "找相關討論、留言、貼文、研究、文章、GitHub 與相關產品。",
        "known": [],
        "unknown": [],
        "counterevidence": [],
        "research_coverage": {},
        "review_priority": 0,
        "needs_founder": False,
        "behavior_tracking_version": BEHAVIOR_TRACKING_VERSION,
        "behavior_observations": [],
        "actor_index": {},
        "repeated_patterns": [],
        "behavior_windows": {},
        "behavior_last_cycle": {},
        "trend_snapshots": [],
        "trend_provider_status": {"provider": "NONE", "status": "NOT_CONFIGURED"},
    })
    return item


def _reopen_after_material_upstream_change(item: dict[str, Any], reason: str) -> bool:
    if not bool(item.get("tracking_enabled", True)):
        return False
    item["auto_status"] = "TRACKING_DUE"
    item["next_track_after"] = _now()
    item["current_call"] = "Idea 有更新，已排入重新追蹤"
    item["why"] = _clean(reason) or "Idea context changed; refresh related-material discovery."
    item["next_job"] = "BASELINE"
    item["next_question"] = "用更新後的 idea context 重新找所有相關資料。"
    item["needs_founder"] = False
    item["latest_change"] = "TRACKING_CONTEXT_CHANGED_REQUEUED"
    item["updated_at"] = _now()
    return True


def _refresh_accumulated_state(item: dict[str, Any]) -> None:
    # No autonomous market interpretation. This function now only refreshes material counts.
    _refresh_material_stats(item)
    item["research_coverage"] = {
        "meaning": "LEGACY_FIELD_REPURPOSED_FOR_TRACKING_COMPATIBILITY",
        "material_total": int((item.get("material_stats") or {}).get("total") or 0),
        "discussions": int((item.get("material_stats") or {}).get("discussions") or 0),
        "products": int((item.get("material_stats") or {}).get("products") or 0),
        "articles": int((item.get("material_stats") or {}).get("articles") or 0),
        "technical": int((item.get("material_stats") or {}).get("technical") or 0),
        "other": int((item.get("material_stats") or {}).get("other") or 0),
    }
    item["review_priority"] = 0
    item["known"] = []
    item["unknown"] = []
    item["counterevidence"] = []
    item["needs_founder"] = False


_TRACKING_CJK_GENERIC_TERMS = {
    "研究", "假設", "待驗證", "目前", "可能", "問題", "相關", "資料", "系統", "使用", "工作",
    "流程", "管理", "追蹤", "業者", "公司", "人員", "方式", "情況", "需要", "進行", "處理",
}


def _cjk_literal_terms(value: Any) -> set[str]:
    raw = _clean(value)
    out: set[str] = set()
    # Chinese/Japanese Han text does not have whitespace token boundaries. Keep meaningful short
    # n-grams so Chinese idea facets can match Chinese discussions instead of silently falling back
    # to English-only relevance. 2-char grams alone are noisy, so prefer 3-6 chars and retain short
    # standalone chunks such as 收據/核銷 when punctuation provides a boundary.
    for chunk in re.findall(r"[\u3400-\u9fff]{2,}", raw):
        if len(chunk) <= 6:
            out.add(chunk)
        for width in (3, 4, 5, 6):
            if len(chunk) < width:
                continue
            for idx in range(0, len(chunk) - width + 1):
                out.add(chunk[idx:idx + width])
        # Short operational nouns are often exactly two Han characters.
        if len(chunk) == 2:
            out.add(chunk)
    out.difference_update(_TRACKING_CJK_GENERIC_TERMS)
    return out


def _tracking_literal_terms(value: Any) -> set[str]:
    terms = set(_latin_literal_terms(value)) | _cjk_literal_terms(value)
    terms.difference_update(_TRACKING_GENERIC_TERMS)
    return terms


def _tracking_structured_facets(item: Mapping[str, Any]) -> dict[str, set[str]]:
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    if not context:
        return {}
    actor_text = " ".join(_clean(context.get(key)) for key in ("actor", "actor_category", "buyer_context") if not _emptyish(context.get(key)))
    pain_text = " ".join(_clean(context.get(key)) for key in ("task", "failure_mode", "consequence") if not _emptyish(context.get(key)))
    workaround_text = " ".join(_clean(context.get(key)) for key in ("workaround", "current_workaround") if not _emptyish(context.get(key)))
    title_terms = _tracking_literal_terms(item.get("title"))
    actor_terms = _tracking_literal_terms(actor_text)
    pain_terms = _tracking_literal_terms(f"{pain_text} {_clean(item.get('description'))}")
    workaround_terms = _tracking_literal_terms(workaround_text)
    context_specific = set(pain_terms | workaround_terms)
    # Terms already present in the short title are useful subject anchors, but they are not enough
    # by themselves to prove that a page is about the same actor/workflow.
    context_specific.difference_update(title_terms)
    return {
        "actor": actor_terms,
        "pain": pain_terms,
        "workaround": workaround_terms,
        "title": title_terms,
        "context_specific": context_specific,
    }


def _tracking_relevance_match(item: Mapping[str, Any], result: Mapping[str, Any], row: Mapping[str, Any], lane_key: str) -> dict[str, Any]:
    if _tracking_profile_key_for_item(item) == "AI_PUBLIC_LINK_ACCESS" and not _tracking_ai_link_row_relevant(row):
        return {
            "passed": False,
            "level": "UNRELATED",
            "basis": "AI_PUBLIC_LINK_PROFILE_RELEVANCE_V2_5_5",
            "core": {"subject_overlap": []},
            "actor_overlap": [],
            "pain_overlap": [],
            "context_specific_overlap": [],
        }
    core = _core_opportunity_match(item, "BASELINE", result, row)
    core_overlap = [term for term in (core.get("subject_overlap") or []) if term not in _TRACKING_GENERIC_TERMS]

    facets = _tracking_structured_facets(item)
    if not facets:
        atomic = _atomic_problem_match(item, result, row)
        direct = bool(atomic.get("passed")) or len(core_overlap) >= 3
        possible = (not direct) and len(core_overlap) >= 2
        return {
            "passed": direct or possible,
            "level": "RELATED" if direct else ("POSSIBLY_RELATED" if possible else "UNRELATED"),
            "basis": "CORE_PLUS_ATOMIC_FALLBACK",
            "core": {**dict(core), "subject_overlap": core_overlap},
            "atomic": atomic,
        }

    card_terms = _tracking_literal_terms(_evidence_card_text(row))
    actor_overlap = sorted(set(facets.get("actor") or set()) & card_terms)
    pain_overlap = sorted(set(facets.get("pain") or set()) & card_terms)
    specific_overlap = sorted(set(facets.get("context_specific") or set()) & card_terms)

    # Direct relevance remains strict enough to reject adjacent-topic noise.
    direct = bool(
        (actor_overlap and (pain_overlap or len(core_overlap) >= 2))
        or (len(specific_overlap) >= 2 and len(core_overlap) >= 1)
        or len(specific_overlap) >= 3
        or len(core_overlap) >= 3
    )
    url = _clean(row.get("url")).lower()
    tracking_family = _clean(row.get("tracking_family")).lower()
    human_family = tracking_family in {
        "public_discussions", "practitioner_communities", "vendor_support_communities",
        "domain_forums", "product_reviews", "manual_workarounds",
    }
    human_host = human_family or any(host in url for host in (
        "reddit.com/", "quora.com/", "stackexchange.com/", "stackoverflow.com/",
        "news.ycombinator.com/", "g2.com/", "capterra.com/", "getapp.com/",
        "trustpilot.com/", "producthunt.com/", "trustradius.com/", "softwareadvice.com/",
        "gartner.com/reviews/", "sourceforge.net/software/", "youtube.com/watch", "linkedin.com/posts",
        "practicalmachinist.com/", "plctalk.net/", "control.com/", "contractortalk.com/",
        "community.shopify.com/", "sellercentral.amazon.com/seller-forums", "thetruckersreport.com/",
        "teachers.net/", "newagtalk.com/", "/forum", "/community", "/discussions", "/support/",
    ))
    if lane_key == "human_comments" and human_host:
        direct = direct or bool(
            (specific_overlap and len(core_overlap) >= 2)
            or (actor_overlap and pain_overlap)
            or len(specific_overlap) >= 2
        )
    if lane_key in {"similar_products", "repo_solutions", "supporting_evidence"}:
        direct = direct or bool(len(core_overlap) >= 2 and (actor_overlap or pain_overlap or specific_overlap))

    # WideNet high-recall tier: keep borderline material when it binds at least one structured
    # actor/workflow/pain facet AND one opportunity anchor.  This is deliberately weaker than
    # direct relevance, but still rejects topic-only overlap such as consumer RMA for a repair-shop
    # reimbursement idea or generic construction pages for a change-order evidence idea.
    possible = False
    if not direct:
        if lane_key == "human_comments" and human_host:
            possible = bool((specific_overlap and core_overlap) or (actor_overlap and core_overlap))
        elif lane_key in {"similar_products", "repo_solutions", "supporting_evidence"}:
            possible = bool(specific_overlap and core_overlap)
        else:
            possible = bool(len(specific_overlap) >= 2)

    return {
        "passed": direct or possible,
        "level": "RELATED" if direct else ("POSSIBLY_RELATED" if possible else "UNRELATED"),
        "basis": "TRACKING_ROLE_WORKFLOW_RELEVANCE_V2",
        "core": {**dict(core), "subject_overlap": core_overlap},
        "actor_overlap": actor_overlap[:12],
        "pain_overlap": pain_overlap[:16],
        "context_specific_overlap": specific_overlap[:16],
    }

def _evidence_trust_filter_result(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Tracking Pivot: keep related material; do not adjudicate market strength or lane semantics."""
    brief = result.get("research_brief") if isinstance(result.get("research_brief"), Mapping) else None
    if not isinstance(brief, Mapping):
        return result
    filtered = copy.deepcopy(dict(result))
    fb = filtered.get("research_brief")
    if not isinstance(fb, dict):
        return result

    before: dict[str, int] = {}
    after: dict[str, int] = {}
    rejected: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []
    duplicate_count = 0
    for lane_key in _EVIDENCE_LANE_KEYS:
        rows = fb.get(lane_key)
        if not isinstance(rows, list):
            continue
        before[lane_key] = len(rows)
        kept: list[dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            rel = _tracking_relevance_match(item, filtered, row, lane_key)
            if not rel.get("passed"):
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="UNRELATED",
                    reason=(
                        "Related-material filter rejected topic-only overlap; basis=" + _clean(rel.get("basis"))
                        + " core=" + ",".join((rel.get("core") or {}).get("subject_overlap") or [])
                        + " actor=" + ",".join(rel.get("actor_overlap") or [])
                        + " specific=" + ",".join(rel.get("context_specific_overlap") or [])
                    ),
                ))
                continue
            duplicate_of = next((prior for prior in accepted_rows if _near_duplicate_rows(prior, row)), None)
            if duplicate_of is not None:
                duplicate_count += 1
                rejected.append(_trust_summary_card(
                    row,
                    lane=lane_key,
                    verdict="DUPLICATE",
                    reason=f"Near-duplicate of already kept related material: {_clean(duplicate_of.get('title'))[:160]}",
                ))
                continue
            core = rel.get("core") if isinstance(rel.get("core"), Mapping) else {}
            match_level = _clean(rel.get("level") or "RELATED").upper()
            row["match_level"] = match_level
            row["evidence_trust"] = {
                "version": _TRACKING_RELEVANCE_VERSION,
                "verdict": match_level,
                "meaning": "RELATED_TO_IDEA_ONLY_NOT_MARKET_EVIDENCE_STRENGTH",
                "basis": rel.get("basis"),
                "subject_overlap": list(core.get("subject_overlap") or [])[:16],
                "actor_overlap": list(rel.get("actor_overlap") or [])[:12],
                "pain_overlap": list(rel.get("pain_overlap") or [])[:16],
                "context_specific_overlap": list(rel.get("context_specific_overlap") or [])[:16],
                "source_grounding": copy.deepcopy(dict(row.get("source_grounding") or {})) if isinstance(row.get("source_grounding"), Mapping) else {},
            }
            kept.append(row)
            accepted_rows.append(row)
        fb[lane_key] = kept
        after[lane_key] = len(kept)

    _recount_brief_summary(fb)
    family_counts: dict[str, int] = {}
    for lane_key in _EVIDENCE_LANE_KEYS:
        for row in (fb.get(lane_key) or []):
            if not isinstance(row, Mapping):
                continue
            family = _clean(row.get("tracking_family"))
            if family:
                family_counts[family] = family_counts.get(family, 0) + 1
    filtered["evidence_trust_gate"] = {
        "version": _TRACKING_RELEVANCE_VERSION,
        "status": "RELATED_MATERIAL_FILTERED_HIGH_RECALL",
        "before": before,
        "after": after,
        "related": sum(after.values()),
        "rejected": max(0, sum(before.values()) - sum(after.values())),
        "near_duplicates_collapsed": duplicate_count,
        "tracking_family_counts": family_counts,
        "rejected_examples": rejected[:40],
        "truth_boundary": "RELEVANCE_ONLY;_NO_MARKET_ANALYSIS_OR_OPPORTUNITY_JUDGMENT",
    }
    return filtered


def _quality_filter_result(item: Mapping[str, Any], job: str, result: Mapping[str, Any]) -> Mapping[str, Any]:
    result = _traceability_filter_result(result)
    result = _source_grounding_filter_result(result)
    return _evidence_trust_filter_result(item, job, result)



_TRACKING_SEARCH_BOILERPLATE = (
    "research hypothesis", "研究假設", "這些都是待驗證假設", "待驗證假設",
    "signalforge 應研究", "signalforge should research", "do not treat as market truth",
    "imported backlog context", "unvalidated", "market truth", "source expansion mode",
)


def _tracking_clean_seed_text(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    # Old opportunity imports contain instructions to the former autonomous-research workflow.
    # Those instructions are metadata, not search terms. Stop at the first known boilerplate marker.
    lower = text.lower()
    cut = len(text)
    for needle in _TRACKING_SEARCH_BOILERPLATE:
        idx = lower.find(needle.lower())
        if idx >= 0:
            cut = min(cut, idx)
    text = text[:cut]
    text = re.sub(r"(?:^|[；;。.!?])\s*(?:目前可能透過)?\s*待驗證[:：]?", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -—–:：;；。")
    return text[:1200]


def _tracking_search_seed(item: Mapping[str, Any]) -> str:
    """Build a compact search-only seed from the actual opportunity facets.

    This is intentionally not a market summary. It avoids carrying old workflow instructions such
    as UNVALIDATED / SignalForge 應研究 into search queries, which previously diluted retrieval.
    """
    context = item.get("source_context") if isinstance(item.get("source_context"), Mapping) else {}
    parts: list[str] = []
    title = _tracking_clean_seed_text(item.get("title"))
    if title:
        parts.append(title)
    for key in ("actor", "task", "failure_mode", "consequence", "buyer_context", "workaround", "current_workaround"):
        value = _tracking_clean_seed_text(context.get(key))
        if value and value.lower() not in {x.lower() for x in parts}:
            parts.append(value)
    if len(parts) < 3:
        desc = _tracking_clean_seed_text(item.get("description"))
        if desc:
            parts.append(desc)
    # Preserve multilingual phrases; the web route will build an English bridge separately.
    return " | ".join(parts)[:2200]


def _tracking_family_yields(item: Mapping[str, Any], *, history_limit: int = 8) -> dict[str, int]:
    counts: dict[str, int] = {family: 0 for family in _TRACKING_SOURCE_FAMILIES}
    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    for row in history[-history_limit:]:
        family_counts = row.get("tracking_family_counts") if isinstance(row.get("tracking_family_counts"), Mapping) else {}
        for family, raw in family_counts.items():
            if family not in counts:
                continue
            try:
                counts[family] += int(raw or 0)
            except Exception:
                pass
    return counts


def _preferred_tracking_families(item: Mapping[str, Any]) -> list[str]:
    """Prioritize missing material types first, then proven-yield families.

    Tracking is a collector, not an analyst. The only reason to prefer a family is coverage: if a
    direction has almost no human voice, keep searching human-heavy sources even when product pages
    were easier to find. Once the library is reasonably broad, actual related-material yield drives
    refreshes.
    """
    yields = _tracking_family_yields(item)
    stats = item.get("material_stats") if isinstance(item.get("material_stats"), Mapping) else {}
    discussions = int(stats.get("discussions") or 0)
    products = int(stats.get("products") or 0)
    articles = int(stats.get("articles") or 0)
    technical = int(stats.get("technical") or 0)

    priority: list[str] = []
    if discussions < 40:
        priority.extend([
            "public_discussions", "practitioner_communities", "vendor_support_communities", "domain_forums",
            "product_reviews", "manual_workarounds",
        ])
    if products < 12:
        priority.extend(["related_products", "app_marketplaces"])
    if articles < 10:
        priority.extend(["research_cases", "academic_sources", "b2b_operational_signals", "job_procurement_signals"])
    if technical < 4:
        priority.extend(["practitioner_communities", "vendor_support_communities"])

    ranked = sorted(
        (family for family in _TRACKING_SOURCE_FAMILIES if family not in {"general_web", "local_language"}),
        key=lambda family: (-int(yields.get(family) or 0), _TRACKING_SOURCE_FAMILIES.index(family)),
    )
    fallback = [
        "public_discussions", "vendor_support_communities", "product_reviews", "manual_workarounds",
        "related_products", "app_marketplaces", "research_cases", "academic_sources", "b2b_operational_signals",
    ]
    out: list[str] = []
    for family in priority + ranked + fallback:
        if family not in out:
            out.append(family)
        if len(out) >= 8:
            break
    return out


def _tracking_material_family_stats(item: Mapping[str, Any]) -> dict[str, int]:
    stats: dict[str, int] = {}
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    for category in _TRACKING_CATEGORIES:
        for row in (library.get(category) or []):
            if not isinstance(row, Mapping):
                continue
            family = _clean(row.get("tracking_family")) or "legacy_or_specialist"
            stats[family] = stats.get(family, 0) + 1
    return dict(sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])))


def _job_prompt(item: Mapping[str, Any], job: str) -> tuple[str, str]:
    title = _clean(item.get("title"))
    base = _research_base(item)
    pending = bool(item.get("tracking_source_expansion_pending", False))
    cycles = int(item.get("tracking_cycle_count") or 0)
    expansion_mode = "BROAD_FIRST_PASS" if pending and cycles <= 0 else ("COVERAGE_REFILL" if pending else "DELTA_REFRESH")
    search_seed = _tracking_search_seed(item)
    preferred = _preferred_tracking_families(item)
    stats = item.get("material_stats") if isinstance(item.get("material_stats"), Mapping) else {}
    coverage = {
        "discussions": int(stats.get("discussions") or 0),
        "products": int(stats.get("products") or 0),
        "articles": int(stats.get("articles") or 0),
        "technical": int(stats.get("technical") or 0),
        "other": int(stats.get("other") or 0),
        "total": int(stats.get("total") or 0),
    }
    return title, (
        f"{base}\n\nTracking mode: collect public material related to this idea. "
        "Find real discussions/comments/posts, product reviews, complaints and workarounds, relevant products/services/tools and pricing pages, "
        "research papers/case studies/articles/news, GitHub issues/repos and technical material. "
        "SignalForge must NOT decide whether the opportunity is good, whether people will pay, or whether to build it. "
        "Keep relevant positive, negative and neutral material; reject only material that is actually about a different idea. "
        f"Source expansion mode: {expansion_mode}.\n"
        f"Tracking search seed: {search_seed}\n"
        f"Tracking preferred families: {','.join(preferred)}\n"
        "Tracking coverage stats: " + ",".join(f"{k}={v}" for k, v in coverage.items()) + "\n"
        "Tracking coverage targets: discussions=40,products=20,articles=15,technical=6,total=90\n"
        f"Tracking cycle index: {cycles}"
    )


def _history_snapshot(job: str, result: Mapping[str, Any], started_at: str, completed_at: str) -> dict[str, Any]:
    trust_gate = dict(result.get("evidence_trust_gate") or {}) if isinstance(result.get("evidence_trust_gate"), Mapping) else {}
    return {
        "research_id": f"t-{_sha_key(started_at + 'TRACK')}",
        "job": "TRACK",
        "started_at": started_at,
        "completed_at": completed_at,
        "status": result.get("status"),
        "counts": _counts(result),
        "human_comments": _top_cards(result, "human_comments", 8),
        "products": _top_cards(result, "similar_products", 8),
        "repos": _top_cards(result, "repo_solutions", 8),
        "supporting": _top_cards(result, "supporting_evidence", 8),
        "counterevidence": _top_cards(result, "counter_evidence", 8),
        "gaps": list(_brief(result).get("gaps") or [])[:8],
        "successful_sources": _successful_sources(result),
        "failed_sources": _failed_sources(result),
        "traceability_gate": dict(result.get("traceability_gate") or {}) if isinstance(result.get("traceability_gate"), Mapping) else {},
        "evidence_trust_gate": trust_gate,
        "evidence_trust_version": trust_gate.get("version") or _TRACKING_RELEVANCE_VERSION,
        "tracking_family_counts": dict(trust_gate.get("tracking_family_counts") or {}),
        "research_trace": _result_research_trace(result),
        "coverage_complete": not _research_transport_limited(result),
        "coverage_reason": "SOURCE_TRANSPORT_LIMITED_NOT_COMPLETE" if _research_transport_limited(result) else "TRACKING_CYCLE_COMPLETED",
        "market_truth_writes": 0,
    }


def _tracking_due(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    if not bool(item.get("tracking_enabled", True)):
        return False
    status = _clean(item.get("auto_status")).upper()
    if status in {"TRACKING_NEW", "TRACKING_DUE"}:
        return True
    if status == "SOURCE_LIMITED":
        return _source_retry_due(item, now=now)
    if status in {"SEARCHING", "RESEARCHING"}:
        return False
    due = _parse_time(item.get("next_track_after"))
    return due is None or due <= (now or datetime.now(timezone.utc))


def _pending_job_estimate(store: Mapping[str, Any]) -> int:
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    now = datetime.now(timezone.utc)
    return sum(1 for item in items.values() if isinstance(item, Mapping) and _tracking_due(item, now=now))


def _select_next_item(store: Mapping[str, Any]) -> tuple[str, str] | None:
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    order = list(store.get("order") or [])
    now = datetime.now(timezone.utc)
    # Never-tracked / manually requested directions first, then oldest periodic refresh.
    for wanted in ("TRACKING_NEW", "TRACKING_DUE"):
        for item_id in order:
            item = items.get(item_id)
            if isinstance(item, Mapping) and bool(item.get("tracking_enabled", True)) and _clean(item.get("auto_status")).upper() == wanted:
                return str(item_id), "BASELINE"
    due_rows: list[tuple[datetime, str]] = []
    for item_id in order:
        item = items.get(item_id)
        if not isinstance(item, Mapping) or not _tracking_due(item, now=now):
            continue
        status = _clean(item.get("auto_status")).upper()
        if status == "SOURCE_LIMITED":
            due = _parse_time(item.get("source_retry_after")) or now
        else:
            due = _parse_time(item.get("next_track_after")) or now
        due_rows.append((due, str(item_id)))
    if due_rows:
        due_rows.sort(key=lambda row: row[0])
        return due_rows[0][1], "BASELINE"
    return None


def _record_scheduler_progress(store: dict[str, Any], *, job: str, was_new: bool, initial_complete_before: bool) -> None:
    # Tracking has no lane progression or opportunity-priority judgment.
    return None


def _material_library_copy(item: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    return {
        category: [copy.deepcopy(dict(row)) for row in (library.get(category) or []) if isinstance(row, Mapping)]
        for category in _TRACKING_CATEGORIES
    }


def _item_for_view(item: Mapping[str, Any], *, include_history: bool = False, include_handoff: bool = True) -> dict[str, Any]:
    history = list(item.get("history") or [])
    latest = history[-1] if history else None
    handoff = build_handoff_text(item) if include_handoff else None
    handoff_hash = hashlib.sha256(handoff.encode("utf-8")).hexdigest()[:24] if handoff is not None else None
    row = {
        "id": item.get("id"),
        "source_kind": item.get("source_kind"),
        "source_ref": item.get("source_ref"),
        "canonical_key": item.get("canonical_key"),
        "title": item.get("title"),
        "description": item.get("description"),
        "source_context": dict(item.get("source_context") or {}),
        "aliases": list(item.get("aliases") or []),
        "import_rank": item.get("import_rank"),
        "auto_status": item.get("auto_status"),
        "tracking_enabled": bool(item.get("tracking_enabled", True)),
        "current_call": item.get("current_call"),
        "why": item.get("why"),
        "last_checked_at": item.get("last_checked_at"),
        "next_track_after": item.get("next_track_after"),
        "tracking_cycle_count": int(item.get("tracking_cycle_count") or 0),
        "tracking_source_expansion_version": item.get("tracking_source_expansion_version"),
        "tracking_source_expansion_pending": bool(item.get("tracking_source_expansion_pending", False)),
        "material_library": _material_library_copy(item),
        "material_stats": dict(item.get("material_stats") or {}),
        "tracking_family_stats": _tracking_material_family_stats(item),
        "new_material_count": int(item.get("new_material_count") or 0),
        "new_product_count": int(item.get("new_product_count") or 0),
        "has_new_data": bool(item.get("has_new_data")),
        "last_tracking_delta": dict(item.get("last_tracking_delta") or {}),
        "behavior_tracking_version": item.get("behavior_tracking_version"),
        "behavior_windows": copy.deepcopy(dict(item.get("behavior_windows") or {})),
        "behavior_last_cycle": copy.deepcopy(dict(item.get("behavior_last_cycle") or {})),
        "repeated_patterns": copy.deepcopy(list(item.get("repeated_patterns") or [])),
        "actors": copy.deepcopy(sorted(
            [row for row in (item.get("actor_index") or {}).values() if isinstance(row, Mapping)],
            key=lambda row: (_clean(row.get("last_seen_at")), int(row.get("observation_count") or 0)),
            reverse=True,
        )[:120]),
        "trend_snapshots": copy.deepcopy(list(item.get("trend_snapshots") or [])[-120:]),
        "trend_provider_status": copy.deepcopy(dict(item.get("trend_provider_status") or {})),
        "founder_reviewed_at": item.get("founder_reviewed_at"),
        "founder_reviewed_research_count": int(item.get("founder_reviewed_research_count") or 0),
        "research_count": len(history),
        "latest_research": latest,
        "latest_change": item.get("latest_change"),
        "source_retry_count": int(item.get("source_retry_count") or 0),
        "source_retry_after": item.get("source_retry_after"),
        "source_retry_reason": item.get("source_retry_reason"),
        "legacy": dict(item.get("legacy") or {}),
        "updated_at": item.get("updated_at"),
        "market_truth_writes": 0,
    }
    if include_handoff:
        row["handoff"] = handoff
        row["handoff_hash"] = handoff_hash
    if include_history:
        row["history"] = history
    return row


def _item_for_list(item: Mapping[str, Any]) -> dict[str, Any]:
    stats = dict(item.get("material_stats") or {})
    return {
        "id": item.get("id"),
        "source_kind": item.get("source_kind"),
        "source_ref": item.get("source_ref"),
        "title": item.get("title"),
        "description": item.get("description"),
        "import_rank": item.get("import_rank"),
        "auto_status": item.get("auto_status"),
        "tracking_enabled": bool(item.get("tracking_enabled", True)),
        "current_call": item.get("current_call"),
        "why": item.get("why"),
        "last_checked_at": item.get("last_checked_at"),
        "next_track_after": item.get("next_track_after"),
        "tracking_cycle_count": int(item.get("tracking_cycle_count") or 0),
        "tracking_source_expansion_version": item.get("tracking_source_expansion_version"),
        "tracking_source_expansion_pending": bool(item.get("tracking_source_expansion_pending", False)),
        "material_stats": stats,
        "tracking_family_stats": dict(item.get("tracking_family_stats") or {}),
        "new_material_count": int(item.get("new_material_count") or 0),
        "new_product_count": int(item.get("new_product_count") or 0),
        "has_new_data": bool(item.get("has_new_data")),
        "source_retry_count": int(item.get("source_retry_count") or 0),
        "source_retry_after": item.get("source_retry_after"),
        "updated_at": item.get("updated_at"),
        "market_truth_writes": 0,
    }


def _tracking_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    status = _clean(row.get("auto_status")).upper()
    return (
        0 if bool(row.get("has_new_data")) else 1,
        0 if status == "SEARCHING" else 1,
        -int(row.get("new_product_count") or 0),
        -int(row.get("new_material_count") or 0),
        _rank_value(row.get("import_rank")),
        _clean(row.get("title")).lower(),
    )



# Dockerless/read-only workspace cache.
# Read surfaces must never run schema migrations or rewrite the 60MB canonical store.
# Mutation/research paths continue to use load_store(), preserving all existing write semantics.
_READ_VIEW_CACHE_LOCK = threading.RLock()
_READ_VIEW_CACHE: dict[str, Any] = {
    "signature": None,
    "base": None,
}
_DETAIL_VIEW_CACHE: dict[tuple[Any, str], dict[str, Any]] = {}
_DETAIL_VIEW_CACHE_ORDER: list[tuple[Any, str]] = []
_DETAIL_VIEW_CACHE_LIMIT = 6


def _store_signature(repo: str | Path = ".") -> tuple[int, int] | None:
    path = _store_path(repo)
    try:
        stat = path.stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _load_store_readonly(repo: str | Path = ".") -> dict[str, Any]:
    """Read the current canonical state without migrations, repair or writes.

    Dashboard GETs are observation-only. Running cumulative migration logic on every GET
    made a ~60MB store time out and also changed the file merely by opening the UI.
    """
    path = _store_path(repo)
    backup_path = _store_backup_path(repo)
    if not path.exists():
        return _default_store()

    raw = _read_store_mapping(path)
    if raw is None and backup_path.exists():
        raw = _read_store_mapping(backup_path)
    if not isinstance(raw, dict):
        blocked = _default_store()
        blocked["storage_recovery_required"] = True
        blocked["storage_error"] = "Persistent backlog JSON is unreadable; read-only workspace could not load it."
        return blocked

    raw.setdefault("items", {})
    raw.setdefault("order", list((raw.get("items") or {}).keys()))
    raw.setdefault("worker", {})
    raw.setdefault("automation", {})
    raw.setdefault("legacy_archive_summary", {})
    raw.setdefault("market_truth_writes", 0)
    raw.setdefault("truth_boundary", TRUTH_BOUNDARY)
    return raw


def _build_backlog_list_base(repo: str | Path = ".") -> dict[str, Any]:
    signature = _store_signature(repo)
    with _READ_VIEW_CACHE_LOCK:
        if _READ_VIEW_CACHE.get("signature") == signature and isinstance(_READ_VIEW_CACHE.get("base"), dict):
            return _READ_VIEW_CACHE["base"]

    store = _load_store_readonly(repo)
    items = store.get("items") if isinstance(store.get("items"), Mapping) else {}
    order = list(store.get("order") or [])
    all_rows = [_item_for_list(items[item_id]) for item_id in order if isinstance(items.get(item_id), Mapping)]
    all_rows.sort(key=_tracking_sort_key)

    worker_view = dict(store.get("worker") or {})
    active_jobs = [row for row in (worker_view.get("active_jobs") or []) if isinstance(row, Mapping)]
    worker_view["active_count"] = len(active_jobs)
    worker_view["queued_jobs_estimate"] = _pending_job_estimate(store)
    automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
    worker_view["max_concurrency"] = max(
        1,
        min(
            int(automation.get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY),
            _MAX_RESEARCH_CONCURRENCY,
        ),
    )

    summary = {
        "directions": len(all_rows),
        "tracking_enabled": sum(1 for row in all_rows if bool(row.get("tracking_enabled", True))),
        "searching": int(worker_view.get("active_count") or 0),
        "directions_with_new_data": sum(1 for row in all_rows if bool(row.get("has_new_data"))),
        "new_materials": sum(int(row.get("new_material_count") or 0) for row in all_rows),
        "new_products": sum(int(row.get("new_product_count") or 0) for row in all_rows),
        "source_limited": sum(1 for row in all_rows if _clean(row.get("auto_status")).upper() == "SOURCE_LIMITED"),
        "paused": len(all_rows) if bool(automation.get("paused_by_founder", False)) else 0,
        "tracking_interval_seconds": int(automation.get("tracking_interval_seconds") or _TRACKING_INTERVAL_SECONDS),
        "source_expansion_pending": sum(1 for row in all_rows if bool(row.get("tracking_source_expansion_pending", False))),
        "broad_query_fanout": int(automation.get("broad_query_fanout") or _TRACKING_BROAD_QUERY_FANOUT),
        "refresh_query_fanout": int(automation.get("refresh_query_fanout") or _TRACKING_REFRESH_QUERY_FANOUT),
        "source_families": list(automation.get("source_families") or _TRACKING_SOURCE_FAMILIES),
    }
    counts = {
        "TRACKING": sum(
            1
            for row in all_rows
            if _clean(row.get("auto_status")).upper() in {"TRACKING", "TRACKING_NEW", "TRACKING_DUE"}
        ),
        "SEARCHING": sum(1 for row in all_rows if _clean(row.get("auto_status")).upper() == "SEARCHING"),
        "SOURCE_LIMITED": summary["source_limited"],
        "NEW_DATA": summary["directions_with_new_data"],
    }
    new_rows = [row for row in all_rows if bool(row.get("has_new_data"))][:6]

    base = {
        "engine_version": store.get("engine_version") or ENGINE_VERSION,
        "status": "OK",
        "all_rows": all_rows,
        "counts": counts,
        "tracking_summary": summary,
        "founder_inbox": new_rows,
        "founder_attention_total": summary["directions_with_new_data"],
        "worker": worker_view,
        "automation": dict(automation),
        "legacy_archive_summary": dict(store.get("legacy_archive_summary") or {}),
        "import_warnings": list((store.get("sync_metadata") or {}).get("import_warnings") or []),
        "market_truth_writes": 0,
        "truth_boundary": store.get("truth_boundary") or TRUTH_BOUNDARY,
    }
    with _READ_VIEW_CACHE_LOCK:
        _READ_VIEW_CACHE["signature"] = signature
        _READ_VIEW_CACHE["base"] = base
        # A new canonical snapshot invalidates cached full details.
        stale = [key for key in _DETAIL_VIEW_CACHE if key[0] != signature]
        for key in stale:
            _DETAIL_VIEW_CACHE.pop(key, None)
        if stale:
            _DETAIL_VIEW_CACHE_ORDER[:] = [key for key in _DETAIL_VIEW_CACHE_ORDER if key in _DETAIL_VIEW_CACHE]
    return base


def _cache_detail_view(signature: Any, item_id: str, value: dict[str, Any]) -> None:
    key = (signature, item_id)
    with _READ_VIEW_CACHE_LOCK:
        _DETAIL_VIEW_CACHE[key] = value
        if key in _DETAIL_VIEW_CACHE_ORDER:
            _DETAIL_VIEW_CACHE_ORDER.remove(key)
        _DETAIL_VIEW_CACHE_ORDER.append(key)
        while len(_DETAIL_VIEW_CACHE_ORDER) > _DETAIL_VIEW_CACHE_LIMIT:
            expired = _DETAIL_VIEW_CACHE_ORDER.pop(0)
            _DETAIL_VIEW_CACHE.pop(expired, None)


def backlog_view(repo: str | Path = ".", *, q: str = "", status: str = "", limit: int = 500) -> dict[str, Any]:
    base = _build_backlog_list_base(repo)
    all_rows = list(base.get("all_rows") or [])
    query = _clean(q).lower()
    status_filter = _clean(status).upper()

    def matches(row: Mapping[str, Any]) -> bool:
        if query and query not in _clean(f"{row.get('title')} {row.get('description')}").lower():
            return False
        if not status_filter:
            return True
        if status_filter == "NEW_DATA":
            return bool(row.get("has_new_data"))
        if status_filter == "TRACKING":
            return _clean(row.get("auto_status")).upper() in {"TRACKING", "TRACKING_NEW", "TRACKING_DUE"}
        return _clean(row.get("auto_status")).upper() == status_filter

    rows = [row for row in all_rows if matches(row)]
    return {
        "engine_version": base.get("engine_version") or ENGINE_VERSION,
        "status": "OK",
        "total": len(all_rows),
        "filtered": len(rows),
        "counts": dict(base.get("counts") or {}),
        "tracking_summary": dict(base.get("tracking_summary") or {}),
        "founder_inbox": list(base.get("founder_inbox") or []),
        "founder_attention_total": int(base.get("founder_attention_total") or 0),
        "items": rows[: max(1, min(int(limit or 1000), 2000))],
        "worker": dict(base.get("worker") or {}),
        "automation": dict(base.get("automation") or {}),
        "legacy_archive_summary": dict(base.get("legacy_archive_summary") or {}),
        "import_warnings": list(base.get("import_warnings") or []),
        "market_truth_writes": 0,
        "truth_boundary": base.get("truth_boundary") or TRUTH_BOUNDARY,
    }


def backlog_detail(repo: str | Path, item_id: str) -> dict[str, Any]:
    signature = _store_signature(repo)
    key = (signature, item_id)
    with _READ_VIEW_CACHE_LOCK:
        cached = _DETAIL_VIEW_CACHE.get(key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

    store = _load_store_readonly(repo)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, Mapping):
        result = {
            "status": "NOT_FOUND",
            "id": item_id,
            "market_truth_writes": 0,
            "truth_boundary": store.get("truth_boundary") or TRUTH_BOUNDARY,
        }
        _cache_detail_view(signature, item_id, result)
        return result

    result = {
        "status": "OK",
        "item": _item_for_view(item, include_history=True, include_handoff=True),
        "market_truth_writes": 0,
        "truth_boundary": store.get("truth_boundary") or TRUTH_BOUNDARY,
    }
    _cache_detail_view(signature, item_id, result)
    return copy.deepcopy(result)


def _format_tracking_cards(rows: Sequence[Mapping[str, Any]], *, limit: int) -> list[str]:
    out: list[str] = []
    ordered = sorted(
        [row for row in rows if isinstance(row, Mapping)],
        key=lambda row: _parse_time(row.get("first_seen_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    for row in ordered[:limit]:
        title = _clean(row.get("title")) or "Untitled"
        source = _clean(row.get("source")) or "source"
        excerpt = _clean(row.get("excerpt"))
        url = _clean(row.get("url"))
        first_seen = _clean(row.get("first_seen_at"))
        family = _clean(row.get("tracking_family"))
        meta = []
        if family:
            meta.append(f"family={family}")
        level = _clean(row.get("match_level"))
        if level:
            meta.append(f"relevance={level}")
        if first_seen:
            meta.append(f"first_seen={first_seen}")
        out.append(f"- [{source}] {title}" + (" | " + " | ".join(meta) if meta else ""))
        if excerpt:
            out.append(f"  {excerpt[:700]}")
        if url:
            out.append(f"  {url}")
    return out


def build_handoff_text(item: Mapping[str, Any]) -> str:
    stats = dict(item.get("material_stats") or {})
    library = item.get("material_library") if isinstance(item.get("material_library"), Mapping) else {}
    lines = [
        "SIGNALFORGE TRACKING HANDOFF",
        "",
        "IDEA",
        _clean(item.get("title")),
        "",
        "IDEA CONTEXT — UNVALIDATED",
        _clean(item.get("description")),
    ]
    context_lines = _context_lines(item)
    if context_lines:
        lines.extend(context_lines)
    lines.extend([
        "",
        "TRACKING SNAPSHOT",
        f"total_related_materials={int(stats.get('total') or 0)} | discussions={int(stats.get('discussions') or 0)} | related_products={int(stats.get('products') or 0)} | articles_research={int(stats.get('articles') or 0)} | technical={int(stats.get('technical') or 0)} | other={int(stats.get('other') or 0)}",
        f"new_since_last_report={int(stats.get('new_total') or 0)} | new_products={int(stats.get('new_products') or 0)} | last_checked={_clean(item.get('last_checked_at')) or 'never'}",
        "SignalForge only filtered for relevance and source traceability. It did NOT judge demand, WTP, market quality, or whether to build.",
        f"source_expansion={_clean(item.get('tracking_source_expansion_version')) or 'pending'} | source_expansion_pending={bool(item.get('tracking_source_expansion_pending', False))}",
        "source_family_materials=" + ", ".join(f"{k}:{v}" for k, v in list(_tracking_material_family_stats(item).items())[:10]),
        f"research_quality={_clean(item.get('tracking_research_quality_version')) or 'legacy'} | quarantined_unrelated={len(item.get('material_quarantine') or [])}",
        "source_expansion_health=" + json.dumps(item.get("tracking_expansion_health") or {}, ensure_ascii=False, sort_keys=True),
        "behavior_tracking_version=" + _clean(item.get("behavior_tracking_version")),
        "behavior_7d=" + json.dumps((item.get("behavior_windows") or {}).get("7d") or {}, ensure_ascii=False, sort_keys=True),
        "behavior_30d=" + json.dumps((item.get("behavior_windows") or {}).get("30d") or {}, ensure_ascii=False, sort_keys=True),
    ])
    patterns = [row for row in (item.get("repeated_patterns") or []) if isinstance(row, Mapping)]
    if patterns:
        lines.extend(["", "REPEATED BEHAVIOR / MENTION PATTERNS — DESCRIPTIVE ONLY"])
        for row in patterns[:12]:
            lines.append(
                f"- {_clean(row.get('canonical_label'))} | kind={_clean(row.get('evidence_kind'))} | independent_actors={int(row.get('independent_actor_count') or 0)} | materials={int(row.get('material_count') or 0)} | first_seen={_clean(row.get('first_seen'))} | last_seen={_clean(row.get('last_seen'))}"
            )
    actors = [row for row in (item.get("actor_index") or {}).values() if isinstance(row, Mapping)]
    actors.sort(key=lambda row: (_clean(row.get("last_seen_at")), int(row.get("observation_count") or 0)), reverse=True)
    if actors:
        lines.extend(["", "PUBLIC ACTORS — OBSERVATION CONTINUITY ONLY"])
        for row in actors[:20]:
            lines.append(
                f"- {_clean(row.get('display_name') or row.get('handle') or 'actor')} | platform={_clean(row.get('platform'))} | observations={int(row.get('observation_count') or 0)} | last_seen={_clean(row.get('last_seen_at'))}"
            )
            contacts = [str(x) for x in (row.get("public_contact_paths") or []) if str(x).startswith(("http://", "https://"))]
            if contacts:
                lines.append(f"  public_contact={contacts[0]}")
    sections = (
        ("RELATED PRODUCTS", "products", 20),
        ("REAL DISCUSSIONS / COMMENTS / POSTS", "discussions", 20),
        ("ARTICLES / RESEARCH / CASES", "articles", 16),
        ("GITHUB / TECHNICAL MATERIAL", "technical", 16),
        ("OTHER RELATED MATERIAL", "other", 8),
    )
    for heading, category, limit in sections:
        rows = [row for row in (library.get(category) or []) if isinstance(row, Mapping)]
        lines.extend(["", heading])
        if rows:
            lines.extend(_format_tracking_cards(rows, limit=limit))
        else:
            lines.append("- none collected yet")

    history = [row for row in (item.get("history") or []) if isinstance(row, Mapping)]
    if history:
        latest = history[-1]
        trace = latest.get("research_trace") if isinstance(latest.get("research_trace"), Mapping) else {}
        lines.extend(["", "LATEST SEARCH TRACE"])
        for run in (trace.get("query_runs") or [])[-8:]:
            if not isinstance(run, Mapping):
                continue
            lines.append(
                f"- {_clean(run.get('label'))}: {_clean(run.get('retrieval_query'))} | useful={run.get('useful_result_count', 0)} | sources={','.join(str(x) for x in (run.get('successful_sources') or []))}"
            )

    lines.extend([
        "",
        "INSTRUCTIONS FOR CHATGPT",
        "Use the material above as research inputs and do the actual analysis yourself.",
        "Separate direct source evidence from inference. Compare repeated pain, current behavior, products, pricing/WTP clues, counter-signals and gaps only when the material supports them.",
        "SignalForge relevance is not validation. Do not treat the counts or categories as a market score.",
    ])
    return "\n".join(lines).strip() + "\n"


def acknowledge_handoff(repo: str | Path, item_id: str, expected_hash: str | None = None) -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, dict):
        return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    handoff = build_handoff_text(item)
    handoff_hash = hashlib.sha256(handoff.encode("utf-8")).hexdigest()[:24]
    if not _clean(expected_hash):
        return {"status": "HANDOFF_HASH_REQUIRED", "id": item_id, "current_handoff_hash": handoff_hash, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    if _clean(expected_hash) != handoff_hash:
        return {"status": "STALE_HANDOFF", "id": item_id, "current_handoff_hash": handoff_hash, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    item["founder_reviewed_at"] = _now()
    item["tracking_last_reported_at"] = item["founder_reviewed_at"]
    item["founder_reviewed_research_count"] = len(item.get("history") or [])
    item["founder_reviewed_handoff_hash"] = handoff_hash
    item["latest_change"] = "TRACKING_HANDOFF_COPIED"
    item["updated_at"] = _now()
    _refresh_material_stats(item)
    save_store(repo, store)
    return {
        "status": "ACKNOWLEDGED",
        "id": item_id,
        "handoff_hash": handoff_hash,
        "founder_reviewed_at": item["founder_reviewed_at"],
        "new_material_count": int(item.get("new_material_count") or 0),
        "market_truth_writes": 0,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def import_trend_snapshots(repo: str | Path, item_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Import provider-neutral/manual trend snapshots without treating them as market truth."""
    store = load_store(repo, repair_worker=False)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, dict):
        return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    normalized = ManualTrendsProvider.normalize(rows)
    existing = item.setdefault("trend_snapshots", [])
    seen = {
        (_clean(row.get("provider")), _clean(row.get("term")), _clean(row.get("geo")), _clean(row.get("period_start")), _clean(row.get("period_end")), _clean(row.get("interval")))
        for row in existing if isinstance(row, Mapping)
    }
    added = 0
    for row in normalized:
        key = (_clean(row.get("provider")), _clean(row.get("term")), _clean(row.get("geo")), _clean(row.get("period_start")), _clean(row.get("period_end")), _clean(row.get("interval")))
        if key in seen:
            continue
        existing.append(dict(row))
        seen.add(key)
        added += 1
    if len(existing) > 500:
        del existing[: len(existing) - 500]
    item["trend_provider_status"] = {"provider": "MANUAL_TRENDS_IMPORT", "status": "AVAILABLE", "last_import_at": _now()}
    item["latest_change"] = "TREND_SNAPSHOTS_IMPORTED"
    item["updated_at"] = _now()
    save_store(repo, store)
    return {"status": "IMPORTED", "id": item_id, "added": added, "total": len(existing), "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


def request_tracking_refresh(repo: str | Path, item_id: str) -> dict[str, Any]:
    store = load_store(repo, repair_worker=False)
    item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
    if not isinstance(item, dict):
        return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}
    item["tracking_enabled"] = True
    item["auto_status"] = "TRACKING_DUE"
    item["next_track_after"] = _now()
    item["current_call"] = "已排入立即追蹤"
    item["why"] = "Founder requested a fresh related-material search."
    item["latest_change"] = "TRACKING_REFRESH_REQUESTED"
    item["updated_at"] = _now()
    save_store(repo, store)
    return {"status": "TRACKING_REFRESH_REQUESTED", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}


async def run_single_item(
    repo: str | Path,
    item_id: str,
    *,
    research_fn: Callable[[str, str], Awaitable[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Research exactly one direction without resuming or mutating global automation."""
    repo = str(Path(repo).resolve())
    await asyncio.to_thread(_SINGLE_ITEM_RUN_LOCK.acquire)
    try:
        store = load_store(repo, repair_worker=False)
        item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
        if not isinstance(item, dict):
            return {"status": "NOT_FOUND", "id": item_id, "market_truth_writes": 0, "truth_boundary": TRUTH_BOUNDARY}

        paused_before = bool((store.get("automation") or {}).get("paused_by_founder", False))
        started_at = _now()
        item["auto_status"] = "SEARCHING"
        item["current_call"] = "正在研究這一條"
        item["why"] = "Founder requested research for this direction only; global auto tracking is unchanged."
        item["latest_change"] = "SINGLE_ITEM_RESEARCH_STARTED"
        item["updated_at"] = started_at
        title, description = _job_prompt(item, "BASELINE")
        save_store(repo, store)

        result: Mapping[str, Any] | None = None
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                candidate = await research_fn(title, description)
                if not isinstance(candidate, Mapping):
                    raise RuntimeError("research_fn returned non-mapping result")
                live_store = load_store(repo, repair_worker=False)
                live_item = (live_store.get("items") or {}).get(item_id) or {}
                result = _quality_filter_result(live_item, "BASELINE", candidate)
                if not _research_transport_limited(result) or attempt >= 1:
                    break
                await asyncio.sleep(0.2 * (2 ** attempt))
            except Exception as exc:
                last_exc = exc
                if attempt < 1:
                    await asyncio.sleep(0.2 * (2 ** attempt))
                    continue
                break

        store = load_store(repo, repair_worker=False)
        item = (store.get("items") or {}).get(item_id) if isinstance(store.get("items"), Mapping) else None
        if not isinstance(item, dict):
            raise RuntimeError(f"research backlog item {item_id!r} disappeared during research")
        paused_after = bool((store.get("automation") or {}).get("paused_by_founder", False))
        completed_at = _now()
        if result is None:
            exc = last_exc or RuntimeError("single-item research failed without a result")
            item["auto_status"] = "SOURCE_LIMITED"
            item["current_call"] = "來源暫時受限"
            item["why"] = f"單項研究來源失敗（已 bounded retry）：{type(exc).__name__}: {exc}"
            item["latest_change"] = "SINGLE_ITEM_RESEARCH_FAILED"
            item["updated_at"] = completed_at
            save_store(repo, store)
            raise RuntimeError(item["why"]) from exc

        history = item.setdefault("history", [])
        history.append(_history_snapshot("TRACK", result, started_at, completed_at))
        while len(history) > 60:
            del history[0]
        added = _merge_material_result(item, result, completed_at)
        item["tracking_cycle_count"] = int(item.get("tracking_cycle_count") or 0) + 1
        item["tracking_source_expansion_version"] = _TRACKING_SOURCE_EXPANSION_VERSION
        expansion_health = _tracking_expansion_health(item, result)
        item["tracking_expansion_health"] = expansion_health
        item["tracking_source_expansion_pending"] = not bool(expansion_health.get("complete"))
        interval = max(3600, int((store.get("automation") or {}).get("tracking_interval_seconds") or _TRACKING_INTERVAL_SECONDS))
        next_delay = interval if bool(expansion_health.get("complete")) else min(interval, 3600)
        item["last_checked_at"] = completed_at
        item["next_track_after"] = (datetime.now(timezone.utc) + timedelta(seconds=next_delay)).isoformat()
        item["next_job"] = None
        _clear_source_retry(item)
        item["auto_status"] = "TRACKING" if bool(expansion_health.get("complete")) else "TRACKING_DUE"
        item["current_call"] = "單項研究完成"
        item["why"] = f"本輪新增 {int(added.get('total') or 0)} 筆相關資料；全域自動追蹤設定未變更。"
        item["needs_founder"] = False
        item["latest_change"] = "SINGLE_ITEM_RESEARCH_COMPLETED"
        item["updated_at"] = completed_at
        _refresh_accumulated_state(item)
        save_store(repo, store)
        return {
            "status": "SINGLE_ITEM_RESEARCH_COMPLETED",
            "id": item_id,
            "materials_added": int(added.get("total") or 0),
            "history_count": len(history),
            "paused_before": paused_before,
            "paused_after": paused_after,
            "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        }
    finally:
        _SINGLE_ITEM_RUN_LOCK.release()


async def run_batch(
    repo: str | Path,
    *,
    research_fn: Callable[[str, str], Awaitable[Mapping[str, Any]]],
    max_jobs: int = 200,
    delay_seconds: float = 0.15,
    concurrency: int | None = None,
) -> dict[str, Any]:
    """Run related-material tracking with bounded network concurrency and serialized commits."""
    repo = str(Path(repo).resolve())
    max_jobs = max(1, min(int(max_jobs or 200), 1000))
    store = load_store(repo, repair_worker=True)
    automation = store.setdefault("automation", dict(_default_store()["automation"]))
    configured = int(automation.get("research_concurrency") or _DEFAULT_RESEARCH_CONCURRENCY)
    concurrency = configured if concurrency is None else int(concurrency)
    concurrency = max(1, min(concurrency, _MAX_RESEARCH_CONCURRENCY, max_jobs))
    worker = store.setdefault("worker", {})
    worker.update({
        "status": "RUNNING",
        "started_at": _now(), "finished_at": None,
        "current_item_id": None, "current_job": None,
        "jobs_completed": 0, "jobs_requested": max_jobs,
        "last_error": None, "stop_requested": False,
        "retry_attempts": 0, "active_jobs": [], "active_count": 0,
        "max_concurrency": concurrency,
        "queued_jobs_estimate": _pending_job_estimate(store),
        "last_wave_started_at": None, "last_wave_completed_at": None,
    })
    worker.setdefault("consecutive_source_limited", 0)
    save_store(repo, store)

    completed = 0
    try:
        while completed < max_jobs:
            store = load_store(repo, repair_worker=False)
            worker = store.setdefault("worker", {})
            automation = store.get("automation") if isinstance(store.get("automation"), Mapping) else {}
            if worker.get("stop_requested") or bool(automation.get("paused_by_founder", False)):
                worker["status"] = "STOPPED"
                worker["finished_at"] = _now()
                worker["active_jobs"] = []
                worker["active_count"] = 0
                worker["current_item_id"] = None
                worker["current_job"] = None
                worker["queued_jobs_estimate"] = _pending_job_estimate(store)
                save_store(repo, store)
                break

            wave_limit = min(concurrency, max_jobs - completed)
            reserved: list[dict[str, Any]] = []
            wave_started = _now()
            while len(reserved) < wave_limit:
                selected = _select_next_item(store)
                if not selected:
                    break
                item_id, _ = selected
                item = (store.get("items") or {}).get(item_id)
                if not isinstance(item, dict):
                    break
                item["auto_status"] = "SEARCHING"
                item["current_call"] = "正在找相關資料"
                item["why"] = "搜尋相關討論、產品、文章／研究與技術資料；不做市場判斷。"
                item["latest_change"] = "TRACKING_SEARCH_STARTED"
                item["updated_at"] = _now()
                title, description = _job_prompt(item, "BASELINE")
                reserved.append({
                    "item_id": item_id,
                    "job": "BASELINE",
                    "title": title,
                    "description": description,
                    "started_at": _now(),
                })

            if not reserved:
                worker["status"] = "IDLE"
                worker["finished_at"] = _now()
                worker["active_jobs"] = []
                worker["active_count"] = 0
                worker["current_item_id"] = None
                worker["current_job"] = None
                worker["queued_jobs_estimate"] = _pending_job_estimate(store)
                save_store(repo, store)
                break

            worker["active_jobs"] = [
                {"item_id": row["item_id"], "job": "TRACK", "started_at": row["started_at"]}
                for row in reserved
            ]
            worker["active_count"] = len(reserved)
            worker["current_item_id"] = reserved[0]["item_id"]
            worker["current_job"] = "TRACK"
            worker["max_concurrency"] = concurrency
            worker["last_wave_started_at"] = wave_started
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            save_store(repo, store)

            async def execute_one(entry: Mapping[str, Any]) -> dict[str, Any]:
                result: Mapping[str, Any] | None = None
                last_exc: Exception | None = None
                retry_count = 0
                for attempt in range(2):
                    try:
                        candidate = await research_fn(str(entry["title"]), str(entry["description"]))
                        if not isinstance(candidate, Mapping):
                            raise RuntimeError("research_fn returned non-mapping result")
                        live_store = load_store(repo, repair_worker=False)
                        live_item = (live_store.get("items") or {}).get(str(entry["item_id"])) or {}
                        result = _quality_filter_result(live_item, "BASELINE", candidate)
                        if not _research_transport_limited(result) or attempt >= 1:
                            break
                        retry_count += 1
                        await asyncio.sleep(max(0.0, delay_seconds) + 0.2 * (2 ** attempt))
                    except Exception as exc:
                        last_exc = exc
                        if attempt < 1:
                            retry_count += 1
                            await asyncio.sleep(max(0.0, delay_seconds) + 0.2 * (2 ** attempt))
                            continue
                        break
                return {"result": result, "exception": last_exc, "retry_count": retry_count, "completed_at": _now()}

            outcomes = await asyncio.gather(*(execute_one(row) for row in reserved))
            store = load_store(repo, repair_worker=False)
            worker = store.setdefault("worker", {})
            circuit_opened = False
            interval = max(3600, int((store.get("automation") or {}).get("tracking_interval_seconds") or _TRACKING_INTERVAL_SECONDS))
            for entry, outcome in zip(reserved, outcomes):
                item_id = str(entry["item_id"])
                live_item = (store.get("items") or {}).get(item_id)
                worker["retry_attempts"] = int(worker.get("retry_attempts") or 0) + int(outcome.get("retry_count") or 0)
                result = outcome.get("result")
                completed_at = str(outcome.get("completed_at") or _now())
                if result is None:
                    exc = outcome.get("exception") or RuntimeError("tracking execution failed without a result")
                    if isinstance(live_item, dict):
                        live_item["auto_status"] = "SOURCE_LIMITED"
                        live_item["current_call"] = "來源暫時受限"
                        live_item["why"] = f"追蹤來源失敗（已 bounded retry）：{type(exc).__name__}: {exc}"
                        live_item["next_job"] = "BASELINE"
                        _schedule_source_retry(live_item, "BASELINE", live_item["why"])
                        live_item["latest_change"] = "TRACKING_SOURCE_LIMITED"
                        live_item["updated_at"] = _now()
                    worker["last_error"] = f"{type(exc).__name__}: {exc}"
                    circuit_opened = _record_source_health(store, limited=True, reason=worker["last_error"]) or circuit_opened
                else:
                    assert isinstance(result, Mapping)
                    if isinstance(live_item, dict):
                        history = live_item.setdefault("history", [])
                        snapshot = _history_snapshot("TRACK", result, str(entry["started_at"]), completed_at)
                        history.append(snapshot)
                        # Keep bounded audit history; the durable material_library survives independently.
                        while len(history) > 60:
                            del history[0]
                        added = _merge_material_result(live_item, result, completed_at)
                        live_item["tracking_cycle_count"] = int(live_item.get("tracking_cycle_count") or 0) + 1
                        live_item["tracking_source_expansion_version"] = _TRACKING_SOURCE_EXPANSION_VERSION
                        expansion_health = _tracking_expansion_health(live_item, result)
                        live_item["tracking_expansion_health"] = expansion_health
                        live_item["tracking_source_expansion_pending"] = not bool(expansion_health.get("complete"))
                        live_item["last_checked_at"] = completed_at
                        next_delay = interval if bool(expansion_health.get("complete")) else min(interval, 3600)
                        live_item["next_track_after"] = (datetime.now(timezone.utc) + timedelta(seconds=next_delay)).isoformat()
                        live_item["next_job"] = None
                        _clear_source_retry(live_item)
                        expansion_complete = bool(expansion_health.get("complete"))
                        live_item["auto_status"] = "TRACKING" if expansion_complete else "TRACKING_DUE"
                        live_item["current_call"] = (
                            ("有新資料" if int(added.get("total") or 0) > 0 else "自動追蹤中")
                            if expansion_complete else "來源擴展尚未完整，稍後補搜"
                        )
                        live_item["why"] = (
                            f"本輪新增 {int(added.get('total') or 0)} 筆相關資料，其中相關產品 {int(added.get('products') or 0)} 筆。"
                            if expansion_complete and int(added.get("total") or 0) > 0
                            else (
                                "本輪沒有新的不重複相關資料；既有資料完整保留，之後會再追蹤。"
                                if expansion_complete
                                else "本輪部分必要 source family 未健康完成；不是市場 0，已保留 pending 並在一小時後 bounded retry。"
                            )
                        )
                        live_item["needs_founder"] = False
                        live_item["latest_change"] = "TRACKING_CYCLE_COMPLETED"
                        live_item["updated_at"] = _now()
                        _refresh_accumulated_state(live_item)
                    limited_now = _research_transport_limited(result)
                    circuit_opened = _record_source_health(
                        store,
                        limited=bool(limited_now),
                        reason=("transport/source outage while tracking" if limited_now else ""),
                    ) or circuit_opened
                completed += 1

            worker = store.setdefault("worker", {})
            worker["jobs_completed"] = completed
            worker["active_jobs"] = []
            worker["active_count"] = 0
            worker["current_item_id"] = None
            worker["current_job"] = None
            worker["last_wave_completed_at"] = _now()
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            paused_now = bool((store.get("automation") or {}).get("paused_by_founder", False))
            stopped_now = bool(worker.get("stop_requested"))
            worker["status"] = "SOURCE_CIRCUIT_OPEN" if circuit_opened else ("STOPPED" if paused_now or stopped_now else "RUNNING")
            save_store(repo, store)
            if circuit_opened or paused_now or stopped_now:
                break
            if completed < max_jobs:
                await asyncio.sleep(max(0.0, delay_seconds))

        store = load_store(repo, repair_worker=False)
        worker = store.setdefault("worker", {})
        if worker.get("status") == "RUNNING":
            worker["status"] = "BATCH_LIMIT_REACHED" if _select_next_item(store) else "IDLE"
            worker["finished_at"] = _now()
            worker["active_jobs"] = []
            worker["active_count"] = 0
            worker["current_item_id"] = None
            worker["current_job"] = None
            worker["queued_jobs_estimate"] = _pending_job_estimate(store)
            save_store(repo, store)
        return {
            "status": worker.get("status"),
            "jobs_completed": completed,
            "max_concurrency": concurrency,
            "queued_jobs_estimate": int(worker.get("queued_jobs_estimate") or 0),
            "market_truth_writes": 0,
            "truth_boundary": TRUTH_BOUNDARY,
        }
    except Exception as exc:
        store = load_store(repo, repair_worker=False)
        worker = store.setdefault("worker", {})
        worker["status"] = "FAILED"
        worker["finished_at"] = _now()
        worker["active_jobs"] = []
        worker["active_count"] = 0
        worker["current_item_id"] = None
        worker["current_job"] = None
        worker["queued_jobs_estimate"] = _pending_job_estimate(store)
        worker["last_error"] = f"{type(exc).__name__}: {exc}"
        save_store(repo, store)
        raise
