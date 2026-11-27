"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { ContentOpportunity, ContentOpportunityKind } from "@/lib/api-types";
import { TableSkeleton } from "@/components/skeletons";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const KIND_LABEL: Record<ContentOpportunityKind, string> = {
  page_title: "Page title",
  faq: "FAQ entry",
  llms_txt: "llms.txt line",
};

function isFlagOff(err: unknown): boolean {
  return err instanceof Error && err.message === "Not found";
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function copyText(o: ContentOpportunity): string {
  return o.body ? `${o.title}\n\n${o.body}` : o.title;
}

export default function ContentOpportunitiesPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [notice, setNotice] = useState("");
  const qc = useQueryClient();

  const topAds = useQuery({
    queryKey: ["ad-insights-top", siteId],
    queryFn: () => api.getTopAds(siteId),
    enabled: !!siteId,
    retry: false,
  });
  const opps = useQuery({
    queryKey: ["ad-insights-opps", siteId],
    queryFn: () => api.listContentOpportunities(siteId),
    enabled: !!siteId,
    retry: false,
  });

  const setStatus = useMutation({
    mutationFn: (v: { id: string; status: "dismissed" | "copied" }) =>
      api.setContentOpportunityStatus(siteId, v.id, v.status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ad-insights-opps", siteId] }),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshAdInsights(siteId),
    onSuccess: () => {
      setNotice("Refreshing in the background — check back in a minute.");
      qc.invalidateQueries({ queryKey: ["ad-insights-top", siteId] });
      qc.invalidateQueries({ queryKey: ["ad-insights-opps", siteId] });
    },
    onError: () => setNotice("Refresh is limited to once per day per site."),
  });

  const onCopy = async (o: ContentOpportunity) => {
    try {
      await navigator.clipboard.writeText(copyText(o));
      setNotice("Copied. Nothing was published — paste it where you want it.");
    } catch {
      setNotice("Could not copy — select the text and copy it manually.");
    }
    setStatus.mutate({ id: o.id, status: "copied" });
  };

  const top = topAds.data;

  return (
    <div className="space-y-6" data-testid="content-opportunities-page">
      <PageHeader
        title="Content Ideas"
        actions={
          <div className="flex items-center gap-3">
            {siteId && (
              <Button
                variant="outline"
                size="sm"
                disabled={refresh.isPending}
                onClick={() => refresh.mutate()}
              >
                Refresh
              </Button>
            )}
            <SiteSelector value={siteId} onChange={setSiteId} />
          </div>
        }
      />

      <p className="text-sm text-muted-foreground" data-testid="suggestions-only-note">
        Suggestions only — nothing is published. Beam reads your best-performing ads and the
        pages AI assistants fetch, then drafts page titles, FAQ entries and llms.txt lines you can
        copy.
      </p>
      {notice && (
        <p className="text-sm" role="status">
          {notice}
        </p>
      )}

      {!siteId ? (
        <EmptyState
          icon={Sparkles}
          title="Pick a site"
          description="Choose a site to see content ideas drawn from your winning ads."
        />
      ) : topAds.isLoading ? (
        <TableSkeleton cols={6} />
      ) : topAds.isError && isFlagOff(topAds.error) ? (
        <EmptyState
          icon={Sparkles}
          title="Content ideas are not enabled"
          description="This view is turned off on this deployment."
        />
      ) : topAds.isError ? (
        <EmptyState
          icon={Sparkles}
          title="Could not load ad insights"
          description="Please try again in a moment."
        />
      ) : !top || !top.enough_data ? (
        <EmptyState
          icon={Sparkles}
          title="Not enough ad data yet"
          description={`Content ideas need at least ${top?.min_qualifying_ads ?? 3} ads with ${
            top?.min_impressions ?? 500
          }+ impressions from a connected Meta or Google Ads account.`}
        />
      ) : (
        <>
          <section className="space-y-2">
            <h2 className="text-base font-semibold">Top ads</h2>
            <Table data-testid="top-ads-table">
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Headline</TableHead>
                  <TableHead>Platform</TableHead>
                  <TableHead className="text-right">Impressions</TableHead>
                  <TableHead className="text-right">CTR</TableHead>
                  <TableHead className="text-right">Conv. rate</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {top.ads.map((a) => (
                  <TableRow key={`${a.provider}:${a.platform_ad_id}`}>
                    <TableCell>{a.rank}</TableCell>
                    <TableCell className="max-w-md truncate">{a.headline || a.platform_ad_id}</TableCell>
                    <TableCell className="capitalize">{a.provider}</TableCell>
                    <TableCell className="text-right">{a.impressions.toLocaleString()}</TableCell>
                    <TableCell className="text-right">{pct(a.ctr)}</TableCell>
                    <TableCell className="text-right">{pct(a.conv_rate)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>

          <section className="space-y-3" data-testid="opportunities-list">
            <h2 className="text-base font-semibold">Suggestions</h2>
            {opps.isLoading ? (
              <TableSkeleton cols={3} />
            ) : !opps.data || opps.data.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No suggestions yet — they are drafted once a day.
              </p>
            ) : (
              opps.data.map((o) => (
                <div key={o.id} className="rounded-md border p-4 space-y-2" data-testid="opportunity-card">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs uppercase text-muted-foreground">
                      {KIND_LABEL[o.kind]}
                      {o.status === "copied" ? " · copied" : ""}
                    </span>
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => onCopy(o)}>
                        Copy
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setStatus.mutate({ id: o.id, status: "dismissed" })}
                      >
                        Dismiss
                      </Button>
                    </div>
                  </div>
                  {/* Model output rendered as plain text only (E5). */}
                  <p className="font-medium">{o.title}</p>
                  {o.body && <p className="text-sm whitespace-pre-wrap">{o.body}</p>}
                  {o.rationale && <p className="text-xs text-muted-foreground">Why: {o.rationale}</p>}
                  {o.source_ad_ids.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Based on ads: {o.source_ad_ids.join(", ")}
                    </p>
                  )}
                </div>
              ))
            )}
          </section>
        </>
      )}
    </div>
  );
}
