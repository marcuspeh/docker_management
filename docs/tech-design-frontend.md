# Docker Management Portal: Frontend Tech Design

The frontend is **two separate web apps**, each built with Vite, React and TypeScript:
- **Deployment app:** register repos and deploy a branch.
- **Containers app:** manage containers and networks, and view logs.

Each app has its own entry point, dev server, build and URL, and works as a page on its own. There is no host shell and no microfrontend runtime. Code both apps need lives in a shared workspace package that each app compiles in at build time.

The supplied prototype is a **sample**: it's a reference for screens, interactions and visual style only. All data comes from the backend described in [tech-design-backend.md](tech-design-backend.md), which owns the API contract.

## Scope
- **Deployment app:** the repo list, and a repo detail page with branch selection, deploy, live deployment output and deployment history.
- **Containers app:** the networks sidebar, container cards with actions, and live logs.
- **Shared package:** the API client, contract types, SSE hook, formatting helpers, UI components and theme.
- **Out of scope:**
  - The sample's Argos Logs and TCC Configs tabs.
  - The sample's Metrics modal.
  - Auth screens.
  - A host shell, or any microfrontend runtime.

## Stack
- npm workspaces (one lockfile for both apps and the shared package)
- Vite, React and TypeScript (strict mode). Each app is scaffolded with `npm create vite@latest -- --template react-ts`.
- React Router for routing within each app
- TanStack Query for server state
- Tailwind CSS v4 through `@tailwindcss/vite`, with `clsx` and `tailwind-merge`
- lucide-react for icons
- framer-motion for small transitions
- `@fontsource/ibm-plex-sans` and `@fontsource/jetbrains-mono` for fonts
- ESLint and Vitest

All packages are installed at their latest stable versions when scaffolded.

## Reference behavior from the sample
**Deployment**
- A repo list with name, Git URL and path. An "Add Repository" modal takes name, Git URL and path, with the path defaulting to `/`.
- A repo detail page with a "Target Branch" select and a "Deploy Docker Image" button. While a deploy runs the button reads "Deploying Image...".
- A dark "Deployment Output" terminal shows the commands and their output, then success or failure.

**Containers**
- A networks sidebar showing name and driver, with an "All Networks" option. Create a network by name, delete one after a confirmation, and connect several containers to a network at once.
- Container cards showing name, status badge, short ID, image, ports, networks and uptime. Search by name, ID or image, and filter by network.
- **Stop** and **View Logs** actions. View Logs opens an inline live panel with stderr in red.

**Visual style:** a light theme with slate greys and blue accents, IBM Plex Sans for text and JetBrains Mono for code, IDs and paths, crisp borders, and dark terminal panels.

## Where the apps differ from the sample
- **No tab bar.** The sample's shared header with tabs is replaced by a header in each app showing the product name, the app's title, a health badge and a link to the other app.
- The Add Repository path field is labelled "Compose file location" instead of "Dockerfile location". There's also an optional compose file name, defaulting to `docker-compose.yml`.
- The Deployment Output shows the real compose commands from the backend, not `docker build` and `docker run`.
- A repo's detail page uses its own route (`/deployment/:repoId`) instead of `?repoId=`.
- The deploy state comes from the backend instead of `?building=true`, so it survives a page reload.
- The repo detail page shows the deployed commit hash and a deployment history.
- Container cards add Start and Restart for stopped containers.
- There's no Metrics modal. The image badge is plain text.

## Workspace structure

```
frontend/
  package.json               # "workspaces": ["apps/*", "packages/*"]; root scripts run both apps
  tsconfig.base.json
  eslint.config.js
  apps/
    deployment/
      index.html
      package.json           # name: @portal/deployment-app; depends on @portal/shared
      vite.config.ts         # base "/deployment/", port 5173, proxy /api
      src/
        main.tsx             # QueryClientProvider + RouterProvider + theme import
        router.tsx
        pages/RepoListPage.tsx  pages/RepoDetailPage.tsx
        components/          # RepoCard, AddRepoModal, BranchSelect, DeployPanel, DeploymentOutput, DeploymentHistory
        queries.ts           # Deployment query hooks + mutations
    containers/
      index.html
      package.json           # name: @portal/containers-app; depends on @portal/shared
      vite.config.ts         # base "/containers/", port 5174, proxy /api
      src/
        main.tsx
        router.tsx
        pages/ContainersPage.tsx
        components/          # NetworkSidebar, ContainerCard, LogPanel, CreateNetworkModal, ConnectContainersModal, DeleteNetworkModal
        queries.ts           # containers + networks query hooks + mutations
  packages/
    shared/
      package.json           # name: @portal/shared; "exports" point at src (no build step)
      src/
        api/client.ts        # fetch wrapper, base URL from config, ApiError
        api/types.ts         # mirrors the backend API contract
        api/health.ts        # useHealth()
        sse/useEventSource.ts
        ui/                  # Button, Input, Select, Modal, Badge, Terminal, EmptyState, ErrorBanner, AppHeader, HealthBadge
        lib/format.ts  lib/cn.ts
        config.ts            # reads VITE_API_BASE_URL, VITE_DEPLOYMENT_URL, VITE_CONTAINERS_URL
        theme.css            # @import "tailwindcss"; @theme tokens; @source for shared components
```

