export type JsonObject = Record<string, unknown>;

export async function readJsonObject(res: Response): Promise<JsonObject> {
  const payload = await res.json().catch(() => ({}));
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return {};
  }
  return payload as JsonObject;
}

export async function fetchJsonObject(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<{ response: Response; data: JsonObject }> {
  const response = await fetch(input, init);
  const data = await readJsonObject(response);
  return { response, data };
}
