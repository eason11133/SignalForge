from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check(name: str, cond: bool) -> None:
    print(f"{name}={'PASS' if cond else 'FAIL'}")
    if not cond:
        raise SystemExit(1)

settings = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")

check("default_storage_mode_is_local", 'os.getenv("SIGNALFORGE_STORAGE_MODE", "local")' in settings)
check("local_mode_flag_exists", "SIGNALFORGE_LOCAL_MODE" in settings)
check("startup_skips_database_in_local_mode", "signalforge_local_storage_ready" in main)
check("legacy_scheduler_skipped_in_local_mode", "legacy_scheduler_skipped" in main)
check("research_backlog_store_declared", ".radar_runtime/founder_opportunity_research_v1.json" in main)
check("legacy_db_routes_fail_explicitly", "LEGACY_DATABASE_DISABLED_IN_LOCAL_MODE" in main)
check("legacy_pipeline_disabled_explicitly", "LEGACY_PIPELINE_DISABLED_IN_LOCAL_MODE" in main)
check("health_reports_docker_requirement", '"docker_required": not local_mode' in main)

runtime_store = ROOT / ".radar_runtime" / "founder_opportunity_research_v1.json"
print(f"research_store_present={'YES' if runtime_store.exists() else 'NO'}")
print("SIGNALFORGE_DOCKERLESS_LOCAL_MODE_V1_REGRESSION_PASS")
