"use client";

import { cn } from "@/lib/utils";

export type Period = "30d" | "lifetime";

/** Days to send to the API for each period. Lifetime is a far-back cutoff that
 *  effectively means "all time" for the backend's `now - days` window. */
export const periodToDays = (p: Period): number => (p === "lifetime" ? 36500 : 30);

export const periodLabel = (p: Period): string =>
  p === "lifetime" ? "Lifetime" : "Last 30 days";

const OPTIONS: { key: Period; label: string }[] = [
  { key: "30d", label: "Last 30 days" },
  { key: "lifetime", label: "Lifetime" },
];

/** Compact segmented Last 30 days / Lifetime switch for metric widgets. */
export function PeriodToggle({
  value,
  onChange,
}: {
  value: Period;
  onChange: (p: Period) => void;
}) {
  return (
    <div className="inline-flex shrink-0 rounded-md border border-border bg-secondary/40 p-0.5 text-[11px]">
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={cn(
            "rounded px-2 py-0.5 transition-colors",
            value === o.key
              ? "bg-card font-medium text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
