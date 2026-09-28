# Patch AI Opportunity Radar to expose tracked LLM spend in the dashboard.
# Run from the community-mind-mirror project root.

from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
FILES = {
    "tracker": ROOT / "spending_tracker.py",
    "api": ROOT / "api" / "main.py",
    "client": ROOT / "dashboard" / "src" / "api" / "client.ts",
    "hooks": ROOT / "dashboard" / "src" / "api" / "hooks.ts",
    "dashboard": ROOT / "dashboard" / "src" / "pages" / "Dashboard.tsx",
}

missing = [str(p) for p in FILES.values() if not p.exists()]
if missing:
    print("ERROR: Required files not found:")
    for p in missing:
        print(" -", p)
    print("\nRun this script from the community-mind-mirror project root.")
    sys.exit(1)

def backup(path: Path):
    dest = path.with_name(path.name + ".before_ai_spend.bak")
    if not dest.exists():
        shutil.copy2(path, dest)
        print(f"Backup: {dest.relative_to(ROOT)}")
    return dest

for p in FILES.values():
    backup(p)

# 1) spending_tracker.py
p = FILES["tracker"]
s = p.read_text(encoding="utf-8")

if "def get_spending_data()" not in s:
    marker = "\ndef get_spending_html() -> str:\n"
    if marker not in s:
        print("ERROR: Could not find get_spending_html() in spending_tracker.py")
        sys.exit(1)

    block = """
def get_spending_data() -> dict:
    \"""Return structured project-local LLM spend data for the dashboard.

    This is the spend recorded by this repository's record_spend() calls.
    It is not the user's account-wide OpenAI billing total.
    \"""
    data = _load()
    total = float(data.get("total_spent_usd", 0.0) or 0.0)
    cap = float(data.get("cap_usd", DEFAULT_CAP) or 0.0)
    remaining = max(cap - total, 0.0)
    pct = (total / cap * 100) if cap > 0 else 0.0
    history = data.get("history", []) or []

    local_now = datetime.now().astimezone()
    local_date = local_now.date()
    today_spent = 0.0
    today_calls = 0

    for item in history:
        raw_ts = item.get("timestamp")
        if raw_ts:
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts.astimezone().date() == local_date:
                    today_spent += float(item.get("cost_usd", 0.0) or 0.0)
                    today_calls += 1
            except (TypeError, ValueError):
                pass

    recent = []
    for item in reversed(history[-10:]):
        recent.append({
            "phase": item.get("phase", "unknown"),
            "cost_usd": float(item.get("cost_usd", 0.0) or 0.0),
            "cumulative_usd": float(item.get("cumulative_usd", 0.0) or 0.0),
            "details": item.get("details", ""),
            "timestamp": item.get("timestamp"),
        })

    return {
        "currency": "USD",
        "tracked_scope": "community-mind-mirror",
        "total_spent_usd": round(total, 6),
        "today_spent_usd": round(today_spent, 6),
        "today_calls": today_calls,
        "cap_usd": round(cap, 6),
        "remaining_usd": round(remaining, 6),
        "used_pct": round(pct, 3),
        "history_count": len(history),
        "recent": recent,
        "updated_at": local_now.isoformat(),
    }

"""
    s = s.replace(marker, "\n" + block + marker, 1)
    p.write_text(s, encoding="utf-8")
    print("PATCHED: spending_tracker.py")
else:
    print("ALREADY OK: spending_tracker.py")

# 2) api/main.py
p = FILES["api"]
s = p.read_text(encoding="utf-8")

endpoint = """

@app.get("/api/system/spending")
async def spending_status():
    \"""Project-local LLM spend recorded by spending_tracker.py.\"""
    from spending_tracker import get_spending_data
    return get_spending_data()
"""

if '@app.get("/api/system/spending")' not in s:
    health_block = """@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "community-mind-mirror"}
"""
    if health_block not in s:
        print("ERROR: Could not find health endpoint insertion point in api/main.py")
        sys.exit(1)
    s = s.replace(health_block, health_block + endpoint, 1)
    p.write_text(s, encoding="utf-8")
    print("PATCHED: api/main.py")
else:
    print("ALREADY OK: api/main.py")

# 3) dashboard/src/api/client.ts
p = FILES["client"]
s = p.read_text(encoding="utf-8")

if "export interface SpendingStatus" not in s:
    marker = "export interface SearchResults {"
    idx = s.find(marker)
    if idx == -1:
        print("ERROR: Could not find type insertion point in client.ts")
        sys.exit(1)

    type_block = """export interface SpendingHistoryItem {
  phase: string;
  cost_usd: number;
  cumulative_usd: number;
  details: string;
  timestamp: string | null;
}

export interface SpendingStatus {
  currency: "USD";
  tracked_scope: string;
  total_spent_usd: number;
  today_spent_usd: number;
  today_calls: number;
  cap_usd: number;
  remaining_usd: number;
  used_pct: number;
  history_count: number;
  recent: SpendingHistoryItem[];
  updated_at: string;
}

"""
    s = s[:idx] + type_block + s[idx:]
    print("PATCHED: client.ts types")