- **Independence:** each app depends only on `@portal/shared`, never on the other app. Either one can be built, served and deployed without the other.
- **Shared code:** the shared package is TypeScript source, compiled by whichever app imports it. There's no separate publish or build step, and each app's bundle contains only the shared code it uses.
- **Tailwind:** `theme.css` uses `@source` to point Tailwind at the shared components, so their classes are generated in each app's CSS.

## Configuration
Each app reads build-time environment variables through `packages/shared/src/config.ts`:
- `VITE_API_BASE_URL`: the API's address. The default is empty, meaning same-origin `/api`.
- `VITE_DEPLOYMENT_URL`: where the header's "Deployment" link goes. The default is `/deployment/`.
- `VITE_CONTAINERS_URL`: where the header's "Containers" link and the Deployment app's "View containers" link go. The default is `/containers/`.

By default all three apps (API, Deployment, Containers) share one origin, so no CORS is needed. To host an app elsewhere, set `VITE_API_BASE_URL` at build time and set `CORS_ORIGINS` on the backend.

## Deployment app

### Routes (base path `/deployment/`)
- `/deployment/`: the repo list. `?modal=add-repo` opens the Add Repository modal.
- `/deployment/:repoId`: the repo detail page. `?branch=` holds the selected branch.
- Any other path redirects to `/deployment/`.

### Pages and the endpoints they use
**Header**
- `AppHeader` shows the title "Deployment", the `HealthBadge`, and a link to the Containers app.
- `HealthBadge` calls `GET /api/health` every 30 seconds. It shows "System Online" (green) when `ok`, "Degraded" (amber) when `degraded`, and "Offline" (red) when the request fails.

**RepoListPage**
- Loads `GET /api/deployment/repos`. Each `RepoCard` shows name, URL, path and the last deployment (branch, short SHA and status).
- `AddRepoModal` calls `POST /api/deployment/repos`. Errors are shown in place:
  - `REPO_UNREACHABLE` shows Git's error output under the URL field.
  - `NAME_TAKEN` and `INVALID_NAME` show under the name field.
  - `INVALID_PATH` shows under the path field.
- On success, the modal closes and the list refetches.
- The empty state prompts the user to add the first repository.

**RepoDetailPage**
- Loads `GET /api/deployment/repos/{id}` for the header (name, URL, path, last deployed commit).
- `BranchSelect` loads `GET /api/deployment/repos/{id}/branches`, with the default branch preselected.
- `DeployPanel`:
  - The Deploy button calls `POST /api/deployment/repos/{id}/deployments`.
  - If the response is 409 `DEPLOY_IN_PROGRESS`, the panel attaches to `detail.deploymentId` instead of showing an error.
  - The button is disabled and reads "Deploying Image..." while the deployment is `queued` or `running`.
- `DeploymentOutput` subscribes to `GET /api/deployment/deployments/{did}/logs`:
  - `$ ` lines are shown in blue. A `step` event shows a step header with its status.
  - `done` shows a green success line (with the short commit hash) or a red failure line (with the error and the step that failed).
  - The output auto-scrolls unless the user has scrolled up.
  - After a successful deploy, a "View containers" link opens the Containers app filtered to this repo (`{VITE_CONTAINERS_URL}?repoId=<id>`).
- `DeploymentHistory` loads `GET /api/deployment/repos/{id}/deployments?limit=20`. It shows branch, short SHA, commit message, status and duration. Clicking a row replays that deployment's output.
- On load, if the newest deployment is `running`, the page attaches to its stream automatically.

### Query keys and invalidation
- Keys: `['repos']`, `['repo', id]`, `['branches', id]`, `['deployments', repoId]`.
- Adding a repo invalidates `repos`.
- Starting a deploy, or a deploy finishing, invalidates `repo`, `repos` and `deployments`.

## Containers app

### Routes (base path `/containers/`)
- `/containers/`: the containers page.
  - `?network=` filters by network. `?repoId=` filters to one repo's containers, for the Deployment app's link. `?expandedLogId=` opens a container's log panel.
  - `?modal=create-network`, `?modal=connect&targetNetwork=` and `?modal=delete-network&targetNetwork=` open the network modals.
- Any other path redirects to `/containers/`.

### Page and the endpoints it uses
**Header**
- `AppHeader` shows the title "Containers", the `HealthBadge`, and a link to the Deployment app.

**ContainersPage**
- `NetworkSidebar` loads `GET /api/networks`. Built-in and compose-owned networks show a lock icon and have no Delete action.
- The container list loads `GET /api/containers?all=true&network=<selected>&repoId=<filter>`.
  - It refreshes every 5 seconds while the tab is visible.
  - The search box filters the loaded list on the client.
  - When `repoId` is set, a removable chip shows the repo filter.
