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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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

        {/* Per-browser table */}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Browser</TableHead>
              <TableHead className="text-right">Captured</TableHead>
              <TableHead className="text-right">Share</TableHead>
              <TableHead className="text-right">Identified</TableHead>
              <TableHead className="text-right">ID rate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.browsers.map((b) => (
              <TableRow key={b.browser}>
                <TableCell className="font-medium">{b.browser}</TableCell>
                <TableCell className="text-right">{b.captured}</TableCell>
                <TableCell className="text-right">{pct(b.share)}</TableCell>
                <TableCell className="text-right">{b.identified}</TableCell>
                <TableCell className="text-right">
                  {pct(b.identification_rate)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
