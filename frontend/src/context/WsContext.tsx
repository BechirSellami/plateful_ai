import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { WsIncoming, WsOutgoing } from "../types/ws";

interface WsState {
  connected: boolean;
  send: (msg: WsOutgoing) => void;
  subscribe: (cb: (msg: WsIncoming) => void) => () => void;
}

const WsContext = createContext<WsState | null>(null);

export function WsProvider({ children }: { children: ReactNode }) {
  const wsRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Set<(msg: WsIncoming) => void>>(new Set());
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as WsIncoming;
      listenersRef.current.forEach((cb) => cb(data));
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  const send = useCallback((msg: WsOutgoing) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const subscribe = useCallback((cb: (msg: WsIncoming) => void) => {
    listenersRef.current.add(cb);
    return () => {
      listenersRef.current.delete(cb);
    };
  }, []);

  return (
    <WsContext.Provider value={{ connected, send, subscribe }}>
      {children}
    </WsContext.Provider>
  );
}

export function useWs(): WsState {
  const ctx = useContext(WsContext);
  if (!ctx) throw new Error("useWs must be inside WsProvider");
  return ctx;
}
