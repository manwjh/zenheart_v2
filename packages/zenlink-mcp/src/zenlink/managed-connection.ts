import { createZenlinkFromEnv, ZenlinkClient } from "./client.js";

export interface ZenlinkReconnectPolicy {
  initialDelayMs: number;
  maxDelayMs: number;
}

export interface ZenlinkManagedConnectionOptions {
  client?: ZenlinkClient;
  reconnectPolicy?: ZenlinkReconnectPolicy;
}

export class ZenlinkManagedConnection {
  readonly client: ZenlinkClient;
  private readonly reconnectPolicy: ZenlinkReconnectPolicy;
  private stopped = false;

  constructor(options: ZenlinkManagedConnectionOptions = {}) {
    this.client = options.client ?? createZenlinkFromEnv();
    this.reconnectPolicy = options.reconnectPolicy ?? {
      initialDelayMs: 1_000,
      maxDelayMs: 30_000,
    };
  }

  async start(): Promise<void> {
    this.stopped = false;
    await this.client.connect();
  }

  stop(): void {
    this.stopped = true;
    this.client.disconnect();
  }

  async reconnectLoop(): Promise<void> {
    let delay = this.reconnectPolicy.initialDelayMs;
    while (!this.stopped && !this.client.isOnline()) {
      try {
        await this.client.connect();
        return;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(this.reconnectPolicy.maxDelayMs, delay * 2);
      }
    }
  }
}

export function createZenlinkManagedFromEnv(): ZenlinkManagedConnection {
  return new ZenlinkManagedConnection({ client: createZenlinkFromEnv() });
}
