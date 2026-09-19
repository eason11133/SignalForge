// SIGNALFORGE_FOUNDER_USABILITY_EVIDENCE_PRECISION_CLOSURE_V1
// Authoritative runtime observer for long Published refreshes.
// It does not change research truth; it only reconciles UI lifecycle with /status.running.

type SFStatus = {
  running?: boolean;
  last_finished_at?: string | null;
  last_error?: string | null;
  last_cycle?: { phase_seconds?: Record<string, number> };
  progress?: {
    phase?: string | null;
    detail?: string | null;
    last_heartbeat_at?: string | null;
    heartbeat_state?: string | null;
    heartbeat_source?: string | null;
    progress_state?: string | null;
    progress_age_seconds?: number | null;
    cycle_elapsed_seconds?: number | null;
    progress?: Record<string, unknown> & { current?: number; total?: number; unit?: string; percent?: number };
  };
  dispatch?: {
    status?: string | null;
    pid?: number | null;
    worker_alive?: boolean;
    age_seconds?: number | null;
    reason?: string | null;
    persisted_status?: string | null;
    effective_status_reason?: string | null;
  };
};

let sawRunning = false;
let startedAt: number | null = null;
let banner: HTMLDivElement | null = null;

function ensureBanner(): HTMLDivElement {
  if (banner && document.body.contains(banner)) return banner;
  banner = document.createElement("div");
  banner.id = "signalforge-founder-runtime-banner";
  Object.assign(banner.style, {
    position: "fixed",
    right: "16px",
    bottom: "16px",
    zIndex: "2147483647",
    padding: "10px 12px",
    borderRadius: "10px",
    background: "rgba(15,23,42,.94)",
    color: "white",
    fontSize: "12px",
    lineHeight: "1.4",
    boxShadow: "0 8px 30px rgba(0,0,0,.25)",
    maxWidth: "360px",
    display: "none",
  });
  document.body.appendChild(banner);
  return banner;
}

function fmt(sec: number) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${String(s).padStart(2,"0")}s`;
}

async function pollSignalForgeStatus() {
  try {
    const r = await fetch("/api/signalforge/status", { cache: "no-store" });
    if (!r.ok) return;
    const s = (await r.json()) as SFStatus;
    const b = ensureBanner();

    const dispatchStatus = String(s.dispatch?.status || "");
    const dispatchActive = Boolean(s.dispatch?.worker_alive) || ["LAUNCHING", "DISPATCHED", "WORKER_STARTED"].includes(dispatchStatus);

    if (s.running || dispatchActive) {
      if (!sawRunning) {
        sawRunning = true;
        startedAt = Date.now();
      }
      const localElapsed = startedAt ? (Date.now() - startedAt) / 1000 : 0;
      const elapsed = Number(s.progress?.cycle_elapsed_seconds ?? localElapsed);
      b.style.display = "block";
      const phase = s.progress?.phase || (dispatchActive ? `dispatch ${dispatchStatus.toLowerCase()}` : "working");
      const detail = s.progress?.detail ? ` · ${s.progress.detail}` : "";
      const heartbeat = s.progress?.heartbeat_state === "QUIET_OR_STALE" && s.running ? " · worker heartbeat quiet" : "";
      const noProgress = s.progress?.progress_state === "PROCESS_ALIVE_NO_RECENT_PROGRESS"
        ? ` · worker alive, no semantic progress ${Math.round(Number(s.progress?.progress_age_seconds || 0))}s`
        : "";
      const cp = s.progress?.progress;
      const bounded = Number.isFinite(Number(cp?.total)) && Number(cp?.total) > 0
        ? ` · ${Number(cp?.current || 0)}/${Number(cp?.total)} ${String(cp?.unit || "items")}`
        : "";
      b.textContent = `SignalForge · ${phase}${detail}${bounded}${heartbeat}${noProgress} · ${fmt(elapsed)} elapsed`;
      document.title = `${phase} · ${fmt(elapsed)} · SignalForge`;
      return;
    }

    if (sawRunning && !s.running) {
      b.style.display = "block";
      b.textContent = s.last_error
        ? `SignalForge refresh finished with error: ${s.last_error}`
        : "SignalForge refresh finished · synchronizing Founder UI";
      sawRunning = false;
      startedAt = null;
      document.title = "SignalForge";
      // Existing websocket/local state may be stale. One authoritative reload closes it.
      setTimeout(() => window.location.reload(), 900);
      return;
    }

    if (!s.running) {
      b.style.display = "none";
    }
  } catch {
    // Observer failure must never block product usage.
  }
}

if (typeof window !== "undefined") {
  window.setInterval(pollSignalForgeStatus, 5000);
  window.setTimeout(pollSignalForgeStatus, 700);
}
