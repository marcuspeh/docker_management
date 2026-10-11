import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Health } from "./types";

export const healthKey = ["health"] as const;

/** Polls `/api/health` for the header badge. */
export function useHealth() {
  return useQuery({
    queryKey: healthKey,
    queryFn: () => api.get<Health>("/api/health"),
    refetchInterval: 30_000,
    // A failed poll means "Offline", so it must not sit in a retry backoff.
    retry: false,
  });
}