/**
 * Keeps memory bounded when a build or a log stream runs for a long time: the
 * log panel and the deployment output hold at most this many lines and drop the
 * oldest first.
 */
export const MAX_STREAM_LINES = 5000;

/** Appends lines, discarding the oldest ones past the cap. */
export function appendCapped<T>(lines: T[], next: T[], cap = MAX_STREAM_LINES): T[] {
  const combined = [...lines, ...next];
  return combined.length > cap ? combined.slice(combined.length - cap) : combined;
}