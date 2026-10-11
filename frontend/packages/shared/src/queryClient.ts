import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api/client";

/**
 * Query defaults shared by both apps: a short stale time, one retry for reads
 * and none for mutations.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        retry: (failureCount, error) => {
          // A request the server actively rejected will not succeed on a retry.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 1;
        },
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}