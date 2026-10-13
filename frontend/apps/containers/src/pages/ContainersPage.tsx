import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Box, Search, X } from "lucide-react";
import {
  ContainersHeader,
  EmptyState,
  ErrorBanner,
  Skeleton,
  toApiError,
  type Network,
} from "@portal/shared";
import { useContainers, useNetworks } from "../queries";
import { ContainerCard } from "../components/ContainerCard";
import { ConnectContainersModal } from "../components/ConnectContainersModal";
import { CreateNetworkModal } from "../components/CreateNetworkModal";
import { DeleteNetworkModal } from "../components/DeleteNetworkModal";
import { NetworkSidebar } from "../components/NetworkSidebar";

/**
 * The single page at `/containers/`.
 *
 * Filters, the search box, the open log panel and which modal is showing all
 * live in the query string, so a view can be linked to and survives a reload.
 */
export function ContainersPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const network = searchParams.get("network");
  const repoId = searchParams.get("repoId");
  const expandedLogId = searchParams.get("expandedLogId");
  const modal = searchParams.get("modal");
  const targetNetworkName = searchParams.get("targetNetwork");

  const [search, setSearch] = useState("");

  const { data: networks, isPending: networksPending } = useNetworks();
  const filters = useMemo(() => ({ network: network ?? undefined, repoId: repoId ?? undefined }), [network, repoId]);
  const { data: containers, isPending, isError, error, refetch, isFetching } =
    useContainers(filters);

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next, { replace: true });
  };

  const openModal = (name: string, target?: string) =>
    update({ modal: name, targetNetwork: target ?? null });

  const closeModal = () => update({ modal: null, targetNetwork: null });

  const targetNetwork: Network | null =
    networks?.find((n) => n.name === targetNetworkName) ?? null;

  // The list is already filtered server-side by network and repo; the search box
  // narrows what came back, so it costs no extra request.
  const visible = useMemo(() => {
    if (!containers) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return containers;
    return containers.filter(
      (c) =>
        c.name.toLowerCase().includes(needle) ||
        c.id.toLowerCase().includes(needle) ||
        c.image.toLowerCase().includes(needle),
    );
  }, [containers, search]);

  const refreshHint = isFetching && !isPending;

  return (
    <div className="min-h-screen">
      <ContainersHeader />

      <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:flex-row">
        <NetworkSidebar
          networks={networks}
          isPending={networksPending}
          selected={network}
          onSelect={(name) => update({ network: name })}
          onCreate={() => openModal("create-network")}
          onConnect={(target) => openModal("connect", target.name)}
          onDelete={(target) => openModal("delete-network", target.name)}
        />

        <section className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400"
                aria-hidden
              />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by name, ID or image"
                aria-label="Search containers"
                className="h-9 w-full rounded-md border border-slate-300 bg-white pl-9 pr-3 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>
            {refreshHint && <span className="text-xs text-slate-400">Refreshing...</span>}
          </div>

          {repoId && (
            <button
              type="button"
              onClick={() => update({ repoId: null })}
              className="inline-flex w-fit items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-600/20 transition-colors hover:bg-blue-100"
            >
              Filtered by repository
              <span className="font-mono">{repoId.slice(0, 8)}</span>
              <X className="size-3" aria-hidden />
            </button>
          )}

          {isError && (
            <ErrorBanner
              title="Could not load containers"
              message={toApiError(error).message}
              onRetry={() => refetch()}
            />
          )}

          {isPending ? (
            <div className="flex flex-col gap-3">
              {[0, 1, 2].map((n) => (
                <Skeleton key={n} className="h-32" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={<Box className="size-8" aria-hidden />}
              title="No containers"
              description={
                search
                  ? "Nothing matches that search."
                  : "Deploy a repository from the Deployment app, or clear the filters."
              }
            />
          ) : (
            <div className="flex flex-col gap-3">
              {visible.map((container) => (
                <ContainerCard
                  key={container.id}
                  container={container}
                  logsOpen={expandedLogId === container.id}
                  onToggleLogs={() =>
                    update({
                      expandedLogId: expandedLogId === container.id ? null : container.id,
                    })
                  }
                />
              ))}
            </div>
          )}
        </section>
      </main>

      <CreateNetworkModal open={modal === "create-network"} onClose={closeModal} />
      <ConnectContainersModal
        network={modal === "connect" ? targetNetwork : null}
        containers={containers}
        onClose={closeModal}
      />
      <DeleteNetworkModal
        network={modal === "delete-network" ? targetNetwork : null}
        onClose={closeModal}
      />
    </div>
  );
}