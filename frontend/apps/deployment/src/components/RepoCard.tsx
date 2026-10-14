import { Link } from "react-router-dom";
import { GitBranch, FolderTree } from "lucide-react";
import { Badge, deploymentStatusClass, shortSha, type Repo } from "@portal/shared";

export type RepoCardProps = { repo: Repo };

/** One row in the repo list: name, Git URL, path and the last deployment. */
export function RepoCard({ repo }: RepoCardProps) {
  const last = repo.lastDeployment;

  return (
    <Link
      to={`/${repo.id}`}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-blue-300 hover:bg-blue-50/30"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{repo.name}</p>
          <p className="mt-1 truncate font-mono text-xs text-slate-500">{repo.url}</p>
        </div>
        {last ? (
          <Badge className={deploymentStatusClass(last.status)}>{last.status}</Badge>
        ) : (
          <Badge className="bg-slate-100 text-slate-500 ring-slate-500/20">
            Never deployed
          </Badge>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <FolderTree className="size-3.5" aria-hidden />
          <span className="font-mono">{repo.path}</span>
        </span>
        {last && (
          <span className="inline-flex items-center gap-1.5">
            <GitBranch className="size-3.5" aria-hidden />
            <span className="font-mono">{last.branch}</span>
            <span className="font-mono text-slate-400">{shortSha(last.commitSha)}</span>
          </span>
        )}
      </div>
    </Link>
  );
}