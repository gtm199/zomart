import { useEffect, useRef } from "react";
import { WS_BASE, getToken } from "../services/api";

/** Keeps a live connection to the server for one order and calls onMessage for every push (rider moved, order changed).
 *  It reconnects by itself. onDown(true) tells the screen to fall back to checking now and then. */
export function useTrackSocket(orderId: string, onMessage: (m: any) => void, onDown: (down: boolean) => void) {
  const handler = useRef(onMessage);
  const down = useRef(onDown);
  handler.current = onMessage;
  down.current = onDown;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const token = getToken();
      if (!token) return;
      ws = new WebSocket(`${WS_BASE}/ws/track/${orderId}/`);
      ws.onopen = () => { ws?.send(JSON.stringify({ type: "auth", token })); };   // the token travels inside the connection
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(String(e.data));
          if (m.type === "ready") { retry = 0; down.current(false); }
          handler.current(m);
        } catch { /* ignore a broken message */ }
      };
      ws.onclose = () => {
        down.current(true);
        if (!closed) timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
      };
      ws.onerror = () => { ws?.close(); };
    };

    connect();
    const ping = setInterval(() => { if (ws?.readyState === 1) ws.send(JSON.stringify({ type: "ping" })); }, 25000);
    return () => { closed = true; if (timer) clearTimeout(timer); clearInterval(ping); ws?.close(); };
  }, [orderId]);
}