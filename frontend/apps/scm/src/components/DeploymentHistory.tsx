import { cn, deploymentStatusClass, formatDeploymentDuration, shortSha, Badge } from "@portal/shared";
import { useDeployments } from "../queries";

export type DeploymentHistoryProps = {
  repoId: string;
  /** The deployment whose output is on screen, highlighted in the list. */
  selectedId: string | null;
  onSelect: (deploymentId: string) => void;
};

/** Past deployments. Selecting one replays its saved output. */
export function DeploymentHistory({ repoId, selectedId, onSelect }: DeploymentHistoryProps) {
  const { data, isPending, isError, refetch } = useDeployments(repoId);

  if (isPending) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((n) => (
          <div key={n} className="h-12 animate-pulse rounded-md bg-slate-100" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <button
        type="button"
        onClick={() => refetch()}
        className="w-full rounded-md border border-dashed border-red-200 py-4 text-xs text-red-600"
      >
        Could not load deployment history. Click to retry.
      </button>
    );
  }

  if (!data || data.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-slate-300 py-6 text-center text-xs text-slate-500">
        No deployments yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-1.5">
      {data.map((deployment) => (
        <li key={deployment.id}>
          <button
            type="button"
            onClick={() => onSelect(deployment.id)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
              deployment.id === selectedId
                ? "border-blue-300 bg-blue-50"
                : "border-slate-200 bg-white hover:bg-slate-50",
            )}
          >
            <Badge className={cn("shrink-0", deploymentStatusClass(deployment.status))}>
              {deployment.status}
            </Badge>
            <span className="w-28 shrink-0 truncate font-mono text-xs text-slate-700">
              {deployment.branch}
            </span>
            <span className="w-16 shrink-0 font-mono text-xs text-slate-500">
              {shortSha(deployment.commitSha)}
            </span>
            <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
              {deployment.commitMessage ?? deployment.error ?? "No commit message"}
            </span>
            <span className="shrink-0 font-mono text-xs text-slate-400">
              {formatDeploymentDuration(deployment.startedAt, deployment.finishedAt)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}