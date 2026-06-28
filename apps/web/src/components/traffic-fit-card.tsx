"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Globe, XCircle } from "lucide-react";
import { api, TrafficFit } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  PeriodToggle,
  periodToDays,
  type Period,
} from "@/components/ui/period-toggle";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const pct = (n: number) => `${Math.round(n * 100)}%`;

const STATUS: Record<
  TrafficFit["status"],
  { label: string; icon: typeof CheckCircle2; tone: string }
> = {
  good_fit: { label: "Good fit", icon: CheckCircle2, tone: "text-success" },
  partial_fit: { label: "Partial fit", icon: AlertTriangle, tone: "text-warning" },
  poor_fit: { label: "Poor fit", icon: XCircle, tone: "text-red-600" },
  insufficient_data: {
    label: "Not enough data",
    icon: Globe,
    tone: "text-muted-foreground",
  },
};

// US (servable) always reads green; other countries get a stable palette color
// by index so the stacked bar's segments are distinguishable.
const GEO_PALETTE = ["#6366f1", "#06b6d4", "#f97316", "#a855f7", "#f43f5e", "#14b8a6"];
const geoColor = (country: string, i: number) =>
  country === "US" ? "#22c55e" : GEO_PALETTE[i % GEO_PALETTE.length];

/**
 * Traffic-fit readout — what share of this site's visitors beam can actually
 * identify, given person-level identification is US-only. Doubles as a
 * qualification signal: a red "poor fit" means the traffic is mostly outside
 * coverage and won't resolve no matter how long the pixel runs.
 */
export function TrafficFitCard({ siteId }: { siteId: string }) {
  const [data, setData] = useState<TrafficFit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [period, setPeriod] = useState<Period>("30d");

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(false);
    api
      .getTrafficFit(siteId, periodToDays(period))
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [siteId, period]);

  // Stay invisible until there's something worth showing — no site, an error, or
  // zero located visitors shouldn't add an empty card to the page.
  if (!siteId || error) return null;
  if (loading && !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Geo</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    );
  }
  if (!data || data.located_visitors === 0) return null;

  const s = STATUS[data.status] ?? STATUS.insufficient_data;
  const Icon = s.icon;
  const enough = data.status !== "insufficient_data";

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <CardTitle className="text-sm">Geo</CardTitle>
            <span
              className={cn(
                "inline-flex items-center gap-1 text-xs font-medium",
                s.tone
              )}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {s.label}
            </span>
          </div>
          <PeriodToggle value={period} onChange={setPeriod} />
        </div>
      </CardHeader>
      <CardContent>
        {data.top_countries.length > 0 && (
          // 100%-stacked country bar — hover a segment for the country + share.
          // The muted track (rounded) shows any unlabeled remainder. No
          // overflow-hidden on the row so the hover tooltip can escape it.
          <div className="flex h-8 w-full rounded-md bg-secondary">
            {data.top_countries.map((c, i) => (
              <div
                key={c.country}
                className="group relative h-full min-w-[3px] cursor-default border-r border-background/60 transition-opacity first:rounded-l-md last:border-r-0 hover:opacity-90"
                style={{ width: pct(c.share), backgroundColor: geoColor(c.country, i) }}
              >
                <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md group-hover:block">
                  <div className="font-medium">{c.country}</div>
                  <div className="mt-0.5 text-muted-foreground">{pct(c.share)}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {enough && (
          <div className="mt-3 flex items-center gap-1 border-t pt-3 text-sm">
            <span className="font-mono font-medium tabular-nums">
              ~{pct(data.identifiable_estimate)}
            </span>
            <span className="text-muted-foreground">identifiable</span>
            <InfoTooltip label="What “identifiable” means" side="top" align="start">
              <p className="font-medium">
                ~{pct(data.identifiable_estimate)} of visitors are identifiable
              </p>
              <p className="mt-1">
                Estimated share beam can put a name to. Person-level
                identification is US-only, so this ≈ your US traffic share (
                {pct(data.us_share)}) × the US match rate — non-US visitors
                won’t resolve no matter how long the pixel runs.
              </p>
            </InfoTooltip>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
