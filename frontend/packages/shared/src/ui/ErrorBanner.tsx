import { AlertCircle, RefreshCw } from "lucide-react";
import { cn } from "../lib/cn";
import { Button } from "./Button";

export type ErrorBannerProps = {
  title?: string;
  message: string;
  detail?: string;
  onRetry?: () => void;
  className?: string;
};

/** An inline failure notice for actions that are not tied to one field. */
export function ErrorBanner({
  title,
  message,
  detail,
  onRetry,
  className,
}: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2.5",
        className,
      )}
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-500" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="text-xs font-medium text-red-800">{title}</p>}
        <p className="text-xs text-red-700">{message}</p>
        {detail && (
          <pre className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded bg-red-100/60 px-2 py-1 font-mono text-[11px] text-red-700">
            {detail}
          </pre>
        )}
      </div>
      {onRetry && (
        <Button variant="ghost" size="sm" onClick={onRetry}>
          <RefreshCw className="size-3.5" aria-hidden />
          Retry
        </Button>
      )}
    </div>
  );
}