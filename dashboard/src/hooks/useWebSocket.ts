import { useEffect, useRef, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export const SIGNALFORGE_WS_STATUS_EVENT = "signalforge:ws-status";

function defaultWsUrl() {
  if (typeof window === "undefined") return "ws://localhost:8000/api/ws/dashboard";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.hostname || "localhost";
  return `${protocol}//${host}:8000/api/ws/dashboard`;
}

const WS_URL = import.meta.env.VITE_WS_URL || defaultWsUrl();

function publishConnectionStatus(connected: boolean) {
  if (typeof window === "undefined") return;
  (window as typeof window & { __signalforgeWsConnected?: boolean }).__signalforgeWsConnected = connected;
  window.dispatchEvent(
    new CustomEvent(SIGNALFORGE_WS_STATUS_EVENT, {
      detail: { connected },
    }),
  );
}

export function getWebSocketConnectedSnapshot(): boolean | null {
  if (typeof window === "undefined") return null;
  const value = (window as typeof window & { __signalforgeWsConnected?: boolean }).__signalforgeWsConnected;
  return typeof value === "boolean" ? value : null;
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const stoppedRef = useRef(false);
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    if (stoppedRef.current) return;
    try {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        if (stoppedRef.current) {
          ws.close();
          return;
        }
        setConnected(true);
        publishConnectionStatus(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "heartbeat") return;

          if (data.type === "new_post" || data.type === "post_update") {
            queryClient.invalidateQueries({ queryKey: ["overview"] });
            queryClient.invalidateQueries({ queryKey: ["pulse"] });
            queryClient.invalidateQueries({ queryKey: ["topics"] });
          } else if (data.type === "new_topic" || data.type === "topic_update") {
            queryClient.invalidateQueries({ queryKey: ["overview"] });
            queryClient.invalidateQueries({ queryKey: ["pulse"] });
            queryClient.invalidateQueries({ queryKey: ["debates"] });
            queryClient.invalidateQueries({ queryKey: ["topics"] });
          } else if (data.type === "new_news") {
            queryClient.invalidateQueries({ queryKey: ["overview"] });
            queryClient.invalidateQueries({ queryKey: ["news"] });
          } else if (data.type === "scraper_complete") {
            queryClient.invalidateQueries({ queryKey: ["overview"] });
            queryClient.invalidateQueries({ queryKey: ["health"] });
          }
        } catch {
          // Ignore parse errors from non-JSON/partial messages.
        }
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (stoppedRef.current) return;
        setConnected(false);
        publishConnectionStatus(false);
        reconnectTimeout.current = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      if (stoppedRef.current) return;
      setConnected(false);
      publishConnectionStatus(false);
      reconnectTimeout.current = setTimeout(connect, 5000);
    }
  }, [queryClient]);

  useEffect(() => {
    stoppedRef.current = false;
    connect();
    return () => {
      stoppedRef.current = true;
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
      }
    };
  }, [connect]);

  return { connected };
}