- `ContainerCard` actions:
  - Stop calls `POST .../stop`.
  - Start and Restart call `POST .../start` and `POST .../restart`.
  - Buttons show a spinner while the request is pending, then the list refetches.
- `LogPanel` subscribes to `GET /api/containers/{id}/logs?tail=200`. stderr lines are red, and INFO, WARN and ERROR prefixes are highlighted. An `end` event shows "Container stopped".
- The network modals:
  - `CreateNetworkModal` calls `POST /api/networks` and shows `NAME_TAKEN` under the name field.
  - `ConnectContainersModal` lists containers not already on the network and calls `POST /api/networks/{id}/connect`. Any `failed[]` entries are shown individually.
  - `DeleteNetworkModal` calls `DELETE /api/networks/{id}`. It keeps the sample's warning that connected containers will be disconnected.

### Query keys and invalidation
- Keys: `['containers', { network, repoId }]`, `['networks']`.
- Container actions invalidate `containers`.
- Network changes invalidate `networks` and `containers`.

## Shared package (`@portal/shared`)

### API client
- `api/client.ts` builds URLs from `VITE_API_BASE_URL`.
- It throws `ApiError` with `code`, `message` and `detail` from the backend's error envelope. Network failures become `code: "NETWORK"`.
- **Query defaults** (each app's `QueryClient`): `staleTime` of 5 seconds, a single retry for reads and none for mutations.

### Streaming (`useEventSource`)
- **API:** `useEventSource(url, handlers, { enabled, resume })`. It's built on the browser's `EventSource`, which sends cookies, so auth can be added later without changes here.
- **Resume:**
  - For deployment output, it reconnects with `offset` set to the last received `seq`, so no lines are lost or repeated.
  - For container logs, it reconnects with `since` set to the time of the last line.
- **Lifecycle:** it closes after `done` or `end`, or when the component unmounts. It stops retrying after 5 failed reconnects in a row and shows a "Reconnect" button.
- **Memory:** the log panel and deployment output keep at most 5,000 lines in memory and drop the oldest first.

### Display formatting (`lib/format.ts`)
- Ports are formatted from `ports[]` as `8080->8080/tcp`, joined by commas, or `-` when there are none.
- Uptime is "Up 2 hours" from `startedAt` for running containers, and "Exited 4 hours ago" from `finishedAt` otherwise.
- The status badge colour comes from `state`: green for running, slate for exited or created, amber for restarting or paused, red for dead. Its text comes from `status`.
- A short SHA is the first 7 characters.
- A `null` subnet is shown as `-`.

### Errors and loading states
- Form modals show errors on the matching field. Other failed actions show an inline `ErrorBanner` on the page or card.
- Lists show skeleton rows on first load and keep the old data visible while refreshing.

## Dev workflow and build
- `npm install` at `frontend/` installs everything for both apps and the shared package.
- **Dev servers:**
  - `npm run dev:deployment` starts the Deployment app on port 5173.
  - `npm run dev:containers` starts the Containers app on port 5174.
  - `npm run dev` starts both.
  - Each dev server proxies `/api`, including SSE, to uvicorn on `http://localhost:8000`.
- **Builds:**
  - `npm run build -w @portal/deployment-app` writes `apps/deployment/dist`.
  - `npm run build -w @portal/containers-app` writes `apps/containers/dist`.
  - `npm run build` builds both. Each build runs a type check with `tsc -b` first.
- `npm run lint` and `npm run test` run across all workspaces.

## Deployment
- **Default:** the backend serves each app's `dist` under its base path, `/deployment/` and `/containers/`. `/` redirects to `/deployment/`. See the backend document's static hosting section.
- **Separate hosting:** either app's `dist` can be put on any static host with an `index.html` fallback for its base path. Rebuild it with `VITE_API_BASE_URL` (and, if needed, the other app's URL) set, and add its origin to the backend's `CORS_ORIGINS`.

## Verification
- **Static checks:** the `tsc` type check and ESLint across all workspaces.
- **Unit tests (Vitest):**
  - The shared package: `lib/format.ts`, `api/client.ts` error parsing, and `useEventSource` resume logic with a mocked `EventSource`.
  - Small component tests in each app for error handling in `AddRepoModal` and `ConnectContainersModal`.
- **Independence checks:**
  - Build and serve each app alone and confirm it works.
  - Confirm neither app's bundle imports from the other app (an ESLint `no-restricted-imports` rule enforces this).
- **Manual end-to-end** against a running backend:
  - **Deployment:** add a repo, select a branch and deploy. Reload during the deploy and check the output picks up again. Check the commit hash appears and the history updates. Open `/deployment/<id>` directly. Follow "View containers".
  - **Containers:** filter by network and by repo, search, view logs, stop, start and restart. Create a network, connect containers to it, then delete it.
