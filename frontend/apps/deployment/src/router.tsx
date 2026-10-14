import { createBrowserRouter, Navigate } from "react-router-dom";
import { RepoListPage } from "./pages/RepoListPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";

/**
 * Routes are declared relative to the app's base path, so `/deployment/` and
 * `/deployment/:repoId` resolve correctly whether the app is served by nginx or
 * by the backend. `basename` strips that prefix before matching, without it
 * `/deployment/` would match `/:repoId` and the list would never render.
 */
export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <RepoListPage />,
    },
    {
      path: "/:repoId",
      element: <RepoDetailPage />,
    },
    {
      path: "*",
      element: <Navigate to="/" replace />,
    },
  ],
  { basename: import.meta.env.BASE_URL },
);