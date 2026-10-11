import { createBrowserRouter, Navigate } from "react-router-dom";
import { ContainersPage } from "./pages/ContainersPage";

/**
 * One route, resolved relative to the app's base path, so `/containers/` works
 * whether the app is served by nginx or by the backend.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <ContainersPage />,
  },
  {
    path: "*",
    element: <Navigate to="/" replace />,
  },
]);