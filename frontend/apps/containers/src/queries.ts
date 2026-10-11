import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type ConnectBody,
  type ConnectResult,
  type Container,
  type CreateNetworkBody,
  type Network,
} from "@portal/shared";

export const networkKey = ["networks"] as const;

export const containerKey = (filters: {
  network?: string;
  repoId?: string;
}) => ["containers", filters] as const;

export function useNetworks() {
  return useQuery({
    queryKey: networkKey,
    queryFn: () => api.get<Network[]>("/api/networks"),
  });
}

export function useContainers(filters: { network?: string; repoId?: string }) {
  return useQuery({
    queryKey: containerKey(filters),
    queryFn: () =>
      api.get<Container[]>("/api/containers", {
        // Stopped containers matter here, so the list is not just running ones.
        query: { all: true, network: filters.network, repoId: filters.repoId },
      }),
    // Poll while the tab is visible, so a background tab is not left polling.
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

function useInvalidateContainers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["containers"] });
}

export function useContainerAction() {
  const invalidate = useInvalidateContainers();
  return useMutation({
    mutationFn: ({
      id,
      action,
      body,
    }: {
      id: string;
      action: "stop" | "start" | "restart";
      body?: unknown;
    }) => api.post<Container>(`/api/containers/${id}/${action}`, body),
    onSuccess: invalidate,
    onSettled: invalidate,
  });
}

export function useCreateNetwork() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateNetworkBody) => api.post<Network>("/api/networks", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: networkKey });
      queryClient.invalidateQueries({ queryKey: ["containers"] });
    },
  });
}

export function useDeleteNetwork() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/api/networks/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: networkKey });
      queryClient.invalidateQueries({ queryKey: ["containers"] });
    },
  });
}

export function useConnectContainers(networkId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectBody) =>
      api.post<ConnectResult>(`/api/networks/${networkId}/connect`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: networkKey });
      queryClient.invalidateQueries({ queryKey: ["containers"] });
    },
  });
}