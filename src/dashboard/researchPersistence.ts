/* SignalForge V2.5.3.1 lightweight research status bridge.
 * Research stays server-owned. UI status uses cached state first and only
 * revalidates at a bounded cadence while this tab is visible.
 */
type Run = {
  run_id?: string;
  item_key?: string;
  status?: string;
  material_count?: number | null;
  completed_units?: number | null;
  total_units?: number | null;
  duplicate_start_suppressed?: number;
  updated_at?: string;
};

const ID = "signalforge-v253-run-pill";
const ACTIVE_STATUSES = new Set(["QUEUED", "RUNNING", "RESUMING", "STOPPING"]);
const ACTIVE_POLL_MS = 12_000;
const IDLE_POLL_MS = 30_000;
const FOCUS_STALE_MS = 15_000;

let lastRuns: Run[] = [];
let lastPollAt = 0;
let timer: number | undefined;
let inflight: Promise<void> | null = null;

function activeRuns(runs: Run[]) {
  return runs.filter((r) => ACTIVE_STATUSES.has(String(r.status || "")));
}

function ensurePill(): HTMLDivElement {
  let el = document.getElementById(ID) as HTMLDivElement | null;
  if (el) return el;
  el = document.createElement("div");
  el.id = ID;
  el.setAttribute("aria-live", "polite");
  Object.assign(el.style, {
    position: "fixed",
    right: "18px",
    bottom: "18px",
    zIndex: "9999",
    maxWidth: "360px",
    padding: "9px 12px",
    borderRadius: "12px",
    background: "rgba(15, 23, 42, 0.92)",
    color: "#fff",
    fontSize: "12px",
    lineHeight: "1.45",
    boxShadow: "0 8px 24px rgba(0,0,0,.18)",
    backdropFilter: "blur(8px)",
    display: "none",
    pointerEvents: "none",
  } as CSSStyleDeclaration);
  document.body.appendChild(el);
  return el;
}

function render(runs: Run[]) {
  lastRuns = runs;
  const el = ensurePill();
  const active = activeRuns(runs);
  if (!active.length) {
    el.style.display = "none";
    window.dispatchEvent(new CustomEvent("signalforge:research-runs", { detail: [] }));
    return;
  }
  const first = active[0];
  const p = typeof first.completed_units === "number" && typeof first.total_units === "number"
    ? ` · ${first.completed_units}/${first.total_units}`
    : "";
  const m = typeof first.material_count === "number" ? ` · 資料 ${first.material_count}` : "";
  const more = active.length > 1 ? ` · 另 ${active.length - 1} 個方向` : "";
  el.textContent = `研究持續中${p}${m}${more} · 可自由切換畫面`;
  el.style.display = "block";
  window.dispatchEvent(new CustomEvent("signalforge:research-runs", { detail: active }));
}

function clearTimer() {
  if (timer !== undefined) {
    window.clearTimeout(timer);
    timer = undefined;
  }
}

function scheduleNext() {
  clearTimer();
  if (document.visibilityState !== "visible") return;
  const delay = activeRuns(lastRuns).length ? ACTIVE_POLL_MS : IDLE_POLL_MS;
  timer = window.setTimeout(() => void poll(), delay);
}

async function poll() {
  if (document.visibilityState !== "visible") return;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await fetch("/api/signalforge/research-backlog/runs?active_only=1", {
        method: "GET",
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      lastPollAt = Date.now();
      render(Array.isArray(data?.runs) ? data.runs : []);
    } catch {
      // Observability must never block or reset the workspace.
    } finally {
      inflight = null;
      scheduleNext();
    }
  })();
  return inflight;
}

function onVisibleAgain() {
  // Keep cached state on screen immediately. Do not clear detail or show a fresh loading state.
  render(lastRuns);
  const staleFor = Date.now() - lastPollAt;
  if (staleFor >= FOCUS_STALE_MS) void poll();
  else scheduleNext();
}

function start() {
  render(lastRuns);
  void poll();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") onVisibleAgain();
    else clearTimer();
  });
  window.addEventListener("online", () => {
    if (document.visibilityState === "visible" && Date.now() - lastPollAt >= FOCUS_STALE_MS) void poll();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}

export function getSignalForgeResearchRunsV253(): Run[] {
  return lastRuns.slice();
}
