import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export type BadgeProps = {
  children: ReactNode;
  className?: string;
  /** Shows a leading dot, for status badges. */
  dot?: boolean;
  title?: string;
};

/** A small pill. Status colours come from `lib/format`. */
export function Badge({ children, className, dot, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        className,
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}