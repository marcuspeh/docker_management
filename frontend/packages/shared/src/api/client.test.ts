import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request, toApiError } from "./client";

const respond = (body: unknown, init: ResponseInit = {}) =>
  new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });

/** Captures the ApiError a rejected request produced. */
async function failure(promise: Promise<unknown>): Promise<ApiError> {
  return promise.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (error: unknown) => error as ApiError,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("returns the parsed body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({ id: "abc" })));
    await expect(request("/api/scm/repos/abc")).resolves.toEqual({ id: "abc" });
  });

  it("unwraps the backend's error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(
          {
            error: {
              code: "REPO_UNREACHABLE",
              message: "Git could not reach the repository.",
              detail: { stderr: "fatal: repository not found" },
            },
          },
          { status: 400 },
        ),
      ),
    );

    const error = await failure(
      request("/api/scm/repos", { method: "POST", body: {} }),
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("REPO_UNREACHABLE");
    expect(error.message).toBe("Git could not reach the repository.");
    expect(error.detail.stderr).toBe("fatal: repository not found");
    expect(error.status).toBe(400);
  });

  it("turns a failed fetch into a NETWORK error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await failure(request("/api/health"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("NETWORK");
  });

  it("survives an error body that is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );

    const error = await failure(request("/api/health"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
  });

  it("returns undefined for 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api.delete("/api/networks/x")).resolves.toBeUndefined();
  });
});

describe("query building", () => {
  it("skips empty and null values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond([]));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/containers", {
      query: { all: true, network: "", repoId: null, q: "api" },
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/containers?all=true&q=api");
  });
});

describe("ApiError", () => {
  it("exposes a named field for validation errors", () => {
    expect(new ApiError("INVALID_PATH", "bad", { field: "path" }).field).toBe("path");
    expect(new ApiError("INVALID_PATH", "bad", {}).field).toBeUndefined();
  });
});

describe("toApiError", () => {
  it("passes an ApiError through untouched", () => {
    const original = new ApiError("NAME_TAKEN", "taken");
    expect(toApiError(original)).toBe(original);
  });

  it("wraps anything else", () => {
    expect(toApiError(new Error("boom")).message).toBe("boom");
    expect(toApiError("nope").message).toBe("Something went wrong.");
  });
});