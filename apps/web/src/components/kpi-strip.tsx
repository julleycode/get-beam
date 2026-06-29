"use client";

import { useEffect, useState } from "react";
import { Hash, LineChart as LineChartIcon } from "lucide-react";
import { api, SiteKpis, type TimeseriesPoint } from "@/lib/api";
import { cn } from "@/lib/utils";
import { StatTile } from "@/components/stat-tile";
import { FunnelTrendChart } from "@/components/funnel-trend-chart";
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

const pct = (n: number) => `${Math.round(n * 100)}%`;

type View = "numbers" | "graph";

/**
 * KPI funnel for one site — the numbers a growth marketer reads to judge ROI:
 * visitors → identified → high-intent (qualified leads) → acted-on, plus the
 * identify and action rates. Reply rate / wedge need reply tracking (not built
 * yet) so we surface the gap honestly instead of a fake number.
 */
export function KpiStrip({ siteId }: { siteId: string }) {
  const [data, setData] = useState<SiteKpis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [period, setPeriod] = useState<Period>("30d");
  const [view, setView] = useState<View>("numbers");
  const [series, setSeries] = useState<TimeseriesPoint[] | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState(false);

  useEffect(() => {
    if (!siteId) return;
    let ignore = false;
    setLoading(true);
    setError(false);
    api
      .getSiteKpis(siteId, periodToDays(period))
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch(() => {
        if (!ignore) setError(true);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [siteId, period]);

  // Lazy-load the daily series only when the graph view is open (and refetch on
  // period change). Numbers view never pays for it.
  useEffect(() => {
    if (!siteId || view !== "graph") return;
    // ignore-flag: a slow response from a previous site/period must not paint
    // over the current one. Clear first so stale data can't flash.
    let ignore = false;
    setSeriesLoading(true);
    setSeriesError(false);
    setSeries(null);
    api
      .getSiteTimeseries(siteId, periodToDays(period))
      .then((r) => {
        if (!ignore) setSeries(r.series);
      })
      .catch(() => {
        if (!ignore) setSeriesError(true);
      })
      .finally(() => {
        if (!ignore) setSeriesLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [siteId, view, period]);

  if (!siteId || error) return null;
  if (loading && !data) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Overall</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    );
  }
  if (!data || data.visitors === 0) return null;

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Overall</CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            {/* Numbers ↔ graph view toggle */}
            <div className="inline-flex rounded-md border border-border bg-secondary/40 p-0.5">
              <button
                type="button"
                onClick={() => setView("numbers")}
                title="Numbers"
                aria-label="Numbers view"
                className={cn(
                  "rounded px-1.5 py-0.5 transition-colors",
                  view === "numbers"
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Hash className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setView("graph")}
                title="Graph"
                aria-label="Graph view"
                className={cn(
                  "rounded px-1.5 py-0.5 transition-colors",
                  view === "graph"
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <LineChartIcon className="h-3.5 w-3.5" />
              </button>
            </div>
            <PeriodToggle value={period} onChange={setPeriod} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {view === "graph" ? (
          seriesError ? (
            <p className="py-8 text-center text-xs text-destructive">
              Couldn&apos;t load the chart — try again.
            </p>
          ) : seriesLoading && !series ? (
            <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>
          ) : series && series.length > 0 ? (
            <FunnelTrendChart data={series} />
          ) : (
            <p className="py-8 text-center text-xs text-muted-foreground">
              No data for this period.
            </p>
          )
        ) : (
          <>
            <div className="grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-4">
              <StatTile label="Visitors" value={data.visitors.toLocaleString()} />
              <StatTile
                label="Identified"
                value={data.identified.toLocaleString()}
                tone="info"
              />
              <StatTile
                label="High-intent leads"
                value={data.high_intent.toLocaleString()}
                tone="primary"
              />
              <StatTile
                label="Acted on"
                value={data.acted_high_intent.toLocaleString()}
                tone="success"
              />
            </div>
            <div className="flex flex-wrap gap-x-8 gap-y-2 border-t pt-3 text-sm">
              <div>
                <span className="font-mono font-medium tabular-nums">
                  {pct(data.identify_rate)}
                </span>{" "}
                <span className="text-muted-foreground">identify rate</span>
              </div>
              <div title="Of your qualified (identified + high-intent) leads, how many you've reached out to">
                <span className="font-mono font-medium tabular-nums">
                  {pct(data.action_rate)}
                </span>{" "}
                <span className="text-muted-foreground">action rate</span>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
