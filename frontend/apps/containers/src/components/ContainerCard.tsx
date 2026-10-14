import { useState } from "react";
import { CircleDot, Play, RotateCw, ScrollText, Square } from "lucide-react";
import {
  Badge,
  Button,
  cn,
  ErrorBanner,
  formatPorts,
  formatUptime,
  statusBadgeClass,
  toApiError,
  type Container,
} from "@portal/shared";
import { useContainerAction } from "../queries";
import { LogPanel } from "./LogPanel";

export type ContainerCardProps = {
  container: Container;
  logsOpen: boolean;
  onToggleLogs: () => void;
};

/** Name, status, image, ports, networks and uptime, plus lifecycle actions. */
export function ContainerCard({ container, logsOpen, onToggleLogs }: ContainerCardProps) {
  const action = useContainerAction();
  const [failedAction, setFailedAction] = useState<string | null>(null);

  const run = (name: "stop" | "start" | "restart") => {
    setFailedAction(null);
    action.mutate(
      { id: container.id, action: name },
      { onError: () => setFailedAction(name) },
    );
  };

  const running = container.state === "running";
  // A pending action belongs to the container it was started from.
  const pendingFor = (name: string) =>
    action.isPending && failedAction === null && action.variables?.action === name
      ? name
      : null;

  return (
    <article className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <CircleDot
              className={cn(
                "size-4",
                running ? "text-green-500" : "text-slate-300",
              )}
              aria-hidden
            />
            <h3 className="truncate text-sm font-semibold text-slate-900">{container.name}</h3>
            <Badge dot className={statusBadgeClass(container.state)}>
              {container.status}
            </Badge>
          </div>

          <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-slate-500 sm:grid-cols-2">
            <div className="flex gap-2">
              <dt className="text-slate-400">ID</dt>
              <dd className="font-mono">{container.id.slice(0, 12)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="shrink-0 text-slate-400">Image</dt>
              <dd className="truncate font-mono">{container.image}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="shrink-0 text-slate-400">Ports</dt>
              <dd className="truncate font-mono">{formatPorts(container.ports)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="shrink-0 text-slate-400">Uptime</dt>
              <dd>{formatUptime(container)}</dd>
            </div>
          </dl>

          {container.networks.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {container.networks.map((network) => (
                <span
                  key={network}
                  className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
                >
                  {network}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {running ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={action.isPending}
              loading={pendingFor("stop") === "stop"}
              onClick={() => run("stop")}
            >
              <Square className="size-3.5" aria-hidden />
              Stop
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={action.isPending}
                loading={pendingFor("start") === "start"}
                onClick={() => run("start")}
              >
                <Play className="size-3.5" aria-hidden />
                Start
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={action.isPending}
                loading={pendingFor("restart") === "restart"}
                onClick={() => run("restart")}
              >
                <RotateCw className="size-3.5" aria-hidden />
                Restart
              </Button>
            </>
          )}
          <Button
            variant={logsOpen ? "primary" : "secondary"}
            size="sm"
            onClick={onToggleLogs}
          >
            <ScrollText className="size-3.5" aria-hidden />
            View Logs
          </Button>
        </div>
      </div>

      {action.isError && failedAction && (
        <ErrorBanner
          className="mx-4 mb-4"
          message={toApiError(action.error).message}
        />
      )}

      {logsOpen && (
        <div className="border-t border-slate-200 p-4">
          <LogPanel container={container} />
        </div>
      )}
    </article>
  );
}