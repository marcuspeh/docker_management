import { apiUrl } from "../config";

/**
 * One error shape for everything the API returns: `{ error: { code, message,
 * detail } }`. Modals switch on `code` to place a message under the right
 * field.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly detail: Record<string, unknown>;
  readonly status: number;

  constructor(
    code: string,
    message: string,
    detail: Record<string, unknown> = {},
    status = 0,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
    this.status = status;
  }

  /** The field a validation error belongs under, when the backend named one. */
  get field(): string | undefined {
    const value = this.detail.field;
    return typeof value === "string" ? value : undefined;
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
};

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const url = apiUrl(path);
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function readError(response: Response): Promise<ApiError> {
  let code = "UNKNOWN";
  let message = response.statusText || "Request failed";
  let detail: Record<string, unknown> = {};
  try {
    const body = await response.json();
    const envelope = (body as { error?: { code?: string; message?: string; detail?: unknown } })
      .error;
    if (envelope) {
      code = envelope.code ?? code;
      message = envelope.message ?? message;
      detail =
        envelope.detail && typeof envelope.detail === "object"
          ? (envelope.detail as Record<string, unknown>)
          : {};
    }
  } catch {
    // A non-JSON error body: keep the status-based message.
  }
  return new ApiError(code, message, detail, response.status);
}

/** Performs one request and parses the response, turning failures into ApiError. */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, signal, query } = options;
  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    // A failed fetch means the request never reached the API.
    if (signal?.aborted) throw cause;
    throw new ApiError("NETWORK", "Could not reach the portal API.");
  }

  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};

/** Normalises anything thrown by the API layer into an ApiError. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof Error) return new ApiError("UNKNOWN", error.message);
  return new ApiError("UNKNOWN", "Something went wrong.");
}