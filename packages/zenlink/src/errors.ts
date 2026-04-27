import type { AuthFailFrame } from "./types.js";

export class ZenlinkAuthError extends Error {
  readonly name = "ZenlinkAuthError";
  constructor(
    public readonly reason: string,
    public readonly raw?: AuthFailFrame
  ) {
    super(`Zenlink auth failed: ${reason}`);
  }
}
