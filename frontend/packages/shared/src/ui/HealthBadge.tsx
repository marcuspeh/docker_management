import { useHealth } from "../api/health";
import { Badge } from "./Badge";

type Level = "ok" | "degraded" | "offline";

const LEVELS: Record<Level, { label: string; className: string }> = {
  ok: { label: "System Online", className: "bg-green-50 text-green-700 ring-green-600/20" },
  degraded: { label: "Degraded", className: "bg-amber-50 text-amber-700 ring-amber-600/20" },
  offline: { label: "Offline", className: "bg-red-50 text-red-700 ring-red-600/20" },
};

/** Polls `/api/health` every 30 seconds through `useHealth`. */
export function HealthBadge() {
  const { data, isError, isPending } = useHealth();

  const level: Level = isError ? "offline" : isPending ? "degraded" : data?.status === "ok" ? "ok" : "degraded";
  const { label, className } = LEVELS[level];

  return (
    <Badge dot className={className} title="Docker and Git status">
      {label}
    </Badge>
  );
}