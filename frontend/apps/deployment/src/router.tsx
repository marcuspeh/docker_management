import { createBrowserRouter, Navigate } from "react-router-dom";
import { RepoListPage } from "./pages/RepoListPage";
import { RepoDetailPage } from "./pages/RepoDetailPage";

/**
 * Routes are relative to the app's base path, so `/deployment/` and `/deployment/:repoId`
 * resolve correctly whether the app is served by nginx or by the backend.
 */
export const router = createBrowserRouter([
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
]);