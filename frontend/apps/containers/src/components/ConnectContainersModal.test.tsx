import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Container, Network } from "@portal/shared";
import { ConnectContainersModal } from "./ConnectContainersModal";

const network: Network = {
  id: "net-1",
  name: "frontend",
  driver: "bridge",
  scope: "local",
  subnet: "172.18.0.0/16",
  internal: false,
  builtin: false,
  composeManaged: false,
  containerCount: 1,
};

const container = (id: string, name: string, networks: string[]): Container => ({
  id,
  fullId: `${id}0000000000`,
  name,
  image: `${name}:1.0`,
  state: "running",
  status: "Up 2 hours",
  exitCode: null,
  ports: [],
  networks,
  createdAt: "2026-01-01T00:00:00Z",
  startedAt: "2026-01-01T00:00:00Z",
  finishedAt: null,
  repoId: null,
  service: null,
});

// Docker short IDs are 12 characters.
const containers = [
  container("aaaaaaaaaaa1", "api", []),
  container("bbbbbbbbbbb2", "worker", []),
  // Already on the network, so there is nothing to connect.
  container("ccccccccccc3", "web", ["frontend"]),
];

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConnectContainersModal network={network} containers={containers} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("ConnectContainersModal", () => {
  it("only offers containers that are not already on the network", () => {
    renderModal();

    expect(screen.getByLabelText("api")).toBeInTheDocument();
    expect(screen.getByLabelText("worker")).toBeInTheDocument();
    expect(screen.queryByLabelText("web")).not.toBeInTheDocument();
  });

  it("sends only the checked containers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ connected: ["aaaaaaaaaaa1"], failed: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderModal();

    const user = userEvent.setup();
    await user.click(screen.getByLabelText("api"));
    await user.click(screen.getByRole("button", { name: /^Connect/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toContain("/api/networks/net-1/connect");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      containerIds: ["aaaaaaaaaaa1"],
    });
  });

  it("lists each container the API could not connect", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            connected: ["aaaaaaaaaaa1"],
            failed: [{ containerId: "bbbbbbbbbbb2", error: "already connected" }],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderModal();

    const user = userEvent.setup();
    await user.click(screen.getByLabelText("api"));
    await user.click(screen.getByLabelText("worker"));
    await user.click(screen.getByRole("button", { name: /^Connect/ }));

    // A partial success stays on screen so the failures can be read.
    const failures = await screen.findByRole("list", { name: "Failed connections" });
    expect(within(failures).getByText("bbbbbbbbbbb2")).toBeInTheDocument();
    expect(within(failures).getByText(/already connected/)).toBeInTheDocument();
  });
});