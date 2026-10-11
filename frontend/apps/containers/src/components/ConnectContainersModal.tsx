import { useMemo, useState } from "react";
import { Button, ErrorBanner, Modal, toApiError, type Container, type Network } from "@portal/shared";
import { useConnectContainers } from "../queries";

export type ConnectContainersModalProps = {
  network: Network | null;
  containers: Container[] | undefined;
  onClose: () => void;
};

/**
 * Connects several containers to a network at once. The API answers per
 * container, so a partial success lists each failure instead of reporting the
 * whole request as failed.
 */
export function ConnectContainersModal({
  network,
  containers,
  onClose,
}: ConnectContainersModalProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const connect = useConnectContainers(network?.id ?? "");

  // A container already on the network has nothing to connect.
  const candidates = useMemo(
    () =>
      network
        ? (containers ?? []).filter((c) => !c.networks.includes(network.name))
        : [],
    [containers, network],
  );

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  };

  const submit = () => {
    if (!network) return;
    connect.mutate(
      { containerIds: selected },
      {
        // Only a clean run closes: a partial failure has to be read first.
        onSuccess: (result) => {
          if (result.failed.length === 0) {
            setSelected([]);
            onClose();
          }
        },
      },
    );
  };

  return (
    <Modal
      open={Boolean(network)}
      title={`Connect containers to ${network?.name ?? ""}`}
      description="Select the containers to attach to this network."
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={connect.isPending}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            loading={connect.isPending}
            disabled={selected.length === 0}
          >
            Connect {selected.length > 0 ? `(${selected.length})` : ""}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {candidates.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 py-6 text-center text-xs text-slate-500">
            No containers available to connect.
          </p>
        ) : (
          <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
            {candidates.map((container) => (
              <li key={container.id}>
                <label className="flex cursor-pointer items-center gap-2.5 rounded-md border border-slate-200 px-3 py-2 transition-colors hover:bg-slate-50">
                  <input
                    type="checkbox"
                    aria-label={container.name}
                    checked={selected.includes(container.id)}
                    onChange={() => toggle(container.id)}
                    className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-800">
                    {container.name}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-slate-400">
                    {container.id.slice(0, 12)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {connect.isError && (
          <ErrorBanner message={toApiError(connect.error).message} />
        )}

        {connect.data && connect.data.failed.length > 0 && (
          <ul
            aria-label="Failed connections"
            className="flex flex-col gap-1 rounded-md border border-red-200 bg-red-50 px-3 py-2"
          >
            {connect.data.failed.map((failure) => (
              <li key={failure.containerId} className="text-xs text-red-700">
                <span className="font-mono">{failure.containerId.slice(0, 12)}</span>:{" "}
                {failure.error}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}