"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, BillingStatus, SiteStats, Visitor } from "@/lib/api";
import { PipelineExplainer } from "@/components/pipeline-explainer";
import { TableSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const EXPLAINER_DISMISSED_KEY = "beam_pipeline_explainer_dismissed";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

function statusColor(status: string): BadgeVariant {
  switch (status) {
    case "identified": return "default";
    case "enriched": return "default";
    case "anonymous": return "secondary";
    case "merged": return "secondary";
    default: return "outline"; // unresolvable, vpn_filtered, partial, failed, ...
  }
}

function intentColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-yellow-600";
  return "text-muted-foreground";
}

// Column-header help — copy mirrors the real scoring/pipeline rules
// (apps/api/services/visitor_aggregator.py, resolution_runner.py).
const COLUMN_TIPS = {
  visitorId: "Anonymous ID assigned by the Beam pixel. Click to open the full profile.",
  firstSeen: "First tracked visit from this browser.",
  lastSeen: "Most recent activity. Intent decays as this ages.",
  pageviews: "Total pages viewed across all sessions.",
  intent:
    "Likelihood to convert, 0–100. Points for repeat sessions (up to +25), scrolling ≥75% (+15), 60s+ on page (+10), fast return visits (up to +15), reaching pricing/signup pages (up to +15), and referrer quality (up to +10). Scores fade with inactivity — full strength under 24h, down to 0.2× after 90 days. 40+ unlocks identification; 70+ is high intent.",
  identity:
    "anonymous: not yet matched · identified: real email/name found · unresolvable: lookups found nothing (retried after 30 days) · vpn filtered: masked IP, skipped · merged: same person as another visitor. Identification runs automatically at intent 40+.",
  enrichment:
    "pending: waiting on identification · enriched: job, company and socials added · partial: some fields found · failed: enrichment errored. Visitors below intent 40 are never identified, so they show —.",
} as const;

function InfoIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 opacity-50"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  );
}

function HeadWithTip({
  label,
  tip,
  className,
}: {
  label: string;
  tip: string;
  className?: string;
}) {
  return (
    <TableHead className={className}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className="inline-flex cursor-help items-center gap-1">
            {label}
            <InfoIcon />
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{tip}</TooltipContent>
      </Tooltip>
    </TableHead>
  );
}

// Honest enrichment cell: "pending" is misleading for visitors that will
// never be identified (below the intent-40 threshold) or can't be
// (unresolvable / VPN). Show "—" with an explanation instead, and "queued"
// for visitors that are genuinely waiting on the next resolution run.
function enrichmentDisplay(v: Visitor): {
  kind: "badge" | "muted";
  label: string;
  variant: BadgeVariant;
  tip: string | null;
} {
  if (v.identity_status === "anonymous" && v.intent_score < 40) {
    return {
      kind: "muted",
      label: "—",
      variant: "outline",
      tip: "Below the intent-40 identification threshold — enrichment won't run for this visitor.",
    };
  }
  if (v.identity_status === "anonymous") {
    return {
      kind: "badge",
      label: "queued",
      variant: "secondary",
      tip: "Eligible — runs on the next identification sweep, or click Resolve now.",
    };
  }
  if (v.identity_status === "unresolvable") {
    return {
      kind: "muted",
      label: "—",
      variant: "outline",
      tip: "Can't enrich: identity lookups found no match for this visitor.",
    };
  }
  if (v.identity_status === "vpn_filtered") {
    return {
      kind: "muted",
      label: "—",
      variant: "outline",
      tip: "Skipped: VPN/proxy traffic can't be reliably identified.",
    };
  }
  return {
    kind: "badge",
    label: v.enrichment_status,
    variant: statusColor(v.enrichment_status),
    tip: null,
  };
}

function EnrichmentCell({ v }: { v: Visitor }) {
  const d = enrichmentDisplay(v);
  const content =
    d.kind === "muted" ? (
      <span tabIndex={0} className="cursor-help text-muted-foreground">
        {d.label}
      </span>
    ) : (
      <Badge variant={d.variant} tabIndex={d.tip ? 0 : undefined} className={d.tip ? "cursor-help" : undefined}>
        {d.label}
      </Badge>
    );

  if (!d.tip) return content;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent className="max-w-xs">{d.tip}</TooltipContent>
    </Tooltip>
  );
}

