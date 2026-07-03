"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import { api } from "@/lib/api";
import { connectionHealth } from "@/components/connection-health";

// Dismissed per calendar day — the banner re-appears tomorrow if the connection
// is still unhealthy, so a real problem isn't silenced forever by one click.
const DISMISS_KEY = "beam_conn_nudge_dismissed";

function dismissedToday(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === new Date().toDateString();
  } catch {
    return false;
  }
}

/**
 * In-app nudge: if any (non-outreach) social connection is expiring or needs a
 * reconnect, show a dismissible warning above the page with a one-click path to
 * fix it. Reuses the same health computation as the Social Accounts badges and
 * the shared ["social-accounts"] query cache — no extra request.
 */
export function ExpiringConnectionBanner() {
  const { data: accounts } = useQuery({
    queryKey: ["social-accounts"],
    queryFn: () => api.getSocialAccounts(),
    staleTime: 5 * 60_000,
  });
  const [dismissed, setDismissed] = useState(dismissedToday);

  if (dismissed || !accounts) return null;

  const unhealthy = accounts.filter(
    (a) => !a.is_outreach && connectionHealth(a) !== "connected"
  );
  if (unhealthy.length === 0) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, new Date().toDateString());
    } catch {
      /* storage blocked — banner just re-shows next mount */
    }
    setDismissed(true);
  };

  const label =
    unhealthy.length === 1
      ? `Your ${unhealthy[0].platform} connection needs attention`
      : `${unhealthy.length} social connections need attention`;

  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3">
      <div className="flex items-center gap-2.5 text-sm text-warning">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>{label} — reconnect to keep replies sending.</span>
      </div>
      <div className="flex items-center gap-1">
        <Link
          href="/dashboard/social-accounts"
          className="rounded-md border border-warning/40 px-3 py-1 text-xs font-medium text-warning hover:bg-warning/15"
        >
          Reconnect
        </Link>
        <button
          onClick={dismiss}
          aria-label="Dismiss"
          className="rounded-md p-1 text-warning/70 transition-colors hover:text-warning"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
