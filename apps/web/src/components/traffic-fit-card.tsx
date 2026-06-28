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
import {
  Card,
  CardContent,
  CardDescription,
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

// US (servable) reads green; everything else is a muted "outside coverage" grey.
const dotColor = (country: string) => (country === "US" ? "#22c55e" : "#94a3b8");

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
          <CardTitle className="text-sm">Traffic fit</CardTitle>
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
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <CardTitle className="text-sm">Traffic fit</CardTitle>
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
            <CardDescription className="text-xs">
              {data.located_visitors.toLocaleString()} located ·{" "}
              {period === "lifetime" ? "all time" : `last ${data.window_days} days`}
            </CardDescription>
          </div>
          <PeriodToggle value={period} onChange={setPeriod} />
        </div>
      </CardHeader>
      <CardContent>
        {enough && (
          <div className="mb-3">
            <span className="font-mono text-2xl font-medium tabular-nums">
              ~{pct(data.identifiable_estimate)}
            </span>
            <span className="ml-2 text-sm text-muted-foreground">
              of your visitors are identifiable
            </span>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {pct(data.us_share)} US · beam resolves US traffic only
            </p>
          </div>
        )}
        <p className="text-xs text-muted-foreground">{data.message}</p>

        {data.top_countries.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 text-xs">
            {data.top_countries.map((c) => (
              <div key={c.country} className="flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: dotColor(c.country) }}
                />
                <span className="font-medium">{c.country}</span>
                <span className="text-muted-foreground">{pct(c.share)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
