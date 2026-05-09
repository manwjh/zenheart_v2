export class ZenlinkAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZenlinkAuthError";
  }
}
