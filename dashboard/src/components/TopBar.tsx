import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Search } from "lucide-react";
import { useHealth } from "../api/hooks";
import {
  getWebSocketConnectedSnapshot,
  SIGNALFORGE_WS_STATUS_EVENT,
} from "../hooks/useWebSocket";

type LiveConnectionState = boolean | null;

export default function TopBar() {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const { data: health, isLoading: healthLoading, isError: healthError } = useHealth();
  const [liveConnected, setLiveConnected] = useState<LiveConnectionState>(() => getWebSocketConnectedSnapshot());

  useEffect(() => {
    setLiveConnected(getWebSocketConnectedSnapshot());
    const onStatus = (event: Event) => {
      const detail = (event as CustomEvent<{ connected?: boolean }>).detail;
      if (typeof detail?.connected === "boolean") setLiveConnected(detail.connected);
    };
    window.addEventListener(SIGNALFORGE_WS_STATUS_EVENT, onStatus);
    return () => window.removeEventListener(SIGNALFORGE_WS_STATUS_EVENT, onStatus);
  }, []);

  const apiHealthy = health?.status === "ok";
  const backendReachable = apiHealthy || liveConnected === true;

  let statusLabel = "連線檢查中";
  let statusClass = "text-text-tertiary";
  let dotClass = "bg-text-tertiary";
  let activityClass = "text-text-tertiary";

  if (apiHealthy && liveConnected === true) {
    statusLabel = "API 已連線 · 即時更新已連線";
    statusClass = "text-text-secondary";
    dotClass = "bg-success";
    activityClass = "text-success";
  } else if (apiHealthy && liveConnected !== true) {
    statusLabel = "API 已連線 · 即時更新重連中";
    statusClass = "text-warning";
    dotClass = "bg-warning";
    activityClass = "text-warning";
  } else if (liveConnected === true) {
    statusLabel = "即時更新已連線 · API health 待確認";
    statusClass = "text-warning";
    dotClass = "bg-warning";
    activityClass = "text-warning";
  } else if (!healthLoading && (healthError || liveConnected === false)) {
    statusLabel = "後端未連線";
    statusClass = "text-danger";
    dotClass = "bg-danger";
    activityClass = "text-danger";
  }

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length >= 2) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`);
    }
  }

  const title = [
    `API health: ${apiHealthy ? "OK" : healthLoading ? "checking" : "not confirmed"}`,
    `Realtime WebSocket: ${liveConnected === true ? "connected" : liveConnected === false ? "disconnected" : "checking"}`,
    backendReachable ? "SignalForge backend is reachable." : "SignalForge backend is not currently confirmed reachable.",
  ].join(" | ");

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border-secondary bg-bg-primary/95 px-6 backdrop-blur">
      <form onSubmit={handleSearch} className="flex w-full max-w-lg items-center gap-2">
        <Search className="h-4 w-4 shrink-0 text-text-tertiary" />
        <input
          type="search"
          aria-label="搜尋 SignalForge"
          placeholder="搜尋商機、Buyer、技術或證據…"
          value={query}
          onChange={(event: ChangeEvent<HTMLInputElement>) => setQuery(event.target.value)}
          className="w-full rounded-xl border border-border-secondary bg-bg-secondary/55 px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-2 focus:ring-info/25"
        />
      </form>

      <div className="ml-4 flex shrink-0 items-center gap-2 text-[11px]" title={title}>
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        <Activity className={`h-3.5 w-3.5 ${activityClass}`} />
        <span className={statusClass}>{statusLabel}</span>
      </div>
    </header>
  );
}
