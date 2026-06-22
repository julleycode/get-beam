"use client";

import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

type InfoTooltipProps = {
  /** Accessible name for the trigger button (the visible icon is decorative). */
  label: string;
  /** Panel content shown on hover/focus. */
  children: React.ReactNode;
  side?: "top" | "bottom";
  align?: "start" | "center" | "end";
  /** Override the panel width / extra classes. */
  className?: string;
};

// Zero-dependency hover/focus tooltip built on the same `group-hover` CSS
// pattern as browser-capture-card.tsx (no Radix tooltip dependency). The panel
// is absolutely positioned off the trigger with a high z-index so it escapes a
// parent table's overflow-x-auto. `group-focus-within:block` reveals it on
// keyboard focus and on touch tap (where :hover never fires), not just mouse.

function panelPosition(side: "top" | "bottom", align: "start" | "center" | "end"): string {
  const vertical = side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5";
  const horizontal =
    align === "start"
      ? "left-0"
      : align === "end"
        ? "right-0"
        : "left-1/2 -translate-x-1/2";
  return `${vertical} ${horizontal}`;
}

export function InfoTooltip({
  label,
  children,
  side = "bottom",
  align = "center",
  className,
}: InfoTooltipProps) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={label}
        className="inline-flex items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <div
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-50 hidden w-72 whitespace-normal rounded-md border bg-popover p-3 text-left text-xs font-normal text-popover-foreground shadow-md group-hover:block group-focus-within:block",
          panelPosition(side, align),
          className
        )}
      >
        {children}
      </div>
    </span>
  );
}
