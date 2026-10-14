import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";
import {
  config,
  ErrorBanner,
  DeploymentHeader,
  shortSha,
  Skeleton,
  toApiError,
} from "@portal/shared";
import { repoKeys, useDeployments, useRepo } from "../queries";
import { DeployPanel } from "../components/DeployPanel";
import { DeploymentHistory } from "../components/DeploymentHistory";
import { DeploymentOutput } from "../components/DeploymentOutput";

/** The repo detail page at `/deployment/:repoId`. */
export function RepoDetailPage() {
  const { repoId } = useParams<{ repoId: string }>();
  const { data: repo, isPending, isError, error, refetch } = useRepo(repoId);
  const { data: deployments } = useDeployments(repoId);
  const queryClient = useQueryClient();

  // The deployment whose output is on screen. null means "follow the newest
  // running one", which is what makes a reload mid-deploy pick the output back
  // up: the state lives in the backend, not in the URL.
  const [pinnedDeploymentId, setPinnedDeploymentId] = useState<string | null>(null);
  const newest = deployments?.[0];
  const runningNewest =
    newest && (newest.status === "running" || newest.status === "queued")
      ? newest.id
      : null;
  // A deployment followed implicitly stops being "newest running" the moment it
  // finishes, which would unmount the panel and throw away the output the user
  // is watching. Latching the id during render keeps the finished log on
  // screen, and the history takes over from there.
  const [lastFollowedId, setLastFollowedId] = useState<string | null>(null);
  if (runningNewest && runningNewest !== lastFollowedId) {
    setLastFollowedId(runningNewest);
  }
  const activeDeploymentId =
    pinnedDeploymentId ?? runningNewest ?? lastFollowedId;

  if (isPending) {
    return (
      <div className="min-h-screen">
        <DeploymentHeader />
        <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="mt-4 h-20" />
          <Skeleton className="mt-6 h-80" />
        </main>
      </div>
    );
  }

  if (isError || !repo) {
    return (
      <div className="min-h-screen">
        <DeploymentHeader />
        <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
          <ErrorBanner
            title="Could not load this repository"
            message={toApiError(error).message}
            onRetry={() => refetch()}
          />
        </main>
      </div>
    );
  }

  const last = repo.lastDeployment;
  // A finished deployment is not "running", so the button unlocks again.
  const running = activeDeploymentId !== null && isRunning(deployments, activeDeploymentId);

  const selectDeployment = (id: string) => {
    setPinnedDeploymentId(id);
  };

  return (
    <div className="min-h-screen">
      <DeploymentHeader />

      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div>
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-xs text-slate-500 transition-colors hover:text-slate-900"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            All repositories
          </Link>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-900">{repo.name}</h2>
            {last?.commitSha && (
              <span className="font-mono text-xs text-slate-500">
                deployed {shortSha(last.commitSha)}
              </span>
            )}
          </div>

          <dl className="mt-2 grid gap-1 text-xs text-slate-500 sm:grid-cols-2">
            <div className="flex gap-2">
              <dt className="text-slate-400">Git URL</dt>
              <dd className="truncate font-mono">{repo.url}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-slate-400">Compose file</dt>
              <dd className="truncate font-mono">
                {repo.path === "/" ? "/" : `${repo.path}/`}
                {repo.composeFile}
              </dd>
            </div>
          </dl>
        </div>

        <DeployPanel
          repoId={repo.id}
          defaultBranch={repo.defaultBranch}
          activeDeploymentId={running ? activeDeploymentId : null}
          onAttach={setPinnedDeploymentId}
        />

        <DeploymentOutput
          key={activeDeploymentId}
          deploymentId={activeDeploymentId}
          onFinish={() => {
            queryClient.invalidateQueries({ queryKey: repoKeys.detail(repo.id) });
            queryClient.invalidateQueries({ queryKey: repoKeys.all });
            queryClient.invalidateQueries({ queryKey: repoKeys.deployments(repo.id) });
          }}
        />

        {last?.status === "success" && (
          <a
            href={`${config.containersUrl}?repoId=${repo.id}`}
            className="inline-flex w-fit items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            <ExternalLink className="size-3.5" aria-hidden />
            View containers
          </a>
        )}

        <section className="flex flex-col gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Deployment History
          </h3>
          <DeploymentHistory
            repoId={repo.id}
            selectedId={activeDeploymentId}
            onSelect={selectDeployment}
          />
        </section>
      </main>
    </div>
  );
}

/** A deployment is live while the backend still reports it as queued or running. */
function isRunning(
  deployments: { id: string; status: string }[] | undefined,
  id: string,
): boolean {
  const match = deployments?.find((deployment) => deployment.id === id);
  return match ? match.status === "running" || match.status === "queued" : true;
}