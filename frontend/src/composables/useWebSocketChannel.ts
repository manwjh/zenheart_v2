export type WebSocketReconnectInfo = {
  attempt: number;
  delayMs: number;
};

export type WebSocketReconnectConfig = {
  initialDelayMs: number;
  maxDelayMs: number;
  /**
   * Max reconnect attempts after an abnormal close before giving up.
   * Each successful `onopen` resets the counter.
   */
  maxAttempts?: number;
  shouldReconnect?: (event: CloseEvent) => boolean;
  onScheduled?: (info: WebSocketReconnectInfo) => void;
  onExhausted?: () => void;
};

type WebSocketChannelOptions = {
  url: string;
  reconnect?: WebSocketReconnectConfig;
  onOpen?: (ws: WebSocket) => void;
  onMessage?: (raw: string) => void;
  onError?: () => void;
  onClose?: (event: CloseEvent) => void;
};

export function createWebSocketChannel(options: WebSocketChannelOptions): {
  connect: () => WebSocket;
  disconnect: () => void;
  current: () => WebSocket | null;
} {
  let ws: WebSocket | null = null;
  let stopped = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempts = 0;

  const maxReconnectAttempts = options.reconnect?.maxAttempts ?? 20;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = (ev: CloseEvent) => {
    const cfg = options.reconnect;
    if (!cfg || stopped) return;
    if (cfg.shouldReconnect && !cfg.shouldReconnect(ev)) return;
    if (reconnectAttempts >= maxReconnectAttempts) {
      cfg.onExhausted?.();
      return;
    }
    reconnectAttempts += 1;
    const exp = cfg.initialDelayMs * 2 ** (reconnectAttempts - 1);
    const delayMs = Math.min(cfg.maxDelayMs, exp);
    cfg.onScheduled?.({ attempt: reconnectAttempts, delayMs });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (stopped) return;
      openSocket();
    }, delayMs);
  };

  const openSocket = () => {
    if (stopped) return;
    clearReconnectTimer();
    if (ws) {
      try {
        ws.close();
      } catch {
        // Ignore transport close errors.
      }
      ws = null;
    }
    const socket = new WebSocket(options.url);
    ws = socket;
    socket.onopen = () => {
      if (ws !== socket) return;
      reconnectAttempts = 0;
      options.onOpen?.(socket);
    };
    socket.onmessage = (ev) => {
      if (ws !== socket) return;
      options.onMessage?.(ev.data as string);
    };
    socket.onerror = () => {
      if (ws !== socket) return;
      options.onError?.();
    };
    socket.onclose = (ev) => {
      if (ws !== socket) return;
      ws = null;
      options.onClose?.(ev);
      if (!stopped) {
        scheduleReconnect(ev);
      }
    };
  };

  const disconnect = () => {
    stopped = true;
    clearReconnectTimer();
    reconnectAttempts = 0;
    if (!ws) return;
    const s = ws;
    try {
      if (s.readyState === WebSocket.CLOSED) {
        ws = null;
        return;
      }
      s.close();
    } catch {
      ws = null;
    }
    // Leave `ws` set until `onclose` so handlers see a consistent current socket.
  };

  const connect = () => {
    stopped = false;
    reconnectAttempts = 0;
    clearReconnectTimer();
    openSocket();
    return ws as WebSocket;
  };

  return {
    connect,
    disconnect,
    current: () => ws,
  };
}
