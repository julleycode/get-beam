import type { SocialAccount } from "@/lib/api";

export type ConnectionHealth = "connected" | "expiring" | "reconnect";

// Warn when the OAuth token expires within this window.
const WARN_MS = 7 * 24 * 60 * 60 * 1000;

/** Parse an ISO expiry as absolute epoch ms. token_expires_at is UTC; if the
 * serialized string carries no timezone marker, assume UTC (avoids a naive-local
 * misread). Comparing two epoch-ms values is timezone-safe. */
function expiryEpochMs(iso: string): number {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).getTime();
}

export function connectionHealth(account: SocialAccount): ConnectionHealth {
  if (!account.is_active) return "reconnect";
  // Cookie-registered outreach accounts have no OAuth token to expire.
  if (account.is_outreach) return "connected";
  // With a refresh token the backend renews access automatically at send time
  // (e.g. Twitter's 2h tokens), so the access-token expiry is not user-facing.
  if (account.has_refresh_token) return "connected";
  // No known expiry (some platforms don't return one) — assume usable.
  if (!account.token_expires_at) return "connected";
  const remaining = expiryEpochMs(account.token_expires_at) - Date.now();
  if (remaining <= 0) return "reconnect";
  if (remaining <= WARN_MS) return "expiring";
  return "connected";
}

const META: Record<
  ConnectionHealth,
  { label: string; chip: string; dot: string; hint: string }
> = {
  connected: {
    label: "Connected",
    chip: "bg-success/15 text-success",
    dot: "bg-success",
    hint: "This connection is active.",
  },
  expiring: {
    label: "Expiring soon",
    chip: "bg-warning/15 text-warning",
    dot: "bg-warning",
    hint: "This connection expires soon. Reconnect to keep sending.",
  },
  reconnect: {
    label: "Reconnect needed",
    chip: "bg-destructive/15 text-destructive",
    dot: "bg-destructive",
    hint: "This connection expired. Reconnect to keep sending.",
  },
};

export function ConnectionHealthBadge({ health }: { health: ConnectionHealth }) {
  const m = META[health];
  return (
    <span
      title={m.hint}
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${m.chip}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  );
}
