import { cn } from "@/lib/utils";

type Tone = "success" | "warning" | "info" | "neutral" | "destructive";

const TONE_CLASS: Record<Tone, string> = {
  success: "bg-success-muted text-success",
  warning: "bg-warning-muted text-warning",
  info: "bg-info-muted text-info",
  neutral: "bg-muted text-muted-foreground",
  destructive: "bg-destructive-muted text-destructive",
};

// One source of truth for every status pill across drafts, campaigns,
// billing, visitors and API keys. Add new statuses here, not inline.
const STATUS_TONE: Record<string, Tone> = {
  // drafts / social
  pending: "warning",
  approved: "info",
  sent: "success",
  rejected: "neutral",
  failed: "destructive",
  // campaigns
  draft: "neutral",
  active: "success",
  paused: "warning",
  completed: "info",
  archived: "neutral",
  // billing
  trialing: "info",
  past_due: "warning",
  canceled: "neutral",
  // visitors / enrichment / keys
  identified: "info",
  enriched: "success",
  unresolvable: "neutral",
  valid: "success",
  invalid: "destructive",
};

export function StatusBadge({
  status,
  label,
  tone,
  className,
}: {
  status: string;
  /** Override the displayed text (defaults to the humanized status). */
  label?: string;
  /** Override the tone (defaults to the mapped tone, else neutral). */
  tone?: Tone;
  className?: string;
}) {
  const resolved = tone ?? STATUS_TONE[status.toLowerCase()] ?? "neutral";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        TONE_CLASS[resolved],
        className
      )}
    >
      {label ?? status.replace(/_/g, " ")}
    </span>
  );
}
