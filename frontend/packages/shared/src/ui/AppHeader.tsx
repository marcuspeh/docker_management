import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Box, GitBranch } from "lucide-react";
import { config } from "../config";
import { cn } from "../lib/cn";
import { HealthBadge } from "./HealthBadge";

export type AppHeaderProps = {
  /** This app's title, "SCM" or "Containers". */
  title: string;
  /** Where the link to the other app points. */
  otherAppUrl: string;
  otherAppLabel: string;
  children?: ReactNode;
};

/**
 * Each app's own header: the product name, this app's title, a health badge and
 * a link to the other app. The cross-app link is a plain anchor, since it
 * leaves this app's router.
 */
export function AppHeader({
  title,
  otherAppUrl,
  otherAppLabel,
  children,
}: AppHeaderProps) {
  const isScm = title.toLowerCase() === "scm";
  const OtherIcon = isScm ? Box : GitBranch;

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-2">
          <Box className="size-5 text-blue-600" aria-hidden />
          <span className="text-sm font-semibold tracking-tight text-slate-900">
            Docker Management Portal
          </span>
        </div>

        <span className="hidden h-5 w-px bg-slate-200 sm:block" aria-hidden />

        <h1 className="text-sm font-medium text-slate-500">{title}</h1>

        <div className="ml-auto flex items-center gap-3">
          {children}
          <HealthBadge />
          <a
            href={otherAppUrl}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-slate-600",
              "transition-colors hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            <OtherIcon className="size-3.5" aria-hidden />
            {otherAppLabel}
          </a>
        </div>
      </div>
    </header>
  );
}

/** The SCM app's header, linking to the Containers app. */
export function ScmHeader({ children }: { children?: ReactNode }) {
  return (
    <AppHeader title="SCM" otherAppUrl={config.containersUrl} otherAppLabel="Containers">
      {children}
    </AppHeader>
  );
}

/** The Containers app's header, linking to the SCM app. */
export function ContainersHeader({ children }: { children?: ReactNode }) {
  return (
    <AppHeader title="Containers" otherAppUrl={config.scmUrl} otherAppLabel="SCM">
      {children}
    </AppHeader>
  );
}

/** Local in-app navigation, which unlike the cross-app link uses the router. */
export function HeaderLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="rounded-md px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
    >
      {children}
    </Link>
  );
}