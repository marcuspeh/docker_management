import { useCallback, useMemo, useRef, useState } from "react";
import {
  apiUrl,
  appendCapped,
  Button,
  formatLogTime,
  Terminal,
  type Container,
  type LogLine,
  type TerminalLine,
  useEventSource,
} from "@portal/shared";

const LEVEL_TONES: [RegExp, TerminalLine["tone"]][] = [
  [/\bERROR\b/, "error"],
  [/\bWARN(ING)?\b/, "error"],
  [/\bINFO\b/, "success"],
];

export type LogPanelProps = {
  container: Container;
};

/**
 * Follows a container's logs.
 *
 * The stream resumes from the time of the last line, so a reconnect picks up
 * where it left off rather than replaying the tail. stderr is shown in red and
 * the usual level prefixes are picked out.
 */
export function LogPanel({ container }: LogPanelProps) {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [stopped, setStopped] = useState(false);
  const lastTime = useRef<string | null>(null);
  const counter = useRef(0);

  const onLog = useCallback((data: unknown) => {
    const line = data as LogLine;
    if (!line || typeof line.msg !== "string") return;
    if (line.time) lastTime.current = line.time;
    counter.current += 1;

    const tone =
      line.stream === "stderr"
        ? "stderr"
        : (LEVEL_TONES.find(([pattern]) => pattern.test(line.msg))?.[1] ?? "stdout");

    setLines((current) =>
      appendCapped(current, [
        {
          key: `${line.time ?? "t"}-${counter.current}`,
          text: `${formatLogTime(line.time)}  ${line.msg}`,
          tone,
        },
      ]),
    );
  }, []);

  const onEnd = useCallback(() => setStopped(true), []);

  const handlers = useMemo(() => ({ log: onLog, end: onEnd }), [onLog, onEnd]);
  const resume = useCallback((): Record<string, string> => {
    return lastTime.current ? { since: lastTime.current } : {};
  }, []);

  const { state, failed, reconnect } = useEventSource(
    apiUrl(`/api/containers/${container.id}/logs`),
    handlers,
    {
      // A stopped container has nothing to follow.
      enabled: container.state === "running" && !stopped,
      resume,
      closeOn: ["end"],
    },
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Logs
        </h4>
        <div className="flex items-center gap-2">
          {state === "open" && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <span className="size-1.5 animate-pulse rounded-full bg-green-500" aria-hidden />
              Live
            </span>
          )}
          {stopped && container.state !== "running" && (
            <span className="text-xs text-slate-500">Container stopped</span>
          )}
          {(failed || stopped) && (
            <Button variant="secondary" size="sm" onClick={reconnect}>
              Reconnect
            </Button>
          )}
        </div>
      </div>
      <Terminal
        lines={lines}
        className="h-72"
        emptyLabel={state === "connecting" ? "Connecting to the log stream..." : "No output yet."}
      />
    </div>
  );
}