import { Lock, Network as NetworkIcon, Plus, Trash2 } from "lucide-react";
import { Button, cn, Skeleton, type Network } from "@portal/shared";

export type NetworkSidebarProps = {
  networks: Network[] | undefined;
  isPending: boolean;
  selected: string | null;
  onSelect: (name: string | null) => void;
  onCreate: () => void;
  onConnect: (network: Network) => void;
  onDelete: (network: Network) => void;
};

/**
 * Networks by name and driver. Built-in and compose-owned networks are locked:
 * the backend refuses to delete them, so the page does not offer to.
 */
export function NetworkSidebar({
  networks,
  isPending,
  selected,
  onSelect,
  onCreate,
  onConnect,
  onDelete,
}: NetworkSidebarProps) {
  return (
    <aside className="flex w-full shrink-0 flex-col gap-2 lg:w-64">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Networks
        </h2>
        <Button variant="ghost" size="sm" onClick={onCreate} aria-label="Create network">
          <Plus className="size-4" aria-hidden />
        </Button>
      </div>

      <nav className="flex flex-col gap-1">
        <NetworkRow
          label="All Networks"
          icon={<NetworkIcon className="size-4" aria-hidden />}
          active={selected === null}
          onClick={() => onSelect(null)}
        />

        {isPending ? (
          [0, 1, 2].map((n) => <Skeleton key={n} className="h-9" />)
        ) : (
          networks?.map((network) => {
            const locked = network.builtin || network.composeManaged;
            return (
              <NetworkRow
                key={network.id}
                label={network.name}
                sublabel={`${network.driver} · ${network.containerCount}`}
                icon={
                  locked ? (
                    <Lock className="size-3.5 text-slate-400" aria-hidden />
                  ) : (
                    <NetworkIcon className="size-4" aria-hidden />
                  )
                }
                active={selected === network.name}
                onClick={() => onSelect(network.name)}
                actions={
                  <>
                    <button
                      type="button"
                      onClick={() => onConnect(network)}
                      aria-label={`Connect containers to ${network.name}`}
                      className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
                    >
                      <Plus className="size-3.5" aria-hidden />
                    </button>
                    {!locked && (
                      <button
                        type="button"
                        onClick={() => onDelete(network)}
                        aria-label={`Delete ${network.name}`}
                        className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </button>
                    )}
                  </>
                }
              />
            );
          })
        )}
      </nav>
    </aside>
  );
}

type NetworkRowProps = {
  label: string;
  sublabel?: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  actions?: React.ReactNode;
};

function NetworkRow({ label, sublabel, icon, active, onClick, actions }: NetworkRowProps) {
  return (
    <div
      className={cn(
        "group flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
        active ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100",
      )}
    >
      <button type="button" onClick={onClick} className="flex min-w-0 flex-1 items-center gap-2">
        {icon}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium">{label}</span>
          {sublabel && (
            <span className="block truncate font-mono text-[10px] text-slate-400">
              {sublabel}
            </span>
          )}
        </span>
      </button>
      {actions && (
        <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {actions}
        </span>
      )}
    </div>
  );
}