import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useEventSource } from "./useEventSource";

/** A stand-in for the browser's EventSource that tests drive by hand. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  closed = false;

  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  private listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  static get latest(): FakeEventSource {
    const instance = FakeEventSource.instances.at(-1);
    if (!instance) throw new Error("no EventSource was opened");
    return instance;
  }

  addEventListener(name: string, handler: (event: MessageEvent) => void) {
    this.listeners.set(name, handler);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  /* Test helpers */

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  emit(name: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    if (name === "message") this.onmessage?.(event);
    else this.listeners.get(name)?.(event);
  }

  error() {
    this.onerror?.();
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useEventSource", () => {
  it("opens the stream and reports it open", () => {
    const { result } = renderHook(() =>
      useEventSource("/api/scm/deployments/d1/logs", {}),
    );

    expect(FakeEventSource.latest.url).toBe("/api/scm/deployments/d1/logs");

    act(() => FakeEventSource.latest.open());
    expect(result.current.state).toBe("open");
  });

  it("resumes from the last received sequence number", () => {
    let lastSeq = 0;
    renderHook(() =>
      useEventSource(
        "/api/scm/deployments/d1/logs",
        {
          line: (data) => {
            lastSeq = (data as { seq: number }).seq;
          },
        },
        { resume: () => ({ offset: lastSeq }) },
      ),
    );

    act(() => FakeEventSource.latest.open());
    act(() => FakeEventSource.latest.emit("line", { seq: 7, text: "$ build" }));

    expect(FakeEventSource.latest.url).toBe("/api/scm/deployments/d1/logs?offset=0");

    // The stream drops, so the hook reconnects from the last seq it saw.
    act(() => FakeEventSource.latest.error());
    act(() => vi.advanceTimersByTime(1000));

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.latest.url).toBe("/api/scm/deployments/d1/logs?offset=7");
  });

  it("closes on a terminal event instead of retrying", () => {
    const onDone = vi.fn();
    const { result } = renderHook(() =>
      useEventSource("/api/scm/deployments/d1/logs", { done: onDone }, { closeOn: ["done"] }),
    );

    act(() => FakeEventSource.latest.open());
    act(() => FakeEventSource.latest.emit("done", { status: "success" }));

    expect(onDone).toHaveBeenCalledOnce();
    expect(FakeEventSource.latest.closed).toBe(true);
    expect(result.current.state).toBe("closed");

    // A terminal event is a clean close, not a failed reconnect.
    act(() => vi.advanceTimersByTime(5000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("gives up after five failed reconnects", () => {
    const { result } = renderHook(() => useEventSource("/api/scm/deployments/d1/logs", {}));

    for (let attempt = 0; attempt < 6; attempt += 1) {
      act(() => FakeEventSource.latest.error());
      act(() => vi.advanceTimersByTime(1000));
    }

    // One initial connection plus five retries.
    expect(FakeEventSource.instances).toHaveLength(6);
    expect(result.current.failed).toBe(true);
  });

  it("stays closed while disabled", () => {
    const { result } = renderHook(() =>
      useEventSource("/api/scm/deployments/d1/logs", {}, { enabled: false }),
    );

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.state).toBe("closed");
  });

  it("closes on unmount", () => {
    const { unmount } = renderHook(() => useEventSource("/api/containers/c1/logs", {}));

    const source = FakeEventSource.latest;
    unmount();

    expect(source.closed).toBe(true);
  });

  it("passes non-JSON payloads through as text", () => {
    const onMessage = vi.fn();
    renderHook(() =>
      useEventSource("/api/containers/c1/logs", { message: onMessage }),
    );

    act(() => FakeEventSource.latest.open());
    act(() => FakeEventSource.latest.onmessage?.({ data: "plain text" } as MessageEvent));

    expect(onMessage).toHaveBeenCalledWith("plain text", expect.anything());
  });
});