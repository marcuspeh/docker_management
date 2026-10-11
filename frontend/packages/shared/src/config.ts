/**
 * Build-time configuration, read from Vite's env replacements.
 *
 * The default for `apiBaseUrl` is empty, meaning the API sits on the same origin
 * under `/api` and no CORS setup is needed. To host an app elsewhere, set
 * `VITE_API_BASE_URL` at build time and add that origin to the backend's
 * `CORS_ORIGINS`.
 */
export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  scmUrl: import.meta.env.VITE_SCM_URL ?? "/scm/",
  containersUrl: import.meta.env.VITE_CONTAINERS_URL ?? "/containers/",
} as const;

/** Builds a URL against the API base, keeping a leading slash on the path. */
export function apiUrl(path: string): string {
  const base = config.apiBaseUrl.replace(/\/+$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}