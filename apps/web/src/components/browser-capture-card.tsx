"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ShieldOff } from "lucide-react";
import { api, BrowserBreakdown } from "@/lib/api";
import { cn } from "@/lib/utils";
import { optoutIsAbnormal, optoutMessage } from "@/lib/privacy-optout";
import {
  PeriodToggle,
  periodToDays,
  type Period,
} from "@/components/ui/period-toggle";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const STATUS_STYLES: Record<
  string,
  { box: string; dot: string; label: string }
> = {
  likely_blocked: {
    box: "border-red-300 bg-red-50 text-red-800",
    dot: "bg-red-500",
    label: "Likely blocked",
  },
  watch: {
    box: "border-yellow-300 bg-yellow-50 text-yellow-800",
    dot: "bg-yellow-500",
    label: "Watch",
  },
  ok: {
    box: "border-green-300 bg-green-50 text-green-800",
    dot: "bg-green-500",
    label: "Healthy",
  },
  insufficient_data: {
    box: "border-border bg-muted text-muted-foreground",
    dot: "bg-muted-foreground",
    label: "Not enough data",
  },
};

const pct = (n: number) => `${Math.round(n * 100)}%`;

// Brand-ish color per known browser; unknown browsers get a stable fallback by
// index so two unknowns never collide.
const BROWSER_COLORS: Record<string, string> = {
  Chrome: "#4285F4",
  Safari: "#06b6d4",
  Firefox: "#f97316",
  Edge: "#22c55e",
  Opera: "#ef4444",
  "Samsung Internet": "#a855f7",
  Other: "#94a3b8",
};
const FALLBACK_COLORS = [
  "#6366f1",
  "#ec4899",
  "#14b8a6",
  "#eab308",
  "#8b5cf6",
  "#f43f5e",
];
const colorFor = (browser: string, index: number) =>
  BROWSER_COLORS[browser] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];

/**
 * Per-browser capture breakdown + Safari-coverage estimate. Surfaces whether
 * ITP / content-blockers are dropping the pixel on Safari/iOS — the signal for
 * whether a first-party install is worth building.
 */
export function BrowserCaptureCard({ siteId, period, onPeriodChange }: { siteId: string; period: Period; onPeriodChange: (p: Period) => void }) {
  const [data, setData] = useState<BrowserBreakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(false);
    api
      .getBrowserBreakdown(siteId, periodToDays(period))
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [siteId, period]);

  // Stay invisible until there's something worth showing — no site, an error,
  // or zero captured visitors shouldn't add an empty card to the page.
  if (!siteId || error) return null;
  if (loading && !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Browser type</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    );
  }
  if (!data || data.total_visitors === 0) return null;

  const cov = data.safari_coverage;
  const s = STATUS_STYLES[cov.status] ?? STATUS_STYLES.insufficient_data;
  // Only surface Safari coverage when it's a problem — a warning icon by the
  // title, with the detail on hover. Healthy / not-enough-data stays silent.
  const abnormal = cov.status === "watch" || cov.status === "likely_blocked";

  // Same philosophy for privacy opt-out: the per-browser figure always shows in
  // the segment tooltip, but the site-level indicator only appears when the rate
  // is genuinely abnormal. A healthy card stays uncluttered.
  const optout = data.privacy_optout;
  const optoutAbnormal =
    !!optout && optoutIsAbnormal(optout.visitors, optout.rate);

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <CardTitle className="text-sm">Browser type</CardTitle>
            {abnormal && (
              <span className="group relative inline-flex">
                <AlertTriangle
                  className={cn(
                    "h-4 w-4",
                    cov.status === "likely_blocked"
                      ? "text-destructive"
                      : "text-warning"
                  )}
                  aria-label={`Safari coverage: ${s.label}`}
                />
                <div
                  role="tooltip"
                  className="pointer-events-none absolute left-0 top-full z-50 mt-1.5 hidden w-64 whitespace-normal rounded-md border bg-popover p-3 text-left text-xs font-normal text-popover-foreground shadow-md group-hover:block group-focus-within:block"
                >
                  <p className="font-medium">Safari coverage: {s.label}</p>
                  <p className="mt-0.5 text-muted-foreground">{cov.message}</p>
                  <p className="mt-1 text-muted-foreground">
                    Captured {pct(cov.actual_share)} Safari vs ~
                    {pct(cov.expected_share)} expected for your geo mix.
                  </p>
                </div>
              </span>
            )}
            {optoutAbnormal && optout && (
              <span className="group relative inline-flex">
                <ShieldOff
                  className="h-4 w-4 text-warning"
                  aria-label={`Privacy opt-out: ${pct(optout.rate)}`}
                />
                <div
                  role="tooltip"
                  className="pointer-events-none absolute left-0 top-full z-50 mt-1.5 hidden w-64 whitespace-normal rounded-md border bg-popover p-3 text-left text-xs font-normal text-popover-foreground shadow-md group-hover:block group-focus-within:block"
                >
                  <p className="font-medium">
                    Privacy opt-out: {pct(optout.rate)}
                  </p>
                  <p className="mt-0.5 text-muted-foreground">
                    {optoutMessage(optout.visitors, optout.rate)}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {optout.opted_out} of {optout.visitors} visitors.
                  </p>
                </div>
              </span>
            )}
          </div>
          <PeriodToggle value={period} onChange={onPeriodChange} />
        </div>
      </CardHeader>
      <CardContent>
        {/* Per-browser 100% stacked bar — hover a segment for details */}
        <div className="flex h-8 w-full">
          {data.browsers.map((b, i) => (
            <div
              key={b.browser}
              className="group relative h-full min-w-[3px] cursor-default border-r border-background/60 transition-opacity first:rounded-l-md last:rounded-r-md last:border-r-0 hover:opacity-90"
              style={{
                width: pct(b.share),
                backgroundColor: colorFor(b.browser, i),
              }}
            >
              {/* Tooltip — escapes the bar (no overflow-hidden on the row) */}
              <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md group-hover:block">
                <div className="font-medium">{b.browser}</div>
                <div className="mt-0.5 text-muted-foreground">
                  {b.captured} visitors · {pct(b.share)} · ID{" "}
                  {pct(b.identification_rate)}
                </div>
                {b.optout_rate !== undefined && (
                  <div className="mt-0.5 text-muted-foreground">
                    Privacy opt-out {pct(b.optout_rate)}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
