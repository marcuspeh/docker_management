import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { cn } from "../lib/cn";

export type TerminalLine = {
  key: string;
  text: string;
  tone?: "command" | "stdout" | "stderr" | "success" | "error" | "muted";
};

const TONES: Record<NonNullable<TerminalLine["tone"]>, string> = {
  command: "text-blue-400",
  stdout: "text-slate-300",
  stderr: "text-red-400",
  success: "text-green-400",
  error: "text-red-400",
  muted: "text-slate-500",
};

export type TerminalProps = {
  lines: TerminalLine[];
  className?: string;
  emptyLabel?: string;
};

/**
 * A dark output panel that follows the tail, unless the user has scrolled up to
 * read something, in which case it holds its position.
 */
export function Terminal({ lines, className, emptyLabel }: TerminalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  // A layout effect keeps the view glued to the bottom as lines arrive.
  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (node && pinned) node.scrollTop = node.scrollHeight;
  }, [lines, pinned]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      setPinned(distance < 24);
    };
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      ref={scrollRef}
      className={cn(
        "overflow-y-auto rounded-md bg-slate-900 px-4 py-3 font-mono text-xs leading-relaxed",
        className,
      )}
    >
      {lines.length === 0 ? (
        <p className="text-slate-500">{emptyLabel ?? "Waiting for output..."}</p>
      ) : (
        lines.map((line) => (
          <div
            key={line.key}
            className={cn("whitespace-pre-wrap break-all", TONES[line.tone ?? "stdout"])}
          >
            {line.text}
          </div>
        ))
      )}
    </div>
  );
}