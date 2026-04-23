const BASE_URL = "/api";

export class ApiError extends Error {
  status: number;
  statusText: string;
  detail: unknown;

  constructor(response: Response, detail: unknown) {
    super(errorMessage(response, detail));
    this.name = "ApiError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.detail = detail;
  }
}

export async function fetchJson<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", headers.get("Accept") ?? "application/json");
  if (options.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!resp.ok) {
    throw new ApiError(resp, await parseBody(resp));
  }

  if (resp.status === 204 || resp.status === 205) {
    return undefined as T;
  }

  const text = await resp.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

export async function fetchOptionalJson<T>(
  path: string,
  options: RequestInit = {},
  optionalStatuses: number[] = [404]
): Promise<T | null> {
  try {
    return await fetchJson<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && optionalStatuses.includes(error.status)) {
      return null;
    }
    throw error;
  }
}

async function parseBody(resp: Response): Promise<unknown> {
  const text = await resp.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorMessage(resp: Response, body: unknown): string {
  const detail = extractDetail(body);
  return detail || `API error: ${resp.status} ${resp.statusText}`;
}

function extractDetail(body: unknown): string {
  if (body == null) return "";
  if (typeof body === "string") return body;
  if (typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail != null) return JSON.stringify(detail);
  }
  return "";
}
