export type StreamStatus = "connecting" | "live" | "reconnecting" | "failed";

type EventSourceOptions = {
  path: string;
  /** Initial backoff delay before the first reconnect (ms). Grows exponentially until `reconnectMaxMs`. */
  reconnectMs: number;
  /** Upper bound for backoff delay (default 30_000). */
  reconnectMaxMs?: number;
  /** Stop reconnecting after this many failed cycles without a successful `onopen` (default 25). */
  reconnectMaxAttempts?: number;
  onMessage: (raw: string) => void;
  onStatusChange?: (status: StreamStatus) => void;
  onError?: () => void;
  /** Called once when `reconnectMaxAttempts` is reached; stream stays stopped until `connect()` runs again. */
  onReconnectExhausted?: () => void;
};

export function createEventSourceStream(options: EventSourceOptions): {
  connect: () => void;
  stop: () => void;
} {
  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  let reconnectAttempts = 0;

  const maxDelayMs = options.reconnectMaxMs ?? 30_000;
  const maxAttempts = options.reconnectMaxAttempts ?? 25;
  const initialDelayMs = options.reconnectMs;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const stop = () => {
    stopped = true;
    clearReconnectTimer();
    reconnectAttempts = 0;
    eventSource?.close();
    eventSource = null;
  };

  const openStream = () => {
    if (stopped) return;
    clearReconnectTimer();
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    options.onStatusChange?.("connecting");
    const es = new EventSource(options.path);
    eventSource = es;

    es.onopen = () => {
      if (eventSource !== es || stopped) return;
      reconnectAttempts = 0;
      options.onStatusChange?.("live");
    };

    es.onmessage = (ev: MessageEvent) => {
      if (eventSource !== es) return;
      options.onMessage(ev.data);
    };

    es.onerror = () => {
      if (eventSource !== es) return;
      es.close();
      if (eventSource === es) {
        eventSource = null;
      }
      if (stopped) return;

      options.onError?.();

      if (reconnectAttempts >= maxAttempts) {
        options.onStatusChange?.("failed");
        options.onReconnectExhausted?.();
        return;
      }

      reconnectAttempts += 1;
      options.onStatusChange?.("reconnecting");
      const delayMs = Math.min(
        maxDelayMs,
        initialDelayMs * 2 ** (reconnectAttempts - 1),
      );
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        if (stopped) return;
        openStream();
      }, delayMs);
    };
  };

  const connect = () => {
    stopped = false;
    reconnectAttempts = 0;
    clearReconnectTimer();
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    openStream();
  };

  return { connect, stop };
}
