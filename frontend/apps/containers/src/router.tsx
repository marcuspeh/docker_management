import { createBrowserRouter, Navigate } from "react-router-dom";
import { ContainersPage } from "./pages/ContainersPage";

/**
 * One route, declared relative to the app's base path, so `/containers/` works
 * whether the app is served by nginx or by the backend. `basename` strips that
 * prefix before matching, without it `/containers/` would fall through to `*`
 * and redirect out of the app.
 */
export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <ContainersPage />,
    },
    {
      path: "*",
      element: <Navigate to="/" replace />,
    },
  ],
  { basename: import.meta.env.BASE_URL },
);