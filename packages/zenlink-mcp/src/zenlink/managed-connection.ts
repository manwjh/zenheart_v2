import { ZenlinkClient, type ZenlinkClientOptions, resolveZenlinkOptionsFromEnv } from "./client.js";
import { ZenlinkAuthError } from "./errors.js";
import type { AuthOkFrame } from "./types.js";

const DEFAULT_INITIAL_DELAY_MS = 1_000;
const DEFAULT_MAX_DELAY_MS = 30_000;
const DEFAULT_BACKOFF_MULTIPLIER = 2;

export type ZenlinkReconnectPolicy = {
  initialDelayMs: number;
  maxDelayMs: number;
  backoffMultiplier: number;
};

export type ZenlinkManagedConnectionOptions = ZenlinkClientOptions & {
  reconnect?: Partial<ZenlinkReconnectPolicy>;
  /** Invoked when long-lived mode stops after a permanent auth failure. */
  onAuthFailure?: (err: ZenlinkAuthError) => void;
};

function normalizePolicy(partial?: Partial<ZenlinkReconnectPolicy>): ZenlinkReconnectPolicy {
  return {
    initialDelayMs: partial?.initialDelayMs ?? DEFAULT_INITIAL_DELAY_MS,
    maxDelayMs: partial?.maxDelayMs ?? DEFAULT_MAX_DELAY_MS,
    backoffMultiplier: partial?.backoffMultiplier ?? DEFAULT_BACKOFF_MULTIPLIER,
  };
}

function computeDelayMs(attempt: number, policy: ZenlinkReconnectPolicy): number {
  const raw = policy.initialDelayMs * Math.pow(policy.backoffMultiplier, Math.max(0, attempt - 1));
  return Math.min(policy.maxDelayMs, Math.max(0, Math.round(raw)));
}

/**
 * Imperative connection control around {@link ZenlinkClient}:
 * one-shot {@link connect}, full {@link disconnect}, and {@link startLongLived} with reconnect backoff.
 *
 * - {@link connect} clears long-lived mode; a later drop does not auto-reconnect.
 * - {@link startLongLived} enables reconnect on close until {@link disconnect}.
 * - Auth failures ({@link ZenlinkAuthError}) end long-lived mode (bad credentials must be fixed first).
 */
export class ZenlinkManagedConnection {
  readonly client: ZenlinkClient;
  private readonly policy: ZenlinkReconnectPolicy;
  private readonly onAuthFailure?: (err: ZenlinkAuthError) => void;

  private longLivedMode = false;
  private userDisconnected = true;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private longLivedConnectInFlight = false;

  constructor(options: ZenlinkManagedConnectionOptions) {
    const { reconnect, onAuthFailure, ...clientOpts } = options;
    this.policy = normalizePolicy(reconnect);
    this.onAuthFailure = onAuthFailure;

    const userOnClose = clientOpts.onClose;
    this.client = new ZenlinkClient({
      ...clientOpts,
      onClose: (code, reason) => {
        userOnClose?.(code, reason);
        this.onSocketClosed();
      },
    });
  }

  /** True while long-lived reconnect is enabled (until {@link disconnect}). */
  isLongLivedEnabled(): boolean {
    return this.longLivedMode && !this.userDisconnected;
  }

  /**
   * Wait until the socket is open and authenticated.
   * When not in long-lived mode, performs one {@link ZenlinkClient.connect}.
   * When long-lived mode is on, ensures a connect attempt is scheduled (see {@link startLongLived}) and polls until open or timeout.
   */
  async awaitOnline(timeoutMs: number): Promise<void> {
    if (this.client.isConnected()) {
      return;
    }
    if (!this.longLivedMode) {
      await this.client.connect();
      return;
    }
    this.startLongLived();
    const deadline = Date.now() + timeoutMs;
    while (!this.client.isConnected()) {
      if (Date.now() > deadline) {
        throw new Error(
          `ZenlinkManagedConnection: timeout waiting for connection (${timeoutMs}ms)`,
        );
      }
      if (this.userDisconnected || !this.longLivedMode) {
        throw new Error("ZenlinkManagedConnection: connection wait aborted");
      }
      await new Promise<void>((r) => setTimeout(r, 50));
    }
  }

  /**
   * Single connection attempt with auth. Disables long-lived reconnect on success; closes any prior socket.
   */
  connect(): Promise<AuthOkFrame> {
    this.longLivedMode = false;
    this.userDisconnected = false;
    this.clearReconnectState();
    return this.client.connect();
  }

  /** Close the socket, cancel scheduled reconnects, and disable long-lived mode. */
  disconnect(): void {
    this.longLivedMode = false;
    this.userDisconnected = true;
    this.clearReconnectState();
    this.longLivedConnectInFlight = false;
    this.client.close();
  }

  /**
   * Keep the session online: connect if needed, and after any close reconnect with exponential backoff
   * until {@link disconnect}. Idempotent if already long-lived and connected.
   */
  startLongLived(): void {
    this.userDisconnected = false;
    this.longLivedMode = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.client.isConnected()) {
      this.reconnectAttempt = 0;
      return;
    }
    this.connectOnceWithLongLivedRecovery();
  }

  private clearReconnectState(): void {
    this.reconnectAttempt = 0;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private onSocketClosed(): void {
    if (this.userDisconnected || !this.longLivedMode) {
      return;
    }
    const delayMs = computeDelayMs(++this.reconnectAttempt, this.policy);
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connectOnceWithLongLivedRecovery();
    }, delayMs);
  }

  private connectOnceWithLongLivedRecovery(): void {
    if (this.userDisconnected || !this.longLivedMode) {
      return;
    }
    if (this.client.isConnected()) {
      this.reconnectAttempt = 0;
      return;
    }
    if (this.longLivedConnectInFlight) {
      return;
    }
    this.longLivedConnectInFlight = true;
    void this.client
      .connect()
      .then(() => {
        this.longLivedConnectInFlight = false;
        this.reconnectAttempt = 0;
      })
      .catch((err: unknown) => {
        this.longLivedConnectInFlight = false;
        if (this.userDisconnected || !this.longLivedMode) {
          return;
        }
        if (err instanceof ZenlinkAuthError) {
          this.longLivedMode = false;
          this.onAuthFailure?.(err);
          return;
        }
        this.onSocketClosed();
      });
  }
}

export function createZenlinkManagedFromEnv(
  overrides?: Partial<ZenlinkManagedConnectionOptions>,
): ZenlinkManagedConnection {
  const { reconnect, onAuthFailure, ...rest } = overrides ?? {};
  return new ZenlinkManagedConnection({
    ...resolveZenlinkOptionsFromEnv(rest),
    reconnect,
    onAuthFailure,
  });
}
