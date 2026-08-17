"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CanaryResponse } from "@/lib/canary-format";
import { chooseRevealMode } from "@/lib/canary-reveal-mode";
import type { CanaryOutcome } from "@/lib/onboarding-flow";
import {
  LISTEN_DEADLINE_MS,
  MAX_CONSECUTIVE_ERRORS,
  pollIntervalFor,
  statusFor,
} from "@/lib/canary-listen-status";

export function CanaryListen({
  fingerprint,
  onResult,
  onSkip,
}: {
  fingerprint: string;
  /** "skipped" is the escape hatch's business, not the poll's. */
  onResult: (
    outcome: Exclude<CanaryOutcome, null | "skipped">,
    response: CanaryResponse | null,
  ) => void;
  onSkip: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(Date.now());
  const settled = useRef(false);
  const errorCount = useRef(0);

  // 1s ticker. Its real job is not the copy — it is forcing a re-render so the
  // `refetchInterval` callback below re-evaluates `expired` and the 2s→4s
  // backoff. Without it the interval would be frozen at its first value.
  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - startedAt.current), 1000);
    return () => clearInterval(id);
  }, []);

  const expired = elapsed >= LISTEN_DEADLINE_MS;

  const query = useQuery<CanaryResponse>({
    queryKey: ["onboarding-canary", fingerprint],
    queryFn: ({ signal }) => api.onboardingCanary(fingerprint, signal),
    enabled: !!fingerprint && !settled.current,
    refetchInterval: (q) => {
      if (q.state.data?.landed || expired) return false;
      return pollIntervalFor(Date.now() - startedAt.current);
    },
    // MANDATORY: the dashboard tab is hidden — the user is in the OTHER tab,
    // which is the entire point of this feature. TanStack stops polling hidden
    // tabs by default, so without this the catch silently never lands.
    refetchIntervalInBackground: true,
    // …and refetch the instant they tab back, which is when they are looking.
    refetchOnWindowFocus: true,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  const { data, isError } = query;

  // Count consecutive failures so a dormant endpoint (location_reveal_enabled
  // off → 404) resolves in ~6s instead of making the user wait out the deadline.
  useEffect(() => {
    if (isError) errorCount.current += 1;
    else if (data) errorCount.current = 0;
  }, [isError, data, query.dataUpdatedAt, query.errorUpdatedAt]);

  // ── settle ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (settled.current) return;

    if (data?.landed) {
      settled.current = true;
      onResult("landed", data);
      return;
    }

    const givenUp = expired || errorCount.current >= MAX_CONSECUTIVE_ERRORS;
    if (!givenUp) return;

    settled.current = true;
    // NEVER fake a detection. If the visit didn't land we say so — but geo
    // comes from the caller's own IP and is not gated on the visit, so a
    // VPN/adblocker/DNT user still gets a real reveal instead of nothing.
    // `!== "skip"` deliberately, not `=== "map" || === "text"`: `RevealMode` was
    // widened with `"country"`, and a country card is a real reveal.
    if (data && chooseRevealMode(data) !== "skip") {
      onResult("geo_only", data);
    } else {
      onResult("nothing", data ?? null);
    }
  }, [data, expired, isError, onResult]);

  return (
    <div className="ob-listen" data-testid="canary-listen">
      <div className="ob-radar" aria-hidden="true">
        <span className="ring" />
        <span className="ring" />
        <span className="ring" />
        <span className="core" />
      </div>
      <p className="ob-map-note" data-testid="canary-status" aria-live="polite">
        {statusFor(elapsed)}
      </p>
      {/* Escape hatch, available the whole time — never trap someone in a
          90-second wait for a demo. */}
      <button type="button" className="ob-skip" onClick={onSkip}>
        skip this, just let me install
      </button>
    </div>
  );
}
