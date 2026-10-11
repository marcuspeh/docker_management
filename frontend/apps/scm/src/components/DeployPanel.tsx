import { useState } from "react";
import { Rocket } from "lucide-react";
import { Button, toApiError } from "@portal/shared";
import { isDeployInProgress, useStartDeployment } from "../queries";
import { BranchSelect } from "./BranchSelect";

export type DeployPanelProps = {
  repoId: string;
  defaultBranch: string | null;
  /** The deployment already running for this repo, if any. */
  activeDeploymentId: string | null;
  /** Fired when a deploy starts, or when a 409 is turned into an attach. */
  onAttach: (deploymentId: string) => void;
};

/**
 * Picks the branch and starts a deployment.
 *
 * A 409 `DEPLOY_IN_PROGRESS` is not a failure: the panel attaches to the
 * running deployment instead, which is also what makes a page reload during a
 * deploy pick the output back up.
 */
export function DeployPanel({
  repoId,
  defaultBranch,
  activeDeploymentId,
  onAttach,
}: DeployPanelProps) {
  // null means "whatever the repo's default branch is", so a late-arriving
  // default does not need an effect to push it into state.
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deploy = useStartDeployment(repoId);

  const branch = selected ?? defaultBranch ?? "";
  const running = Boolean(activeDeploymentId);

  const submit = () => {
    setError(null);
    deploy.mutate(
      { branch },
      {
        onSuccess: (deployment) => onAttach(deployment.id),
        onError: (cause) => {
          const existing = isDeployInProgress(cause);
          if (existing) {
            onAttach(existing);
            return;
          }
          setError(toApiError(cause).message);
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-end">
      <div className="flex-1">
        <BranchSelect
          repoId={repoId}
          value={branch}
          onChange={setSelected}
          disabled={running}
        />
        {error && <p className="mt-1.5 text-xs text-red-600">{error}</p>}
      </div>
      <Button
        onClick={submit}
        disabled={running || !branch}
        loading={deploy.isPending}
        className="sm:w-44"
      >
        <Rocket className="size-4" aria-hidden />
        {running ? "Deploying Image..." : "Deploy Docker Image"}
      </Button>
    </div>
  );
}