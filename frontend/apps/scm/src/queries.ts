import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type BranchList,
  type CreateRepoBody,
  type Deployment,
  type Repo,
  type StartDeploymentBody,
} from "@portal/shared";

export const repoKeys = {
  all: ["repos"] as const,
  detail: (id: string) => ["repo", id] as const,
  branches: (id: string) => ["branches", id] as const,
  deployments: (id: string) => ["deployments", id] as const,
};

export function useRepos() {
  return useQuery({
    queryKey: repoKeys.all,
    queryFn: () => api.get<Repo[]>("/api/scm/repos"),
  });
}

export function useRepo(id: string | undefined) {
  return useQuery({
    queryKey: repoKeys.detail(id ?? ""),
    queryFn: () => api.get<Repo>(`/api/scm/repos/${id}`),
    enabled: Boolean(id),
  });
}

export function useBranches(id: string | undefined) {
  return useQuery({
    queryKey: repoKeys.branches(id ?? ""),
    queryFn: () => api.get<BranchList>(`/api/scm/repos/${id}/branches`),
    enabled: Boolean(id),
    // Branches change only when someone pushes.
    staleTime: 60_000,
  });
}

export function useDeployments(id: string | undefined, limit = 20) {
  return useQuery({
    queryKey: [...repoKeys.deployments(id ?? ""), limit],
    queryFn: () =>
      api.get<Deployment[]>(`/api/scm/repos/${id}/deployments`, { query: { limit } }),
    enabled: Boolean(id),
  });
}

export function useCreateRepo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateRepoBody) => api.post<Repo>("/api/scm/repos", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: repoKeys.all }),
  });
}

export function useStartDeployment(repoId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StartDeploymentBody) =>
      api.post<Deployment>(`/api/scm/repos/${repoId}/deployments`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: repoKeys.detail(repoId) });
      queryClient.invalidateQueries({ queryKey: repoKeys.all });
      queryClient.invalidateQueries({ queryKey: repoKeys.deployments(repoId) });
    },
  });
}

/** A deploy already running for this repo is not an error, it is an attach. */
export function isDeployInProgress(error: unknown): string | null {
  if (error instanceof ApiError && error.code === "DEPLOY_IN_PROGRESS") {
    const id = error.detail.deploymentId;
    return typeof id === "string" ? id : null;
  }
  return null;
}