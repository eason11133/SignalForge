from pathlib import Path
import shutil
import sys

p = Path("dashboard/src/pages/Dashboard.tsx")
if not p.exists():
    print(f"ERROR: {p} not found. Run this from the community-mind-mirror project root.")
    sys.exit(1)

backup = p.with_suffix(p.suffix + ".bak")
if not backup.exists():
    shutil.copy2(p, backup)
    print(f"Backup created: {backup}")

s = p.read_text(encoding="utf-8")

replacements = [
    (
        '<MetricCard label="Tracked users" value={formatNumber(overview?.total_users || 0)} badge="+312 this week" badgeType="success" />',
        '<MetricCard label="Tracked users" value={formatNumber(overview?.total_users || 0)} />',
        "remove hard-coded weekly user growth",
    ),
    (
        '<MetricCard label="Posts today" value={formatNumber(overview?.total_posts || 0)} badge={`${Object.keys(overview?.news_by_source || {}).length} platforms`} badgeType="info" />',
        '<MetricCard label="Total posts" value={formatNumber(overview?.total_posts || 0)} />',
        "fix total-posts metric label and misleading platform badge",
    ),
    (
        '<MetricCard label="Hype vs reality gap" value={(hypeIndex || []).length > 0 ? ((hypeIndex || [])[0]?.gap ?? 0).toFixed(2) : "—"} subtext="moderate divergence" valueColor="text-warning" />',
        '<MetricCard label="Hype vs reality gap" value={(hypeIndex || []).length > 0 ? ((hypeIndex || [])[0]?.gap ?? 0).toFixed(2) : "—"} valueColor="text-warning" />',
        "remove hard-coded divergence claim",
    ),
    (
        '<p className="text-[12px] text-text-secondary mb-3">Most discussed unresolved problems this week</p>',
        '<p className="text-[12px] text-text-secondary mb-3">Unresolved problems detected from the last 30 days</p>',
        "match pain-point UI window to processor",
    ),
    (
        'const intensity = pp.intensity_score != null ? Math.round(pp.intensity_score * 100) : 0;',
        'const intensity = pp.intensity_score != null ? Math.round(pp.intensity_score) : 0;',
        "fix pain-point intensity 0-100 rendering",
    ),
    (
        '{Math.round(((jobIntelSummary.by_remote_policy.find(r => r.policy === "fully_remote")?.count || 0) / jobIntelSummary.total_processed) * 100)}%',
        '{jobIntelSummary.total_processed > 0 ? Math.round(((jobIntelSummary.by_remote_policy.find(r => r.policy === "fully_remote")?.count || 0) / jobIntelSummary.total_processed) * 100) : 0}%',
        "avoid NaN remote percentage",
    ),
    (
        '{Math.round(((jobIntelSummary.by_ai_level.find(r => r.level === "core_product")?.count || 0) / jobIntelSummary.total_processed) * 100)}%',
        '{jobIntelSummary.total_processed > 0 ? Math.round(((jobIntelSummary.by_ai_level.find(r => r.level === "core_product")?.count || 0) / jobIntelSummary.total_processed) * 100) : 0}%',
        "avoid NaN AI-core percentage",
    ),
]

changed = 0
for old, new, label in replacements:
    if old in s:
        s = s.replace(old, new)
        changed += 1
        print(f"PATCHED: {label}")
    elif new in s:
        print(f"ALREADY OK: {label}")
    else:
        print(f"WARNING: pattern not found: {label}")

p.write_text(s, encoding="utf-8")

print(f"\nDone. {changed} change(s) applied.")
print("Vite should hot-reload automatically. Refresh http://localhost:5173 if needed.")
print(f"Rollback file: {backup}")
