"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { BrowserCaptureCard } from "@/components/browser-capture-card";
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

function intentColor(score: number): string {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-yellow-600";
  return "text-muted-foreground";
}

// "YYYY-MM-DD" → next calendar day, computed in UTC so a +07 browser tz can't
// shift the date. Used to make the date range's upper bound inclusive of the
// chosen end day (backend filters first/last_seen < this value).
function nextDay(d: string): string {
  const [y, m, day] = d.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, day));
  dt.setUTCDate(dt.getUTCDate() + 1);
  return dt.toISOString().slice(0, 10);
}

export default function VisitorsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("intent_score");
  // Filter panel (Phase 01): date ranges by first/last seen + country.
  const [firstFrom, setFirstFrom] = useState("");
  const [firstTo, setFirstTo] = useState("");
  const [lastFrom, setLastFrom] = useState("");
  const [lastTo, setLastTo] = useState("");
  const [country, setCountry] = useState("all");
  // "all" | "new" | "returning" — Beam's own visit signal (session count).
  const [visitorType, setVisitorType] = useState("all");
  // "all" | "known" | "unknown" — match against the owner's known-contacts list.
  const [knownFilter, setKnownFilter] = useState("all");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [
      "visitors", siteId, page, filter, sortBy,
      firstFrom, firstTo, lastFrom, lastTo, country, visitorType, knownFilter,
    ],
    queryFn: () =>
      api.listVisitors(siteId, {
        page,
        page_size: 50,
        visitor_type: visitorType === "all" ? undefined : visitorType,
        known: knownFilter === "all" ? undefined : knownFilter === "known",
        // "enriched" is an enrichment_status, not an identity_status — route it
        // to the right param (the old code sent identity_status=enriched, which
        // matched nothing).
        identity_status:
          filter === "all" || filter === "enriched" ? undefined : filter,
        enrichment_status: filter === "enriched" ? "enriched" : undefined,
        country: country === "all" ? undefined : country,
        first_seen_from: firstFrom || undefined,
        first_seen_to: firstTo ? nextDay(firstTo) : undefined,
        last_seen_from: lastFrom || undefined,
        last_seen_to: lastTo ? nextDay(lastTo) : undefined,
        sort_by: sortBy,
      }),
    enabled: !!siteId,
  });

  // Country options (with per-country counts) for the filter dropdown.
  const { data: countries } = useQuery({
    queryKey: ["visitor-countries", siteId],
    queryFn: () => api.getVisitorCountries(siteId),
    enabled: !!siteId,
  });

  const hasFilters =
    filter !== "all" ||
    country !== "all" ||
    visitorType !== "all" ||
    knownFilter !== "all" ||
    !!(firstFrom || firstTo || lastFrom || lastTo);

  function clearFilters() {
    setFilter("all");
    setCountry("all");
    setVisitorType("all");
    setKnownFilter("all");
    setFirstFrom("");
    setFirstTo("");
    setLastFrom("");
    setLastTo("");
    setPage(1);
  }

  const { data: site } = useQuery({
    queryKey: ["site", siteId],
    queryFn: () => api.getSite(siteId),
    enabled: !!siteId,
  });

  const visitors = data?.visitors ?? [];
  const total = data?.total ?? 0;

  const queryClient = useQueryClient();
  // Which visitor row currently has an action in flight (per-row spinner).
  const [actioningId, setActioningId] = useState<string | null>(null);
  // Transient notice for non-visual outcomes (limit reached, skipped, error).
  const [notice, setNotice] = useState<string | null>(null);

  const refreshRows = () => {
    setActioningId(null);
    queryClient.invalidateQueries({ queryKey: ["visitors"] });
  };

  const resolveMut = useMutation({
    mutationFn: (visitorId: string) => api.resolveVisitor(siteId, visitorId),
    onMutate: (visitorId) => {
      setActioningId(visitorId);
      setNotice(null);
    },
    onSuccess: (res) => {
      // identified/unresolvable show up visually; only surface the rest.
      if (res.status === "limit_reached" || res.status === "anonymous") {
        setNotice(res.message ?? null);
      }
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : "Identify failed"),
    onSettled: refreshRows,
  });

  const enrichMut = useMutation({
    mutationFn: (visitorId: string) => api.enrichVisitor(siteId, visitorId),
    onMutate: (visitorId) => {
      setActioningId(visitorId);
      setNotice(null);
    },
    onSuccess: (res) => {
      if (res.status !== "enriched") setNotice(res.message ?? null);
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : "Enrich failed"),
    onSettled: refreshRows,
  });

  const autoMut = useMutation({
    mutationFn: (enabled: boolean) => api.setAutoIdentify(siteId, enabled),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["site", siteId] }),
  });

  function renderIdentity(v: (typeof visitors)[number]) {
    const s = v.identity_status;
    if (s === "identified" || s === "merged") {
      return (
        <Badge className="border-transparent bg-green-600 text-white hover:bg-green-600">
          Identified
        </Badge>
      );
    }
    if (s === "unresolvable" || s === "vpn_filtered") {
      return (
        <Badge variant="outline" className="capitalize opacity-50">
          {s.replace("_", " ")}
        </Badge>
      );
    }
    const busy = resolveMut.isPending && actioningId === v.visitor_id;
    return (
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => resolveMut.mutate(v.visitor_id)}
      >
        {busy ? "Identifying…" : "Identify"}
      </Button>
    );
  }

  function renderEnrichment(v: (typeof visitors)[number]) {
    const idOk = v.identity_status === "identified" || v.identity_status === "merged";
    // Can't enrich an anonymous / unresolvable visitor — dim + disabled.
    if (!idOk) {
      return <span className="text-xs text-muted-foreground opacity-50">—</span>;
    }
    if (v.enrichment_status === "enriched") {
      return (
        <Badge className="border-transparent bg-green-600 text-white hover:bg-green-600">
          Enriched
        </Badge>
      );
    }
    const busy = enrichMut.isPending && actioningId === v.visitor_id;
    const label = v.enrichment_status === "failed" ? "Retry enrich" : "Enrich";
    return (
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => enrichMut.mutate(v.visitor_id)}
      >
        {busy ? "Enriching…" : label}
      </Button>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Visitors</h2>
        <div className="flex items-center gap-3">
          <SiteSelector value={siteId} onChange={setSiteId} />
          {siteId && site && (
            <Button
              variant={site.auto_identify_enabled ? "default" : "outline"}
              size="sm"
              disabled={autoMut.isPending}
              onClick={() => autoMut.mutate(!site.auto_identify_enabled)}
              title="On = tự động nhận diện khách intent cao. Off = bấm Identify từng người."
            >
              Auto-identify: {site.auto_identify_enabled ? "On" : "Off"}
            </Button>
          )}
          <Select value={filter} onValueChange={(v) => { setFilter(v); setPage(1); }}>
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
          <Select value={sortBy} onValueChange={(v) => { setSortBy(v); setPage(1); }}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="intent_score">Intent score</SelectItem>
              <SelectItem value="last_seen">Last seen</SelectItem>
              <SelectItem value="pageviews">Pageviews</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {siteId && (
        <div className="mb-4 flex flex-wrap items-end gap-4 rounded-lg border bg-muted/30 p-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">First seen</label>
            <div className="flex items-center gap-1">
              <input
                type="date"
                value={firstFrom}
                max={firstTo || undefined}
                onChange={(e) => { setFirstFrom(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
              <span className="text-xs text-muted-foreground">→</span>
              <input
                type="date"
                value={firstTo}
                min={firstFrom || undefined}
                onChange={(e) => { setFirstTo(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">Last seen</label>
            <div className="flex items-center gap-1">
              <input
                type="date"
                value={lastFrom}
                max={lastTo || undefined}
                onChange={(e) => { setLastFrom(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
              <span className="text-xs text-muted-foreground">→</span>
              <input
                type="date"
                value={lastTo}
                min={lastFrom || undefined}
                onChange={(e) => { setLastTo(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">Country</label>
            <Select value={country} onValueChange={(v) => { setCountry(v); setPage(1); }}>
              <SelectTrigger className="h-9 w-[170px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All countries</SelectItem>
                {(countries ?? []).map((c) => (
                  <SelectItem key={c.country_code} value={c.country_code}>
                    {c.country_code} ({c.count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <label
              className="text-xs font-medium text-muted-foreground"
              title="By number of visits Beam has seen — not whether they're in your CRM."
            >
              Visitor type
            </label>
            <Select value={visitorType} onValueChange={(v) => { setVisitorType(v); setPage(1); }}>
              <SelectTrigger className="h-9 w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All visitors</SelectItem>
                <SelectItem value="new">New (1 visit)</SelectItem>
                <SelectItem value="returning">Returning (2+ visits)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <label
              className="text-xs font-medium text-muted-foreground"
              title="Whether this person's email is in the customer list you uploaded under Settings → Known contacts."
            >
              Known
            </label>
            <Select value={knownFilter} onValueChange={(v) => { setKnownFilter(v); setPage(1); }}>
              <SelectTrigger className="h-9 w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Everyone</SelectItem>
                <SelectItem value="known">In my list</SelectItem>
                <SelectItem value="unknown">Not in my list</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>
      )}

      <BrowserCaptureCard siteId={siteId} />

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view visitors.</p>
      ) : isLoading ? (
        <TableSkeleton cols={7} rows={10} />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load visitors — ${error instanceof Error ? error.message : "unknown error"}`}
          onRetry={() => refetch()}
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground mb-3">
            {total} visitor{total !== 1 ? "s" : ""}
          </p>
          {notice && (
            <p className="mb-3 text-sm text-yellow-600">{notice}</p>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Visitor ID</TableHead>
                <TableHead>First seen</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead className="text-right">Pageviews</TableHead>
                <TableHead className="text-right">Intent</TableHead>
                <TableHead>Identity</TableHead>
                <TableHead>Enrichment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visitors.map((v) => (
                <TableRow key={v.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/dashboard/visitors/${v.visitor_id}?site=${siteId}`}
                        className="hover:underline"
                      >
                        {v.email || v.full_name ? (
                          <div className="flex flex-col">
                            <span className="text-sm font-medium">
                              {v.email ?? v.full_name}
                            </span>
                            <span className="font-mono text-xs text-muted-foreground">
                              {v.visitor_id.slice(0, 12)}…
                            </span>
                          </div>
                        ) : (
                          <span className="font-mono text-xs">
                            {v.visitor_id.slice(0, 12)}…
                          </span>
                        )}
                      </Link>
                      {v.total_sessions > 1 && (
                        <span
                          className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700"
                          title={`Returning — ${v.total_sessions} visits Beam has seen (not your CRM)`}
                        >
                          Returning
                        </span>
                      )}
                      {v.is_known && (
                        <span
                          className="shrink-0 rounded bg-purple-50 px-1.5 py-0.5 text-[10px] font-medium text-purple-700"
                          title="In your uploaded known-contacts list"
                        >
                          Known
                        </span>
                      )}
                    </div>
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
                  <TableCell>{renderIdentity(v)}</TableCell>
                  <TableCell>{renderEnrichment(v)}</TableCell>
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
