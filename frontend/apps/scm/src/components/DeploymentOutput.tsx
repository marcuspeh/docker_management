import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiUrl,
  appendCapped,
  Button,
  cn,
  Terminal,
  type DoneEvent,
  type LineEvent,
  type StepEvent,
  type TerminalLine,
  useEventSource,
} from "@portal/shared";

const STEP_LABELS: Record<string, string> = {
  clone: "Clone",
  fetch: "Fetch",
  checkout: "Checkout",
  build: "Build",
  up: "Up",
  networks: "Networks",
};

export type DeploymentOutputProps = {
  deploymentId: string | null;
  /** Called once the stream reports `done`, so the page can refetch. */
  onFinish?: (event: DoneEvent) => void;
  /** Hides the panel entirely when there is nothing to show. */
  className?: string;
};

/**
 * Streams a deployment's log.
 *
 * Each line carries a sequence number, and reconnects ask the backend to replay
 * from the last one, so a page reload or a dropped connection resumes exactly
 * where it left off instead of losing or repeating output.
 */
export function DeploymentOutput({
  deploymentId,
  onFinish,
  className,
}: DeploymentOutputProps) {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [done, setDone] = useState<DoneEvent | null>(null);
  // The last seq is a ref, not state: the reconnect reads it without waiting
  // for a render.
  const lastSeq = useRef(0);
  const onFinishRef = useRef(onFinish);
  useEffect(() => {
    onFinishRef.current = onFinish;
  });

  const onLine = useCallback((data: unknown) => {
    const event = data as LineEvent;
    if (typeof event?.seq !== "number" || typeof event.text !== "string") return;
    lastSeq.current = Math.max(lastSeq.current, event.seq);
    setLines((current) =>
      appendCapped(current, [
        {
          key: `line-${event.seq}`,
          // Commands are sent as `$ <command>` and shown in blue.
          text: event.text,
          tone: event.text.startsWith("$ ") ? "command" : "stdout",
        },
      ]),
    );
  }, []);

  const onStep = useCallback((data: unknown) => {
    const event = data as StepEvent;
    if (!event?.step) return;
    const label = STEP_LABELS[event.step] ?? event.step;
    const tone =
      event.status === "failed" ? "error" : event.status === "succeeded" ? "success" : "muted";
    const suffix =
      event.status === "started" ? "" : event.status === "succeeded" ? " - ok" : " - failed";
    setLines((current) =>
      appendCapped(current, [
        {
          key: `step-${event.step}-${event.status}-${current.length}`,
          text: `[${label}]${suffix}`,
          tone,
        },
      ]),
    );
  }, []);

  const onDone = useCallback((data: unknown) => {
    const event = data as DoneEvent;
    setDone(event);
    onFinishRef.current?.(event);
    setLines((current) =>
      appendCapped(current, [
        {
          key: `done-${event?.status ?? "unknown"}`,
          text:
            event?.status === "success"
              ? `Deployment succeeded${event.commitSha ? ` at ${event.commitSha.slice(0, 7)}` : ""}`
              : `Deployment ${event?.status ?? "failed"}${event?.error ? `: ${event.error}` : ""}`,
          tone: event?.status === "success" ? "success" : "error",
        },
      ]),
    );
  }, []);

  const handlers = useMemo(
    () => ({ line: onLine, step: onStep, done: onDone }),
    [onLine, onStep, onDone],
  );

  const resume = useCallback(
    () => ({ offset: lastSeq.current }),
    [],
  );

  const { state, failed, reconnect } = useEventSource(
    deploymentId ? apiUrl(`/api/scm/deployments/${deploymentId}/logs`) : "",
    handlers,
    {
      enabled: Boolean(deploymentId),
      resume,
      closeOn: ["done"],
    },
  );

  if (!deploymentId) return null;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Deployment Output
        </h3>
        <div className="flex items-center gap-2">
          {state === "open" && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <span className="size-1.5 animate-pulse rounded-full bg-green-500" aria-hidden />
              Streaming
            </span>
          )}
          {(failed || (!done && state === "closed")) && (
            <Button variant="secondary" size="sm" onClick={reconnect}>
              Reconnect
            </Button>
          )}
        </div>
      </div>
      <Terminal
        lines={lines}
        className="h-80"
        emptyLabel={
          state === "connecting" ? "Connecting to the deployment stream..." : "No output yet."
        }
      />
    </div>
  );
}