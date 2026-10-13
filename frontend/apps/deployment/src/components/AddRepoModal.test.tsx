import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AddRepoModal } from "./AddRepoModal";

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AddRepoModal open onClose={() => {}} />
    </QueryClientProvider>,
  );
}

/** Answers the next POST with the backend's error envelope. */
function failWith(error: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(error), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

const fillAndSubmit = async () => {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Name"), "my-service");
  await user.type(screen.getByLabelText("Git URL"), "git@github.com:owner/my-service.git");
  await user.click(screen.getByRole("button", { name: "Add Repository" }));
};

describe("AddRepoModal", () => {
  it("puts Git's own output under the URL field when the repo is unreachable", async () => {
    failWith({
      error: {
        code: "REPO_UNREACHABLE",
        message: "Git could not reach the repository.",
        detail: { stderr: "fatal: repository not found" },
      },
    });
    renderModal();

    await fillAndSubmit();

    await waitFor(() => {
      expect(screen.getByText("fatal: repository not found")).toBeInTheDocument();
    });
    // The message belongs to the URL field, not the name field.
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid");
  });

  it("puts a taken name under the name field", async () => {
    failWith({
      error: {
        code: "NAME_TAKEN",
        message: "A repository named 'my-service' already exists.",
        detail: {},
      },
    });
    renderModal();

    await fillAndSubmit();

    await waitFor(() => {
      expect(
        screen.getByText("A repository named 'my-service' already exists."),
      ).toBeInTheDocument();
    });
  });

  it("puts an invalid path under the path field", async () => {
    failWith({
      error: {
        code: "INVALID_PATH",
        message: "Path must stay inside the repository.",
        detail: { field: "path" },
      },
    });
    renderModal();

    await fillAndSubmit();

    await waitFor(() => {
      expect(
        screen.getByText("Path must stay inside the repository."),
      ).toBeInTheDocument();
    });
  });

  it("sends the compose file and the path the user typed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "r1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderModal();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "svc");
    await user.type(screen.getByLabelText("Git URL"), "https://example.com/svc.git");
    // The field starts on the repo root, so replace it rather than append.
    const pathField = screen.getByLabelText("Compose file location");
    await user.clear(pathField);
    await user.type(pathField, "deploy");
    await user.click(screen.getByRole("button", { name: "Add Repository" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body).toMatchObject({
      name: "svc",
      url: "https://example.com/svc.git",
      path: "deploy",
      composeFile: "docker-compose.yml",
    });
  });
});