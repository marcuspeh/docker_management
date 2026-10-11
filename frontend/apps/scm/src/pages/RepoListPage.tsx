import { useSearchParams } from "react-router-dom";
import { GitBranch, Plus } from "lucide-react";
import {
  Button,
  EmptyState,
  ErrorBanner,
  ScmHeader,
  Skeleton,
  toApiError,
} from "@portal/shared";
import { useRepos } from "../queries";
import { RepoCard } from "../components/RepoCard";
import { AddRepoModal } from "../components/AddRepoModal";

/** The repo list at `/scm/`. `?modal=add-repo` opens the Add Repository modal. */
export function RepoListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, isPending, isError, error, refetch } = useRepos();

  const modalOpen = searchParams.get("modal") === "add-repo";
  const closeModal = () => {
    searchParams.delete("modal");
    setSearchParams(searchParams, { replace: true });
  };

  return (
    <div className="min-h-screen">
      <ScmHeader>
        <Button size="sm" onClick={() => setSearchParams({ modal: "add-repo" })}>
          <Plus className="size-4" aria-hidden />
          Add Repository
        </Button>
      </ScmHeader>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Repositories</h2>
          {data && (
            <span className="text-xs text-slate-500">
              {data.length} {data.length === 1 ? "repository" : "repositories"}
            </span>
          )}
        </div>

        {isError && (
          <ErrorBanner
            className="mb-4"
            title="Could not load repositories"
            message={toApiError(error).message}
            onRetry={() => refetch()}
          />
        )}

        {isPending ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-24" />
            ))}
          </div>
        ) : data && data.length === 0 ? (
          <EmptyState
            icon={<GitBranch className="size-8" aria-hidden />}
            title="No repositories yet"
            description="Add a Git repository to deploy one of its branches with Docker Compose."
            action={
              <Button onClick={() => setSearchParams({ modal: "add-repo" })}>
                <Plus className="size-4" aria-hidden />
                Add Repository
              </Button>
            }
          />
        ) : (
          // Old rows stay visible while a refresh is in flight.
          <div className="flex flex-col gap-3">
            {data?.map((repo) => <RepoCard key={repo.id} repo={repo} />)}
          </div>
        )}
      </main>

      <AddRepoModal open={modalOpen} onClose={closeModal} />
    </div>
  );
}