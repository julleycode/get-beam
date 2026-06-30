"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatGridSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Small spend ($0.01/call) needs more than 2 decimals to stay legible; large
// totals don't. Show 4 dp under a cent, 2 dp otherwise.
function money(n: number): string {
  if (n > 0 && n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

const CATEGORY_LABELS: Record<string, string> = {
  identity: "Identity",
  enrichment: "Enrichment",
  osint: "OSINT",
  email: "Email",
  ai: "AI",
};

export default function CostsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [days, setDays] = useState("30");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["costs", siteId, days],
    queryFn: () => api.getCostSummary(siteId, Number(days)),
    enabled: !!siteId,
  });

  const maxDay = Math.max(0, ...(data?.by_day ?? []).map((d) => d.cost_usd));
  const successRate =
    data && data.total_calls > 0
      ? Math.round((data.success_calls / data.total_calls) * 100)
      : 0;
  const coverage = data?.identity_coverage;
  const coveragePct = coverage
    ? Math.round(coverage.coverage_rate * 100)
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-serif font-semibold tracking-tight">
            API Costs
          </h2>
          <p className="text-sm text-muted-foreground">
            Estimated spend on paid API calls — identity, enrichment & OSINT.
            Email & AI are on free tiers and not tracked yet.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
            </SelectContent>
          </Select>
          <SiteSelector value={siteId} onChange={setSiteId} />
        </div>
      </div>

      {!siteId ? (
        <p className="text-sm text-muted-foreground">
          Select a site to see its API spend.
        </p>
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load costs — ${
            error instanceof Error ? error.message : "unknown error"
          }`}
          onRetry={() => refetch()}
        />
      ) : isLoading || !data ? (
        <StatGridSkeleton cols={4} />
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Owned coverage</CardDescription>
                <CardTitle className="text-3xl text-success">
                  {coveragePct}%
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {coverage?.owned_calls ?? 0} free from your data ·{" "}
                  {coverage?.paid_calls ?? 0} paid
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Total spend (est.)</CardDescription>
                <CardTitle className="text-3xl">
                  {money(data.total_usd)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  over the last {data.days} days
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>API calls</CardDescription>
                <CardTitle className="text-3xl">{data.total_calls}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {data.success_calls} ok · {data.failed_calls} failed
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Success rate</CardDescription>
                <CardTitle className="text-3xl">{successRate}%</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  failed calls usually cost $0
                </p>
              </CardContent>
            </Card>
          </div>

          {data.total_calls === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                No API spend recorded in this window. Identity resolution writes
                a cost row per provider call — run an identify to see data here.
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Spend by category */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">By category</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-3">
                    {data.by_category.map((c) => (
                      <div
                        key={c.category}
                        className="flex-1 min-w-[120px] rounded-lg border border-[rgba(43,37,48,0.08)] p-3"
                      >
                        <p className="text-xs uppercase tracking-wider text-muted-foreground">
                          {CATEGORY_LABELS[c.category] ?? c.category}
                        </p>
                        <p className="text-xl font-semibold">{money(c.cost_usd)}</p>
                        <p className="text-xs text-muted-foreground">
                          {c.calls} call{c.calls === 1 ? "" : "s"}
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Spend by day */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Spend by day</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex items-end gap-1 h-40">
                    {data.by_day.map((d) => (
                      <div
                        key={d.date}
                        className="flex-1 flex flex-col items-center justify-end group"
                        title={`${d.date}: ${money(d.cost_usd)} (${d.calls} calls)`}
                      >
                        <div
                          className="w-full rounded-t bg-[hsl(345,100%,60%)] min-h-[2px] transition-all group-hover:opacity-80"
                          style={{
                            height: maxDay
                              ? `${(d.cost_usd / maxDay) * 100}%`
                              : "2px",
                          }}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="flex justify-between mt-2 text-[10px] text-muted-foreground">
                    <span>{data.by_day[0]?.date}</span>
                    <span>{data.by_day[data.by_day.length - 1]?.date}</span>
                  </div>
                </CardContent>
              </Card>

              {/* By provider */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">By provider</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Provider</TableHead>
                        <TableHead className="text-right">Calls</TableHead>
                        <TableHead className="text-right">Success</TableHead>
                        <TableHead className="text-right">Cost (est.)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.by_provider.map((p) => (
                        <TableRow key={p.provider}>
                          <TableCell className="font-medium">
                            {p.provider}
                          </TableCell>
                          <TableCell className="text-right">{p.calls}</TableCell>
                          <TableCell className="text-right">
                            {Math.round(p.success_rate * 100)}%
                          </TableCell>
                          <TableCell className="text-right">
                            {money(p.cost_usd)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
