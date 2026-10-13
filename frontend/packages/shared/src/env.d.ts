/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the portal API. Empty means same-origin `/api`. */
  readonly VITE_API_BASE_URL?: string;
  /** Where the header's Deployment link points. Defaults to `/deployment/`. */
  readonly VITE_DEPLOYMENT_URL?: string;
  /** Where the header's Containers link points. Defaults to `/containers/`. */
  readonly VITE_CONTAINERS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}