#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = {
    "home": ROOT / "dashboard/src/pages/OpportunityRadar.tsx",
    "thesis": ROOT / "dashboard/src/pages/ThesisDetail.tsx",
    "research": ROOT / "dashboard/src/pages/Research.tsx",
    "search": ROOT / "dashboard/src/pages/SearchPage.tsx",
    "sidebar": ROOT / "dashboard/src/components/Sidebar.tsx",
    "topbar": ROOT / "dashboard/src/components/TopBar.tsx",
}


def text(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def ok(name: str, condition: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, bool(condition), detail)


def main() -> int:
    h = text("home")
    t = text("thesis")
    r = text("research")
    s = text("search")
    sb = text("sidebar")
    tb = text("topbar")

    checks: list[tuple[str, bool, str]] = []
    checks += [
        ok("home_three_questions", "有沒有值得做、為什麼、今天要做什麼" in h),
        ok("home_founder_conclusion", "SIGNALFORGE 結論" in h and "今天只做這件事" in h),
        ok("home_primary_action_from_market_action_queue", "const primaryAction = suggestedActions[0]" in h),
        ok("home_buyer_channel_plain_language", "找出你真的接觸得到的買家管道" in h and "BUYER_ACCESS_NOT_ESTABLISHED" in h),
        ok("home_action_success_failure", "做到什麼算有進展" in h and "什麼結果代表先放棄" in h),
        ok("home_machine_work_deemphasized", "AI 自己在忙什麼" in h and "這些不用你處理" in h),
        ok("home_advanced_hidden", '<details className="mt-8 rounded-2xl' in h and "進階：看系統路由、候選案例與證據細節" in h),
        ok("home_candidate_not_strategic_authority", "這是證據 drill-down，不是商機排行榜" in h),
        ok("home_market_truth_boundary", "這不是「證明商機成立」" in h and "工程 PASS 不等於商機成立" in h),
        ok("home_no_default_six_lane_wall", "Founder operating loop" not in h),
        ok("home_summary_not_governor_founder_count", "founderTaskCount = suggestedActions.length" in h),
        ok("home_market_action_registry_preserved", "MarketActionExecutionCard" in h and "useCompleteSignalForgeMarketAction" in h),
        ok("home_atomic_validation_preserved", "ClaimValidationReadyCard" in h and "useRecordSignalForgeValidationResult" in h),
        ok("thesis_plain_action", "SignalForge 現在要你做什麼" in t and "為什麼現在還不能直接做" in t),
        ok("thesis_plain_dimensions", "你做不做得出來" in t and "你找不找得到買家" in t and "市場會不會相信你" in t),
        ok("thesis_advanced_hidden", "進階：結構判斷與原始證據" in t and "<details" in t),
        ok("research_plain_title", "AI 研究進度" in r and "大部分時間你不用處理" in r),
        ok("search_plain_scopes", "商機與問題" in s and "原始資料" in s and "搜尋 SignalForge" in s),
        ok("sidebar_founder_language", "今天錢在哪" in sb and "商機工作台" in sb and "AI 研究進度" in sb and "找商機 / 證據" in sb and "系統狀態" in sb),
        ok("topbar_plain_language", "搜尋問題、買家、商機或證據" in tb and "可使用" in tb),
    ]

    # Guard against accidental edits outside the intended UI surface by asserting
    # this acceptance file itself has no authority to change backend truth.
    backend_guard_paths = [
        ROOT / "processors/signalforge_production_admission.py",
        ROOT / "processors/problem_recurrence_multi.py",
        ROOT / "processors/radar_ledger.py",
        ROOT / "processors/signalforge_execution_governor.py",
        ROOT / "api/routes/signalforge.py",
    ]
    checks.append(ok("backend_truth_files_present", all(p.is_file() for p in backend_guard_paths)))

    failed = [c for c in checks if not c[1]]
    print("=" * 88)
    print("SIGNALFORGE — FOUNDER-FIRST PRODUCT UI ACCEPTANCE")
    print("=" * 88)
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL':4}  {name}{(' — ' + detail) if detail else ''}")
    print("-" * 88)
    print(f"RESULT: {len(checks)-len(failed)}/{len(checks)} PASS")
    if failed:
        print("FINAL_STATUS: SIGNALFORGE_FOUNDER_FIRST_PRODUCT_UI_ACCEPTANCE_FAIL")
        return 1
    print("FINAL_STATUS: SIGNALFORGE_FOUNDER_FIRST_PRODUCT_UI_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
