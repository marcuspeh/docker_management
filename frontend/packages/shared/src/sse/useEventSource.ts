import { useCallback, useEffect, useRef, useState } from "react";

/** Gives up after this many consecutive failed reconnects. */
const MAX_RETRIES = 5;
/** Backoff before each automatic reconnect. */
const RETRY_DELAY_MS = 1000;

export type EventSourceHandlers = Record<
  string,
  ((data: unknown, event: MessageEvent) => void) | undefined
>;

export type UseEventSourceOptions = {
  /** When false the stream stays closed. */
  enabled?: boolean;
  /**
   * Query parameters to (re)connect with, given what has been received so far.
   * Deploy logs resume from the last `seq`, container logs from the time of the
   * last line, so nothing is lost or repeated.
   */
  resume?: () => Record<string, string | number>;
  /** Named events that end the stream, for example `done` or `end`. */
  closeOn?: string[];
};

export type EventSourceState = "connecting" | "open" | "closed" | "failed";

/**
 * Subscribes to a Server-Sent Events stream.
 *
 * Built on the browser's `EventSource`, which sends cookies, so auth can be
 * added later without touching this hook. Named events go to the matching
 * handler and a plain `message` event to the `message` key.
 */
export function useEventSource(
  url: string,
  handlers: EventSourceHandlers,
  options: UseEventSourceOptions = {},
) {
  const { enabled = true, resume, closeOn = [] } = options;

  const [state, setState] = useState<EventSourceState>("connecting");
  const [attempts, setAttempts] = useState(0);
  // Bumped to reconnect, which re-reads the resume position.
  const [generation, setGeneration] = useState(0);
  // Consecutive failed reconnects. A ref, not effect-local state: the effect
  // re-runs on every attempt and must not reset the count.
  const failuresRef = useRef(0);

  // Handlers and options are read through a ref so a new object identity on
  // every render neither tears the stream down nor serves stale callbacks.
  // Declared before the connecting effect so it is populated first on mount.
  const latest = useRef({ handlers, resume, closeOn });
  useEffect(() => {
    latest.current = { handlers, resume, closeOn };
  });

  const reconnect = useCallback(() => {
    failuresRef.current = 0;
    setAttempts(0);
    setGeneration((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    const buildUrl = () => {
      const params = latest.current.resume?.() ?? {};
      const query = new URLSearchParams(
        Object.entries(params).map(([key, value]) => [key, String(value)]),
      ).toString();
      if (!query) return url;
      return `${url}${url.includes("?") ? "&" : "?"}${query}`;
    };

    const connect = () => {
      if (disposed) return;
      source = new EventSource(buildUrl());
      setState("connecting");

      source.onopen = () => {
        failuresRef.current = 0;
        setAttempts(0);
        setState("open");
      };

      source.onmessage = (event) => {
        latest.current.handlers.message?.(parseData(event), event);
      };

      source.onerror = () => {
        source?.close();
        if (disposed) return;

        // The browser also closes after the server's terminal event, so only a
        // close nothing asked for counts as a failed reconnect.
        failuresRef.current += 1;
        const failures = failuresRef.current;
        setAttempts(failures);
        if (failures > MAX_RETRIES) {
          setState("failed");
          return;
        }
        setState("closed");
        timer = setTimeout(() => setGeneration((n) => n + 1), RETRY_DELAY_MS);
      };

      // Every named event needs its own listener; `message` is already covered
      // by onmessage above.
      for (const name of Object.keys(latest.current.handlers)) {
        if (name === "message") continue;
        source.addEventListener(name, (event) => {
          const message = event as MessageEvent;
          latest.current.handlers[name]?.(parseData(message), message);
          if (latest.current.closeOn.includes(name)) {
            source?.close();
            if (!disposed) setState("closed");
          }
        });
      }
    };

    connect();

    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [url, enabled, generation]);

  // A disabled hook is closed, without needing an effect to say so.
  const currentState: EventSourceState = enabled ? state : "closed";

  return {
    state: currentState,
    attempts,
    failed: currentState === "failed",
    reconnect,
  };
}

function parseData(event: MessageEvent): unknown {
  if (typeof event.data !== "string") return event.data;
  try {
    return JSON.parse(event.data);
  } catch {
    return event.data;
  }
}