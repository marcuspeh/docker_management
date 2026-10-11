import type { Container, ContainerState, Port } from "../api/types";

/** The first 7 characters of a commit hash. */
export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "-";
}

/** `8080->8080/tcp`, joined by commas, or `-` when there are no ports. */
export function formatPorts(ports: Port[] | undefined): string {
  if (!ports || ports.length === 0) return "-";
  return ports
    .map((port) => {
      const protocol = port.protocol ?? "tcp";
      if (port.hostPort === null || port.hostPort === undefined) {
        return `${port.containerPort}/${protocol}`;
      }
      const host = port.hostIp && port.hostIp !== "0.0.0.0" ? `${port.hostIp}:` : "";
      return `${host}${port.hostPort}->${port.containerPort}/${protocol}`;
    })
    .join(", ");
}

/** Human-readable elapsed time, for example "3 minutes" or "2 days". */
export function formatDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

function ago(iso: string | null | undefined, now: number): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  return formatDuration(now - then);
}

/** "Up 2 hours" while running, otherwise "Exited 4 hours ago". */
export function formatUptime(container: Container, now = Date.now()): string {
  if (container.state === "running") {
    const elapsed = ago(container.startedAt, now);
    return elapsed ? `Up ${elapsed}` : "Up";
  }
  const elapsed = ago(container.finishedAt ?? container.createdAt, now);
  const verb = container.state === "created" ? "Created" : "Exited";
  return elapsed ? `${verb} ${elapsed} ago` : verb;
}

/** How long a deployment took, or how long it has been running. */
export function formatDeploymentDuration(
  startedAt: string,
  finishedAt: string | null,
  now = Date.now(),
): string {
  return formatDuration(
    (finishedAt ? Date.parse(finishedAt) : now) - Date.parse(startedAt),
  );
}

const STATE_STYLES: Record<ContainerState, string> = {
  running: "bg-green-50 text-green-700 ring-green-600/20",
  exited: "bg-slate-100 text-slate-600 ring-slate-500/20",
  created: "bg-slate-100 text-slate-600 ring-slate-500/20",
  restarting: "bg-amber-50 text-amber-700 ring-amber-600/20",
  paused: "bg-amber-50 text-amber-700 ring-amber-600/20",
  dead: "bg-red-50 text-red-700 ring-red-600/20",
};

/** Badge classes for a container's `state`. */
export function statusBadgeClass(state: ContainerState): string {
  return STATE_STYLES[state] ?? STATE_STYLES.exited;
}

/** A null subnet is shown as a dash. */
export function formatSubnet(subnet: string | null | undefined): string {
  return subnet ?? "-";
}

/** The time part of a log line, for the log panel's gutter. */
export function formatLogTime(iso: string): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return iso;
  return new Date(parsed).toISOString().slice(11, 23);
}

const DEPLOYMENT_STATUS_STYLES: Record<string, string> = {
  queued: "bg-slate-100 text-slate-600 ring-slate-500/20",
  running: "bg-blue-50 text-blue-700 ring-blue-600/20",
  success: "bg-green-50 text-green-700 ring-green-600/20",
  failed: "bg-red-50 text-red-700 ring-red-600/20",
  cancelled: "bg-amber-50 text-amber-700 ring-amber-600/20",
};

export function deploymentStatusClass(status: string): string {
  return DEPLOYMENT_STATUS_STYLES[status] ?? DEPLOYMENT_STATUS_STYLES.queued;
}