export default function VisitorsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [visitors, setVisitors] = useState<Visitor[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("intent_score");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [stats, setStats] = useState<SiteStats | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [showExplainer, setShowExplainer] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [resolveMsg, setResolveMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId) return;
    setLoading(true);
    setError(null);
    api
      .listVisitors(siteId, {
        page,
        page_size: 50,
        identity_status: filter === "all" ? undefined : filter,
        sort_by: sortBy,
      })
      .then((res) => {
        setVisitors(res.visitors);
        setTotal(res.total);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [siteId, page, filter, sortBy, retryKey]);

  // Funnel stats power the explainer's live counts — non-blocking.
  useEffect(() => {
    if (!siteId) {
      setStats(null);
      return;
    }
    api
      .getVisitorStats(siteId)
      .then(setStats)
      .catch(() => setStats(null));
  }, [siteId, retryKey]);

  useEffect(() => {
    api
      .getBillingStatus()
      .then(setBilling)
      .catch(() => setBilling(null));
  }, []);

  useEffect(() => {
    if (!localStorage.getItem(EXPLAINER_DISMISSED_KEY)) {
      setShowExplainer(true);
    }
  }, []);

  function dismissExplainer() {
    localStorage.setItem(EXPLAINER_DISMISSED_KEY, "1");
    setShowExplainer(false);
  }

  async function handleResolve() {
    if (!siteId) return;
    setResolving(true);
    setResolveMsg(null);
    try {
      const res = await api.resolveSiteVisitors(siteId);
      setResolveMsg(res.message);
      if (res.status === "started") {
        setTimeout(() => setRetryKey((k) => k + 1), 3000);
      }
    } catch (e) {
      setResolveMsg(e instanceof Error ? e.message : "Couldn't start identification.");
    } finally {
      setResolving(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Visitors</h2>
        <div className="flex items-center gap-3">
          <SiteSelector value={siteId} onChange={setSiteId} />
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All status</SelectItem>
              <SelectItem value="anonymous">Anonymous</SelectItem>
              <SelectItem value="identified">Identified</SelectItem>
              <SelectItem value="enriched">Enriched</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sortBy} onValueChange={setSortBy}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="intent_score">Intent score</SelectItem>
              <SelectItem value="last_seen">Last seen</SelectItem>
              <SelectItem value="pageviews">Pageviews</SelectItem>
            </SelectContent>
          </Select>
          {siteId && (
            <Button size="sm" onClick={handleResolve} disabled={resolving}>
              {resolving ? "Resolving..." : "Resolve now"}
            </Button>
          )}
        </div>
      </div>

      {showExplainer && (
        <PipelineExplainer stats={siteId ? stats : null} billing={billing} onDismiss={dismissExplainer} />
      )}

      {resolveMsg && <p className="mb-3 text-sm text-muted-foreground">{resolveMsg}</p>}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view visitors.</p>
      ) : loading ? (
        <TableSkeleton cols={7} rows={10} />
      ) : error ? (
        <ErrorBanner
          message={`Couldn't load visitors — ${error}`}
          onRetry={() => setRetryKey((k) => k + 1)}
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground mb-3">
            {total} visitor{total !== 1 ? "s" : ""}
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <HeadWithTip label="Visitor ID" tip={COLUMN_TIPS.visitorId} />
                <HeadWithTip label="First seen" tip={COLUMN_TIPS.firstSeen} />
                <HeadWithTip label="Last seen" tip={COLUMN_TIPS.lastSeen} />
                <HeadWithTip label="Pageviews" tip={COLUMN_TIPS.pageviews} className="text-right" />
                <HeadWithTip label="Intent" tip={COLUMN_TIPS.intent} className="text-right" />
                <HeadWithTip label="Identity" tip={COLUMN_TIPS.identity} />
                <HeadWithTip label="Enrichment" tip={COLUMN_TIPS.enrichment} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visitors.map((v) => (
                <TableRow key={v.id}>
                  <TableCell>
                    <Link
                      href={`/dashboard/visitors/${v.visitor_id}?site=${siteId}`}
                      className="font-mono text-xs hover:underline"
                    >
                      {v.visitor_id.slice(0, 12)}...
                    </Link>
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.first_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.last_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-right">{v.total_pageviews}</TableCell>
                  <TableCell className={`text-right font-medium ${intentColor(v.intent_score)}`}>
                    {Math.round(v.intent_score)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusColor(v.identity_status)}>
                      {v.identity_status.replace(/_/g, " ")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <EnrichmentCell v={v} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {total > 50 && (
            <div className="flex justify-center gap-2 mt-4">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground self-center">
                Page {page} of {Math.ceil(total / 50)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= Math.ceil(total / 50)}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
