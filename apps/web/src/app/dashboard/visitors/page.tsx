"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { aiSourceLabel } from "@/lib/ai-sources";
import { SlidersHorizontal, SearchX, Target, ChevronDown } from "lucide-react";
import { TableSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { EmptyState } from "@/components/empty-state";
import { SiteSelector } from "@/components/site-selector";
import { VisitorWidgets } from "@/components/visitor-widgets";
import { type Period } from "@/components/ui/period-toggle";
import { PageHeader } from "@/components/page-header";
import { VisitorsHelp } from "@/components/page-help";
import { UsageWarningBanner } from "@/components/usage-warning-banner";
import { UpgradeModal } from "@/components/upgrade-modal";
import { useBillingStatus } from "@/lib/use-billing";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { IntentScoreInfo } from "@/components/intent-score-info";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function intentColor(score: number): string {
  if (score >= 70) return "text-intent-high";
  if (score >= 40) return "text-warning";
  return "text-muted-foreground";
}

// A calm on/off toggle for the toolbar: always an outline button, state shown
// by a leading status dot (green = on) rather than a loud filled fill. Keeps
// the two automation toggles visible without them shouting over the filters.
function ToggleChip({
  label,
  on,
  pending,
  onToggle,
  title,
}: {
  label: string;
  on: boolean;
  pending: boolean;
  onToggle: () => void;
  title: string;
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={pending}
      onClick={onToggle}
      title={title}
      aria-pressed={on}
    >
      <span
        className={`mr-1.5 h-2 w-2 rounded-full ${on ? "bg-success" : "bg-muted-foreground/40"}`}
      />
      {label}
    </Button>
  );
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

// "YYYY-MM-DD" strings sort chronologically as plain strings, so min/max over a
// few date bounds is a sort. Empty values are ignored. Used to intertwine the
// First-seen and Last-seen pickers (a visitor's last_seen is always >= its
// first_seen, so the two ranges constrain each other).
const earliest = (...ds: string[]): string | undefined =>
  ds.filter(Boolean).sort()[0] || undefined;
const latest = (...ds: string[]): string | undefined =>
  ds.filter(Boolean).sort().at(-1) || undefined;

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
  // "all" | "__any__" | a concrete ai_source label — AI-referral Source facet.
  // Attribution-only; never affects emailability.
  const [source, setSource] = useState("all");
  // Filters panel starts collapsed to keep the page calm; opens on demand.
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Shared Last 30 days / Lifetime window: drives the insight widgets AND the
  // visitor list below. A view window, not a filter chip — it's deliberately
  // excluded from hasFilters / clearFilters.
  const [period, setPeriod] = useState<Period>("30d");

  // The list's cutoff implied by the period toggle, in the same "YYYY-MM-DD"
  // shape the date pickers produce. Lifetime means no cutoff.
  const implicitLastFrom =
    period === "30d"
      ? new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)
      : undefined;

  // Filters shared by the list AND the country facet, so the dropdown counts
  // reflect the same predicates as the rows. The country filter is NOT in here
  // on purpose — a facet must not constrain its own counts (faceted search).
  // "enriched" is an enrichment_status, not an identity_status — route it to the
  // right param (the old code sent identity_status=enriched, which matched
  // nothing).
  const facetParams = {
    visitor_type: visitorType === "all" ? undefined : visitorType,
    known: knownFilter === "all" ? undefined : knownFilter === "known",
    identity_status:
      filter === "all" || filter === "enriched" ? undefined : filter,
    enrichment_status: filter === "enriched" ? "enriched" : undefined,
    first_seen_from: firstFrom || undefined,
    first_seen_to: firstTo ? nextDay(firstTo) : undefined,
    // A manual Last-seen-from filter always wins over the period toggle.
    last_seen_from: lastFrom || implicitLastFrom,
    last_seen_to: lastTo ? nextDay(lastTo) : undefined,
  };

  // Logically-impossible date windows (e.g. last-seen-end before first-seen-start,
  // or a from after its own to). A visitor's last_seen is always >= first_seen,
  // so such combinations can only ever return zero rows — warn instead of
  // silently showing an empty table.
  const dateWarning =
    (firstFrom && firstTo && firstFrom > firstTo) ||
    (lastFrom && lastTo && lastFrom > lastTo)
      ? "Start date is after end date. No visitors match."
      : firstFrom && lastTo && lastTo < firstFrom
        ? "“Last seen to” is before “First seen from” — impossible (last seen is always after first seen)."
        : null;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [
      "visitors", siteId, page, filter, sortBy,
      firstFrom, firstTo, lastFrom, lastTo, country, visitorType, knownFilter, source,
      period,
    ],
    queryFn: () =>
      api.listVisitors(siteId, {
        ...facetParams,
        page,
        page_size: 50,
        country: country === "all" ? undefined : country,
        ai_source: source === "all" ? undefined : source,
        sort_by: sortBy,
      }),
    enabled: !!siteId,
  });

  // Country options (with per-country counts) for the filter dropdown — faceted
  // by every other active filter (keyed on facetParams so it refetches).
  const { data: countries } = useQuery({
    queryKey: ["visitor-countries", siteId, facetParams],
    queryFn: () => api.getVisitorCountries(siteId, facetParams),
    enabled: !!siteId,
  });

  // AI-referral Source options (with counts) — faceted like countries. Kept out
  // of facetParams so the facet doesn't self-constrain; country still constrains
  // it (cross-facet) via the explicit pass-through.
  const { data: aiSources } = useQuery({
    queryKey: ["visitor-ai-sources", siteId, facetParams, country],
    queryFn: () =>
      api.getVisitorAiSources(siteId, {
        ...facetParams,
        country: country === "all" ? undefined : country,
      }),
    enabled: !!siteId,
  });

  // Keep the currently-selected country visible even if the faceted counts no
  // longer include it (e.g. a date filter dropped it to zero) — otherwise the
  // Select trigger would render blank and feel stuck. Show it with (0).
  const countryOptions = (() => {
    const list = countries ?? [];
    if (country !== "all" && !list.some((c) => c.country_code === country)) {
      return [...list, { country_code: country, count: 0 }];
    }
    return list;
  })();

  // Keep the selected source visible even if faceted counts dropped it to zero.
  const sourceOptions = (() => {
    const list = aiSources ?? [];
    if (
      source !== "all" &&
      source !== "__any__" &&
      !list.some((s) => s.ai_source === source)
    ) {
      return [...list, { ai_source: source, count: 0 }];
    }
    return list;
  })();

  const activeFilterCount =
    (filter !== "all" ? 1 : 0) +
    (country !== "all" ? 1 : 0) +
    (visitorType !== "all" ? 1 : 0) +
    (knownFilter !== "all" ? 1 : 0) +
    (source !== "all" ? 1 : 0) +
    (firstFrom || firstTo ? 1 : 0) +
    (lastFrom || lastTo ? 1 : 0);
  const hasFilters = activeFilterCount > 0;

  function clearFilters() {
    setFilter("all");
    setCountry("all");
    setVisitorType("all");
    setKnownFilter("all");
    setSource("all");
    setFirstFrom("");
    setFirstTo("");
    setLastFrom("");
    setLastTo("");
    setPage(1);
  }

  // Switching sites must drop the previous site's filters AND reset paging —
  // otherwise e.g. country="US" from the old site (or page 3) carries over and
  // the new site looks empty for no visible reason.
  function handleSiteChange(id: string) {
    setSiteId(id);
    clearFilters();
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
  // Upsell modal: opened only when a hit is the monthly plan limit (upgrading
  // lifts it). Daily caps stay as a plain notice — upgrading doesn't raise them.
  const [upgradeOpen, setUpgradeOpen] = useState(false);
  // Auto-identify should proactively upsell on page entry once the monthly plan
  // limit is already exhausted. Reset per site so each site can show its own
  // limit state once, but don't re-open immediately after the user closes it.
  const [autoPromptSeenForSite, setAutoPromptSeenForSite] = useState<string | null>(null);
  // Which held visitor is awaiting the "Clear privacy hold" confirmation. The
  // clear is a deliberate, confirmed owner action (US-3/AC-3) — never fire it
  // without this gate. null = dialog closed.
  const [pendingClearId, setPendingClearId] = useState<string | null>(null);
  const { data: billing } = useBillingStatus();

  // A resolve/enrich outcome is an upgrade moment only when it's the monthly
  // plan limit. Opens the modal; otherwise surface the message as a notice.
  const handleLimitOutcome = (res: { message?: string | null; limit_kind?: string }) => {
    if (res.limit_kind === "monthly_plan") {
      setUpgradeOpen(true);
    } else if (res.message) {
      setNotice(res.message);
    }
  };

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
      // Surface any explanatory message (limit, privacy opt-out, region
      // coverage). A successful identify shows up visually, so skip only that.
      if (res.status !== "identified") {
        handleLimitOutcome(res);
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
      if (res.status !== "enriched") handleLimitOutcome(res);
    },
    onError: (e) => setNotice(e instanceof Error ? e.message : "Enrich failed"),
    onSettled: refreshRows,
  });

  // Clear a single visitor's sticky privacy hold (do_not_resolve → false) for
  // this site only. Confirmed via the dialog below. onSuccess re-fetches so the
  // row re-renders with the normal Identify control; never bypasses /resolve.
  const clearMut = useMutation({
    mutationFn: (visitorId: string) => api.clearPrivacyHold(siteId, visitorId),
    onMutate: (visitorId) => {
      setActioningId(visitorId);
      setNotice(null);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["visitors"] });
      setNotice("Privacy hold cleared for this visitor on this site.");
    },
    onError: (e) =>
      setNotice(e instanceof Error ? e.message : "Couldn't clear the privacy hold"),
    onSettled: () => {
      setActioningId(null);
      setPendingClearId(null);
    },
  });

  const autoMut = useMutation({
    mutationFn: (enabled: boolean) => api.setAutoIdentify(siteId, enabled),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["site", siteId] }),
  });

  const hotMut = useMutation({
    mutationFn: (enabled: boolean) => api.setHotAlert(siteId, enabled),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["site", siteId] }),
  });

  useEffect(() => {
    if (!siteId) {
      setAutoPromptSeenForSite(null);
      return;
    }

    const limit = billing?.monthly_limit;
    const used = billing?.monthly_identified_count ?? 0;
    const autoEnabled = !!site?.auto_identify_enabled;
    const exhausted = limit !== null && limit !== undefined && used >= limit;

    if (autoEnabled && exhausted && autoPromptSeenForSite !== siteId) {
      setUpgradeOpen(true);
      setAutoPromptSeenForSite(siteId);
    }
  }, [
    autoPromptSeenForSite,
    billing?.monthly_identified_count,
    billing?.monthly_limit,
    site?.auto_identify_enabled,
    siteId,
  ]);

  function renderIdentity(v: (typeof visitors)[number]) {
    const s = v.identity_status;
    if (s === "verified" || s === "identified") {
      return <StatusBadge status="verified" label="Verified" />;
    }
    if (s === "provider_candidate") {
      return <StatusBadge status="provider_candidate" label="Candidate" />;
    }
    if (s === "candidate") {
      // Identity-honesty Phase 1: an UNCONFIRMED identity-graph match. Placed
      // here (the status column) rather than as an extra pill in the name
      // cluster because "candidate" IS a status value, not an orthogonal
      // attribute like Known / Company-level. The confidence lives in the
      // tooltip so the row stays scannable.
      return (
        <span
          title={`Unconfirmed match${
            typeof v.confidence_score === "number"
              ? ` — ${Math.round(v.confidence_score * 100)}% confidence`
              : ""
          }. Not personalized in outreach until confirmed.`}
        >
          <StatusBadge status="candidate" label="Candidate" />
        </span>
      );
    }
    if (s === "merged") {
      // Deduped duplicate of another visitor — same person. The identity lives
      // on the canonical profile; the API surfaces its email here too.
      return <StatusBadge status="merged" label="Merged" className="opacity-80" />;
    }
    if (s === "vpn_filtered") {
      return (
        <StatusBadge status={s} label="Privacy relay / VPN" className="opacity-60" />
      );
    }
    if (s === "unresolvable") {
      // Retryable: a prior attempt may have failed during a provider outage.
      const retrying = resolveMut.isPending && actioningId === v.visitor_id;
      return (
        <div className="flex items-center gap-2">
          <StatusBadge status={s} label={s.replace("_", " ")} className="opacity-60" />
          <Button
            size="sm"
            variant="outline"
            disabled={retrying}
            onClick={() => resolveMut.mutate(v.visitor_id)}
          >
            {retrying ? "Retrying…" : "Retry"}
          </Button>
        </div>
      );
    }
    // Privacy hold: the visitor sent a privacy signal (GPC/DNT) or was cascaded
    // from a suppression opt-out, so do_not_resolve is sticky. This is a POLICY
    // block, not a usage limit (US-1) — show it plainly and offer a deliberate,
    // confirmed owner Clear (AC-1/AC-2) instead of a dead-end Identify button.
    if (v.identity_status === "anonymous" && v.do_not_resolve) {
      const clearing = clearMut.isPending && actioningId === v.visitor_id;
      return (
        <div className="flex flex-col items-start gap-1">
          <div className="flex items-center gap-2">
            <StatusBadge status="vpn_filtered" label="Privacy hold" className="opacity-80" />
            <Button
              size="sm"
              variant="outline"
              disabled={clearing}
              onClick={() => setPendingClearId(v.visitor_id)}
            >
              {clearing ? "Clearing…" : "Clear privacy hold"}
            </Button>
          </div>
          <span className="text-xs text-muted-foreground">
            Opted out of identification (privacy signal) — a policy block, not a
            usage limit.
          </span>
        </div>
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
    const idOk =
      v.identity_status === "verified" ||
      v.identity_status === "identified" ||
      v.identity_status === "provider_candidate" ||
      v.identity_status === "merged";
    // Can't enrich an anonymous / unresolvable visitor — dim + disabled.
    if (!idOk) {
      return <span className="text-xs text-muted-foreground opacity-50">—</span>;
    }
    if (v.enrichment_status === "enriched") {
      return <StatusBadge status="enriched" label="Enriched" />;
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
      <PageHeader
        title="Visitors"
        info={<VisitorsHelp />}
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <SiteSelector value={siteId} onChange={handleSiteChange} />
            {siteId && (
              <Button asChild variant="outline" size="sm">
                <Link href={`/dashboard/outcomes?site=${siteId}`}>
                  <Target className="mr-1.5 h-4 w-4" />
                  Outcomes
                </Link>
              </Button>
            )}
            {siteId && site && (
              <ToggleChip
                label="Auto-identify"
                on={!!site.auto_identify_enabled}
                pending={autoMut.isPending}
                onToggle={() => autoMut.mutate(!site.auto_identify_enabled)}
                title="On = auto-identify high-intent visitors. Off = click Identify per visitor."
              />
            )}
            {siteId && site && (
              <ToggleChip
                label="Hot alerts"
                on={!!site.hot_alert_enabled}
                pending={hotMut.isPending}
                onToggle={() => hotMut.mutate(!site.hot_alert_enabled)}
                title="On = email alert when a high-intent US visitor is identified."
              />
            )}
            <Select value={filter} onValueChange={(v) => { setFilter(v); setPage(1); }}>
              <SelectTrigger className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All status</SelectItem>
                <SelectItem value="anonymous">Anonymous</SelectItem>
                <SelectItem value="identified">Verified</SelectItem>
                <SelectItem value="provider_candidate">Candidate</SelectItem>
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
        }
      />

      <div className="mb-4">
        <UsageWarningBanner />
      </div>

      {siteId && (
        <VisitorWidgets
          siteId={siteId}
          period={period}
          onPeriodChange={(p) => { setPeriod(p); setPage(1); }}
        />
      )}

      {siteId && (
        <div className="mb-4 rounded-lg border bg-muted/30">
          <button
            type="button"
            onClick={() => setFiltersOpen((o) => !o)}
            aria-expanded={filtersOpen}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Filters
            {activeFilterCount > 0 && (
              <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium normal-case text-primary">
                {activeFilterCount} active
              </span>
            )}
            <ChevronDown
              className={`ml-auto h-4 w-4 transition-transform ${filtersOpen ? "rotate-180" : ""}`}
            />
          </button>
          {filtersOpen && (
            <div className="flex flex-wrap items-end gap-4 border-t p-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">First seen</label>
            <div className="flex items-center gap-1">
              <input
                type="date"
                value={firstFrom}
                max={earliest(firstTo, lastTo)}
                onChange={(e) => { setFirstFrom(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
              <span className="text-xs text-muted-foreground">→</span>
              <input
                type="date"
                value={firstTo}
                min={firstFrom || undefined}
                max={lastTo || undefined}
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
                min={firstFrom || undefined}
                max={lastTo || undefined}
                onChange={(e) => { setLastFrom(e.target.value); setPage(1); }}
                className="h-9 rounded-md border bg-background px-2 text-sm"
              />
              <span className="text-xs text-muted-foreground">→</span>
              <input
                type="date"
                value={lastTo}
                min={latest(lastFrom, firstFrom)}
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
                {countryOptions.map((c) => (
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
              title="By number of visits Beam has seen, not whether they're in your CRM."
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
          <div className="flex flex-col gap-1">
            <label
              className="text-xs font-medium text-muted-foreground"
              title="Which AI answer engine referred this visitor (ChatGPT, Perplexity, …). Attribution only."
            >
              Source
            </label>
            <Select value={source} onValueChange={(v) => { setSource(v); setPage(1); }}>
              <SelectTrigger className="h-9 w-[170px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="__any__">Any AI referral</SelectItem>
                {sourceOptions.map((s) => (
                  <SelectItem key={s.ai_source} value={s.ai_source}>
                    {aiSourceLabel(s.ai_source)} ({s.count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
          {dateWarning && (
            <p className="w-full text-xs font-medium text-warning">{dateWarning}</p>
          )}
            </div>
          )}
        </div>
      )}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view visitors.</p>
      ) : isLoading ? (
        <TableSkeleton cols={7} rows={10} />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load visitors: ${error instanceof Error ? error.message : "unknown error"}`}
          onRetry={() => refetch()}
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground mb-3">
            {total} visitor{total !== 1 ? "s" : ""}
          </p>
          {notice && (
            <p className="mb-3 text-sm text-warning">{notice}</p>
          )}
          {visitors.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title={hasFilters ? "No visitors match your filters" : "No visitors yet"}
              description={
                hasFilters
                  ? "Try widening the date range or removing some filters."
                  : "Once the pixel records a visit, visitors will show up here."
              }
              action={
                hasFilters ? (
                  <Button variant="outline" size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          ) : (
          <div className="overflow-hidden rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Visitor ID</TableHead>
                <TableHead>First seen</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead className="text-right">Pageviews</TableHead>
                <TableHead className="text-right">
                  <span className="inline-flex items-center justify-end gap-1">
                    Intent
                    <InfoTooltip
                      label="How intent score is calculated"
                      side="bottom"
                      align="end"
                    >
                      <IntentScoreInfo />
                    </InfoTooltip>
                  </span>
                </TableHead>
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
                          className="shrink-0 rounded bg-info-muted px-1.5 py-0.5 text-[10px] font-medium text-info"
                          title={`Returning: ${v.total_sessions} visits Beam has seen (not your CRM)`}
                        >
                          Returning
                        </span>
                      )}
                      {v.ai_source && (
                        <span
                          className="shrink-0 rounded bg-info-muted px-1.5 py-0.5 text-[10px] font-medium text-info"
                          title={`Arrived via ${aiSourceLabel(v.ai_source)}, from an AI answer-engine citation`}
                        >
                          via {aiSourceLabel(v.ai_source)}
                        </span>
                      )}
                      {v.is_bot_suspect && (
                        <span
                          className="shrink-0 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning"
                          title="Bot-suspect: cron-like visit cadence and pageview-only sessions. Visibility signal only: still fully contactable and fully counted."
                        >
                          Bot-suspect
                        </span>
                      )}
                      {v.is_agent_operated && (
                        <span
                          className="shrink-0 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning"
                          title="Agent-operated: this session behaved like it was driven by an AI agent or browser automation. Visibility signal only: still fully contactable and fully counted."
                        >
                          Agent-operated
                        </span>
                      )}
                      {v.is_internal_suspect && (
                        <span
                          className="shrink-0 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning"
                          title="Unusually high activity for this site. Is this you? This visitor's traffic volume is a statistical outlier. A suggestion to review, not a verdict: open the visitor to confirm. Until then they stay fully contactable and fully counted."
                        >
                          High activity?
                        </span>
                      )}
                      {v.handoff_confidence && (
                        <span
                          className="shrink-0 rounded bg-info-muted px-1.5 py-0.5 text-[10px] font-medium text-info"
                          title={`Likely the human behind recent AI-agent research. ${v.handoff_confidence} confidence. Correlated signal, not a certainty.`}
                        >
                          AI research
                        </span>
                      )}
                      {v.is_known && (
                        <span
                          className="shrink-0 rounded bg-success-muted px-1.5 py-0.5 text-[10px] font-medium text-success"
                          title="In your uploaded known-contacts list"
                        >
                          Known
                        </span>
                      )}
                      {v.identity_level === "company" && (
                        <span
                          className="shrink-0 rounded bg-warning-muted px-1.5 py-0.5 text-[10px] font-medium text-warning"
                          title="Company-level guess: matched to this company via IP, then an employee was inferred. This is likely NOT the actual visitor, so don't email them."
                        >
                          Company-level
                        </span>
                      )}
                    </div>
                    {v.conviction && (
                      <div
                        className="mt-1 text-xs text-muted-foreground"
                        title="Why this visitor is worth reaching out to"
                      >
                        {v.conviction}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.first_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-sm">
                    {new Date(v.last_seen).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-right">{v.total_pageviews}</TableCell>
                  <TableCell className={`text-right font-mono font-medium tabular-nums ${intentColor(v.intent_score)}`}>
                    {Math.round(v.intent_score)}
                  </TableCell>
                  <TableCell>{renderIdentity(v)}</TableCell>
                  <TableCell>{renderEnrichment(v)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
          )}

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

      <UpgradeModal
        open={upgradeOpen}
        onOpenChange={setUpgradeOpen}
        currentPlan={billing?.plan ?? "free"}
        reason="You've hit your plan's monthly identification limit."
      />

      {/* Confirm dialog for clearing a sticky privacy hold. Deliberate,
          site-scoped, non-un-suppressing (US-3/AC-3/AC-13). Cancel = no write. */}
      <Dialog
        open={pendingClearId !== null}
        onOpenChange={(open) => {
          if (!open) setPendingClearId(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear this visitor&apos;s privacy hold?</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 text-sm text-muted-foreground">
                <p>
                  This is a deliberate action. It lifts the privacy hold for{" "}
                  <span className="font-medium">this visitor on this site only</span>,
                  so you can try to identify them through the normal flow.
                </p>
                <p>
                  It does <span className="font-medium">not</span> remove this person
                  from any suppression / do-not-process list, and it does not identify
                  them by itself.
                </p>
                <p>
                  If their browser later sends another opt-out signal, the privacy hold
                  may return automatically.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingClearId(null)}>
              Cancel
            </Button>
            <Button
              disabled={clearMut.isPending}
              onClick={() => {
                if (pendingClearId) clearMut.mutate(pendingClearId);
              }}
            >
              {clearMut.isPending ? "Clearing…" : "Clear privacy hold"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
