"use client";

import { useEffect, useState } from "react";
import { api, BrowserBreakdown } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
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
export function BrowserCaptureCard({ siteId }: { siteId: string }) {
  const [data, setData] = useState<BrowserBreakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(false);
    api
      .getBrowserBreakdown(siteId)
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [siteId]);

  // Stay invisible until there's something worth showing — no site, an error,
  // or zero captured visitors shouldn't add an empty card to the page.
  if (!siteId || error) return null;
  if (loading && !data) {
    return (
      <Card className="mb-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Capture by browser</CardTitle>
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

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Capture by browser</CardTitle>
        <CardDescription className="text-xs">
          {data.total_visitors} visitors · last {data.window_days} days
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Safari-coverage flag */}
        <div
          className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${s.box}`}
        >
          <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${s.dot}`} />
          <div>
            <p className="font-medium">Safari coverage: {s.label}</p>
            <p className="mt-0.5 opacity-90">{cov.message}</p>
            {cov.status !== "insufficient_data" && (
              <p className="mt-1 opacity-75">
                Captured {pct(cov.actual_share)} Safari vs ~
                {pct(cov.expected_share)} expected for your geo mix.
              </p>
            )}
          </div>
        </div>

        {/* Per-browser 100% stacked bar — hover a segment for details */}
        <div>
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
                </div>
              </div>
            ))}
          </div>

          {/* Legend */}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
            {data.browsers.map((b, i) => (
              <div key={b.browser} className="flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: colorFor(b.browser, i) }}
                />
                <span className="font-medium">{b.browser}</span>
                <span className="text-muted-foreground">{pct(b.share)}</span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
