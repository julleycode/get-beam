"use client";

import { useEffect, useState } from "react";
import { api, SiteKpis } from "@/lib/api";
import { StatTile } from "@/components/stat-tile";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const pct = (n: number) => `${Math.round(n * 100)}%`;

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

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(false);
    api
      .getSiteKpis(siteId)
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [siteId]);

  if (!siteId || error) return null;
  if (loading && !data) {
    return (
      <Card className="mb-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    );
  }
  if (!data || data.visitors === 0) return null;

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Funnel</CardTitle>
        <CardDescription className="text-xs">
          last {data.window_days} days
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
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
        {!data.reply_tracking_available && (
          <p className="text-xs text-muted-foreground">
            Reply rate &amp; the wedge metric (visitor-reply vs cold) need reply
            tracking — coming next.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
