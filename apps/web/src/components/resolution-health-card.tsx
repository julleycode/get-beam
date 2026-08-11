"use client";

import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api, IngestHealth } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  providerMessage,
  providerStatus,
  resolutionHealthSummary,
  unhealthyProviders,
} from "@/lib/resolution-health";

/**
 * Identity-provider outage banner.
 *
 * Deliberately breaks the "healthy stays silent, problems whisper on hover"
 * pattern of the other insight cards on ONE axis: when a provider is dead the
 * message is rendered inline, not behind a tooltip. A dead provider produces
 * zero identified visitors and, because `provider_unavailable` writes no
 * `resolution_logs` row, it also disappears from every other chart — so a hover
 * affordance nobody hovers is how four days of zero output went unnoticed.
 *
 * Healthy and insufficient-data still render nothing at all.
 */
export function ResolutionHealthCard({ siteId }: { siteId: string }) {
  const [data, setData] = useState<IngestHealth | null>(null);

  useEffect(() => {
    if (!siteId) return;
    let ignore = false;
    // 1440 minutes = the endpoint's max window (one day) — the shortest window
    // that reliably clears the sample floor at observed per-site call volumes.
    api
      .getIngestHealth(siteId, 1440)
      .then((r) => {
        if (!ignore) setData(r);
      })
      .catch(() => {
        /* observability must never break the page it observes */
      });
    return () => {
      ignore = true;
    };
  }, [siteId]);

  const providers = data?.resolution_health?.providers ?? [];
  const bad = unhealthyProviders(providers);
  if (bad.length === 0) return null;

  const summary = resolutionHealthSummary(providers);
  const anyDead = bad.some(
    (p) => providerStatus(p.calls, p.unavailable_rate) === "dead"
  );

  return (
    <div
      role="alert"
      className={cn(
        "mb-4 rounded-lg border p-3",
        anyDead
          ? "border-red-300 bg-red-50 text-red-800"
          : "border-yellow-300 bg-yellow-50 text-yellow-800"
      )}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{summary}</p>
          <ul className="mt-1 space-y-0.5">
            {bad.map((p) => (
              <li key={p.provider} className="text-xs">
                {providerMessage(p)}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs opacity-80">
            These are auth or quota failures, not &ldquo;no match&rdquo; — new
            visitors will not be identified until they are fixed. Last 24 hours.
          </p>
        </div>
      </div>
    </div>
  );
}