if 'spending: () => fetchJSON<SpendingStatus>("/system/spending")' not in s:
    marker = '  health: () => fetchJSON<{ status: string }>("/health"),\n'
    if marker not in s:
        print("ERROR: Could not find health API function in client.ts")
        sys.exit(1)
    s = s.replace(
        marker,
        marker + '  spending: () => fetchJSON<SpendingStatus>("/system/spending"),\n',
        1,
    )
    print("PATCHED: client.ts api.spending")

p.write_text(s, encoding="utf-8")

# 4) dashboard/src/api/hooks.ts
p = FILES["hooks"]
s = p.read_text(encoding="utf-8")

if "export function useSpendingStatus()" not in s:
    marker = """export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 10_000, refetchInterval: 30_000 });
}
"""
    if marker not in s:
        print("ERROR: Could not find useHealth() in hooks.ts")
        sys.exit(1)

    addition = """
export function useSpendingStatus() {
  return useQuery({
    queryKey: ["spendingStatus"],
    queryFn: api.spending,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
"""
    s = s.replace(marker, marker + addition, 1)
    p.write_text(s, encoding="utf-8")
    print("PATCHED: hooks.ts")
else:
    print("ALREADY OK: hooks.ts")

# 5) dashboard/src/pages/Dashboard.tsx
p = FILES["dashboard"]
s = p.read_text(encoding="utf-8")

if "useSpendingStatus" not in s:
    target = "  useJobIntelSummary, useJobIntelHiring, useJobIntelTechStack,\n"
    if target not in s:
        print("ERROR: Could not find hook import insertion point in Dashboard.tsx")
        sys.exit(1)
    s = s.replace(target, target + "  useSpendingStatus,\n", 1)
    print("PATCHED: Dashboard import")

if "const { data: spending } = useSpendingStatus();" not in s:
    target = '  const { data: jobIntelTech } = useJobIntelTechStack({ limit: "10" });\n'
    if target not in s:
        print("ERROR: Could not find hook call insertion point in Dashboard.tsx")
        sys.exit(1)
    s = s.replace(target, target + "  const { data: spending } = useSpendingStatus();\n", 1)
    print("PATCHED: Dashboard data hook")

s = s.replace(
    '<div className="grid grid-cols-2 md:grid-cols-4 gap-3">',
    '<div className="grid grid-cols-2 md:grid-cols-5 gap-3">',
    2,
)

if 'label="Tracked AI spend"' not in s:
    candidates = [
        '        <MetricCard label="Hype vs reality gap" value={(hypeIndex || []).length > 0 ? ((hypeIndex || [])[0]?.gap ?? 0).toFixed(2) : "—"} valueColor="text-warning" />\n',
        '        <MetricCard label="Hype vs reality gap" value={(hypeIndex || []).length > 0 ? ((hypeIndex || [])[0]?.gap ?? 0).toFixed(2) : "—"} subtext="moderate divergence" valueColor="text-warning" />\n',
    ]
    insert_after = next((x for x in candidates if x in s), None)
    if insert_after is None:
        print("ERROR: Could not find Hype metric insertion point in Dashboard.tsx")
        sys.exit(1)

    card = """        <MetricCard
          label="Tracked AI spend"
          value={formatUsd(spending?.total_spent_usd)}
          badge={spending ? `${formatUsd(spending.today_spent_usd)} today` : undefined}
          badgeType={spending && spending.used_pct >= 90 ? "danger" : spending && spending.used_pct >= 70 ? "warning" : "info"}
          subtext={spending ? `${formatUsd(spending.remaining_usd)} left of ${formatUsd(spending.cap_usd)}` : "Loading…"}
          valueColor={spending && spending.used_pct >= 90 ? "text-danger" : spending && spending.used_pct >= 70 ? "text-warning" : "text-info"}
        />
"""
    s = s.replace(insert_after, insert_after + card, 1)
    print("PATCHED: Dashboard spend card")

if "function formatUsd(" not in s:
    marker = "\nfunction MetricCard("
    if marker not in s:
        print("ERROR: Could not find MetricCard helper insertion point")
        sys.exit(1)

    helper = """
function formatUsd(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  if (value > 0 && value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

"""
    s = s.replace(marker, "\n" + helper + "function MetricCard(", 1)
    print("PATCHED: Dashboard USD formatter")

p.write_text(s, encoding="utf-8")

print("\n============================================================")
print("AI SPEND DASHBOARD PATCH COMPLETE")
print("============================================================")
print("Next:")
print("1. Open http://localhost:8000/api/system/spending")
print("2. Refresh http://localhost:5173")
print("3. Look for the 'Tracked AI spend' card.")
print()
print("This is project-local tracked/estimated LLM spend, not account-wide OpenAI billing.")
print("Rollback files end with .before_ai_spend.bak")
