import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  default: "text-foreground",
  success: "text-success",
  info: "text-info",
  warning: "text-warning",
  primary: "text-primary",
};

/** A single metric: big DM Mono number over a muted caption. */
export function StatTile({
  label,
  value,
  tone = "default",
  className,
}: {
  label: string;
  value: ReactNode;
  tone?: "default" | "success" | "info" | "warning" | "primary";
  className?: string;
}) {
  return (
    <div className={cn("text-center", className)}>
      <p className={cn("text-2xl font-mono font-medium tabular-nums", TONE[tone])}>
        {value}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
