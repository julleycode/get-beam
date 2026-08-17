"use client";

import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  Briefcase,
  ChevronDown,
  ExternalLink,
  Globe,
  Loader2,
  MapPin,
  MessageSquare,
  Search,
  ShieldAlert,
  Sparkles,
  UserRound,
} from "lucide-react";
import { api, OsintAccount, SocialPost, VisitorDetail } from "@/lib/api";
import { aiSourceLabel } from "@/lib/ai-sources";
import { icpFitLabel, icpFitTooltip } from "@/lib/icp-fit-copy";
import { cn } from "@/lib/utils";
import { CardGridSkeleton, PageHeaderSkeleton, StatGridSkeleton } from "@/components/skeletons";
import { StatusBadge } from "@/components/ui/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/* ------------------------------------------------------------------ */
/* Small presentational helpers — a real profile, not a wall of cards. */
/* ------------------------------------------------------------------ */

// Compact a page path for the chips. Strips the origin, and collapses long
// paths (e.g. /blog/2026/06/really-long-post-slug → /blog/…/really-long-post).
function shortenPath(raw: string, max = 26): string {
  let p = raw;
  try {
    if (/^https?:\/\//i.test(raw)) p = new URL(raw).pathname || raw;
  } catch {
    /* not a URL — use as-is */
  }
  if (p.length <= max) return p;
  const segs = p.split("/").filter(Boolean);
  if (segs.length >= 2) {
    const collapsed = `/${segs[0]}/…/${segs[segs.length - 1]}`;
    if (collapsed.length <= max) return collapsed;
  }
  return p.slice(0, max - 1) + "…";
}

/** Parse an API timestamp as UTC.
 *
 * DB columns are naive `DateTime` and serialize without a `Z`, and JS parses an
 * offset-less datetime as LOCAL time — so a UTC+7 viewer would read a 5-minute-old
 * event as "7h ago". Append the marker when the string carries no zone of its own.
 */
function parseApiDate(iso: string): Date {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone || !iso.includes("T") ? iso : `${iso}Z`);
}

function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - parseApiDate(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return parseApiDate(iso).toLocaleDateString();
}

function IntentRing({ score }: { score: number }) {
  const r = 26;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score));
  const stroke =
    score >= 70 ? "stroke-intent-high" : score >= 40 ? "stroke-warning" : "stroke-muted-foreground";
  const text =
    score >= 70 ? "text-intent-high" : score >= 40 ? "text-warning" : "text-muted-foreground";
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative h-16 w-16">
        <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90">
          <circle cx="32" cy="32" r={r} fill="none" strokeWidth="5" className="stroke-border" />
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ - (pct / 100) * circ}
            className={cn("transition-[stroke-dashoffset] duration-700 ease-out", stroke)}
          />
        </svg>
        <span
          className={cn(
            "absolute inset-0 flex items-center justify-center font-mono text-lg font-medium",
            text,
          )}
        >
          {Math.round(score)}
        </span>
      </div>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Intent</span>
    </div>
  );
}

function withHttps(url: string): string {
  return /^[a-z][a-z0-9+.-]*:/i.test(url) ? url : `https://${url}`;
}

function LinkPill({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs font-medium text-foreground transition hover:border-primary/40 hover:text-primary"
    >
      {label}
      <ExternalLink className="h-3 w-3 opacity-60" />
    </a>
  );
}

function Section({
  title,
  icon: Icon,
  action,
  children,
  className,
}: {
  title: string;
  icon?: ComponentType<{ className?: string }>;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-xl border bg-card shadow-sm", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-5 py-3.5">
        <h3 className="flex items-center gap-2 font-serif text-base font-semibold tracking-tight">
          {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
          {title}
        </h3>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

// Foldable variant of Section — native <details>, header stays clickable.
function CollapsibleSection({
  title,
  icon: Icon,
  defaultOpen = true,
  children,
  className,
}: {
  title: string;
  icon?: ComponentType<{ className?: string }>;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details open={defaultOpen} className={cn("group rounded-xl border bg-card shadow-sm", className)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3.5">
        <span className="flex items-center gap-2 font-serif text-base font-semibold tracking-tight">
          {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
          {title}
        </span>
        <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border/60 p-5">{children}</div>
    </details>
  );
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="max-w-[62%] text-right font-medium">{children}</span>
    </div>
  );
}

function providerCount(count: number): string {
  return `${count} data provider${count === 1 ? "" : "s"}`;
}

/** Why this visitor is still unidentified: real attempts vs provider outages.
 *
 * These are two different things and the whole point is to keep them apart. An
 * *attempt* means a provider answered and nobody matched — that is information
 * about the visitor, and it arms the 30-day retry lock. An *outage* means the
 * provider never answered — that says nothing about the visitor, so it is
 * deliberately not recorded as an attempt and the visitor stays retryable.
 * Showing only "tried: leadpipe" for a vendor that was down reads as "we looked
 * and found nothing", which is exactly the wrong conclusion.
 */
function ResolutionAttempts({ visitor }: { visitor: VisitorDetail }) {
  const tried = visitor.resolution_providers_tried ?? [];
  const outages = visitor.outage_providers ?? [];
  if (tried.length === 0 && outages.length === 0) return null;

  return (
    <div className="space-y-1.5 rounded-xl border bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
      {tried.length > 0 && (
        <p>
          <span className="font-medium text-foreground">
            Checked {providerCount(tried.length)}
          </span>
          {visitor.last_resolution_attempt && (
            <> · last attempt {timeAgo(visitor.last_resolution_attempt)}</>
          )}
        </p>
      )}
      {outages.length > 0 && (
        <p>
          <span className="font-medium text-amber-600 dark:text-amber-500">
            {providerCount(outages.length)} unavailable
          </span>
          {visitor.last_outage_at && <> ({timeAgo(visitor.last_outage_at)})</>}. This
          isn&apos;t a &quot;no match&quot; — the visitor stays eligible for a retry.
        </p>
      )}
    </div>
  );
}

// Handoff Detection H2: friendly label for a fetch-side agent vendor.
const HANDOFF_VENDOR_LABELS: Record<string, string> = {
  openai: "ChatGPT",
  anthropic: "Claude",
  perplexity: "Perplexity",
};

function handoffVendorLabel(vendor: string): string {
  return HANDOFF_VENDOR_LABELS[vendor] ?? vendor;
}

// PROBABILISTIC copy only (AC-H2-4) — a correlated signal, never a certainty.
// Deliberately hedged: "likely", "may indicate", "confidence" qualifier.
function handoffCopy(visitor: VisitorDetail): string {
  const vendor = handoffVendorLabel(visitor.handoff_vendor ?? "");
  const secs = visitor.handoff_delta_seconds ?? 0;
  const mins = Math.max(1, Math.round(secs / 60));
  return (
    `${vendor} fetched this page about ${mins} min before this visit. ` +
    `${visitor.handoff_confidence} confidence this human may be the person behind that AI research. ` +
    `Correlated signal, not a certainty.`
  );
}

function CompletenessBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "bg-success" : pct >= 50 ? "bg-warning" : "bg-primary";
  return (
    <div className="mb-4 space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Profile completeness</span>
        <span className="font-mono font-medium tabular-nums">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-700", color)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function VisitorDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const visitorId = params.visitorId as string;
  const siteId = searchParams.get("site") || "";
  const [visitor, setVisitor] = useState<VisitorDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Deep-dive research (the full pipeline) — the single research action.
  const [resolving, setResolving] = useState(false);
  const [resolveResult, setResolveResult] = useState<{
    status: string;
    message?: string;
  } | null>(null);
  const [showGuesses, setShowGuesses] = useState(false);

  // Recent social posts by this visitor, pulled from the EasyEngage feed
  // (source=visitors) and matched on their Twitter handle. null = not loaded.
  const [posts, setPosts] = useState<SocialPost[] | null>(null);
  // Recent LinkedIn posts for this visitor, pulled from the feed (source=visitors)
  // and matched on their LinkedIn vanity slug. null = not loaded.
  const [liPosts, setLiPosts] = useState<SocialPost[] | null>(null);
  // In-flight guard for the internal-traffic override action.
  const [savingOverride, setSavingOverride] = useState(false);
  const [savingCandidate, setSavingCandidate] = useState(false);

  useEffect(() => {
    if (!siteId || !visitorId) return;
    api
      .getVisitor(siteId, visitorId)
      .then(setVisitor)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [siteId, visitorId]);

  const handle = visitor?.twitter_handle;
  useEffect(() => {
    if (!handle) return;
    const want = handle.replace(/^@/, "").toLowerCase();
    let cancelled = false;
    api
      .getFeed(1, undefined, undefined, undefined, "visitors")
      .then((res) => {
        if (cancelled) return;
        const mine = res.posts
          .filter((p) => (p.author_username ?? "").replace(/^@/, "").toLowerCase() === want)
          .slice(0, 4);
        setPosts(mine);
      })
      .catch(() => {
        if (!cancelled) setPosts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [handle]);

  const liUrl = visitor?.linkedin_url;
  useEffect(() => {
    if (!liUrl) return;
    const m = liUrl.match(/\/in\/([^/?#]+)/);
    const vanity = (m?.[1] || "").toLowerCase();
    if (!vanity) return;
    let cancelled = false;
    api
      .getFeed(1, undefined, undefined, undefined, "visitors")
      .then((res) => {
        if (cancelled) return;
        const mine = res.posts
          .filter(
            (p) =>
              String(p.platform).toLowerCase() === "linkedin" &&
              (p.author_username ?? "").toLowerCase() === vanity
          )
          .slice(0, 4);
        setLiPosts(mine);
      })
      .catch(() => {
        if (!cancelled) setLiPosts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [liUrl]);

  // Outlier / internal-traffic damping: the human's call always wins over the
  // automatic scorer, permanently and in both directions. Passing null clears
  // the manual call and hands the visitor back to the automatic scorer.
  async function handleInternalOverride(
    override: "internal" | "not_internal" | null,
  ) {
    if (!siteId || !visitorId) return;
    setSavingOverride(true);
    try {
      const result = await api.setInternalOverride(siteId, visitorId, override);
      setVisitor((prev) =>
        prev
          ? {
              ...prev,
              internal_override: result.internal_override,
              is_internal_suspect: result.is_internal_suspect,
            }
          : prev,
      );
    } catch {
      // Non-fatal: the badge simply stays as-is until the next load.
    } finally {
      setSavingOverride(false);
    }
  }

  // Identity-honesty Phase 1: the human's verdict on an unconfirmed match.
  // Confirm → identified (stamps confirmed_at). Reject → back to anonymous and
  // the stale identity row is marked do-not-email so it can't be contacted.
  async function handleCandidateVerdict(verdict: "confirm" | "reject") {
    if (!siteId || !visitorId) return;
    setSavingCandidate(true);
    try {
      const result =
        verdict === "confirm"
          ? await api.confirmCandidate(siteId, visitorId)
          : await api.rejectCandidate(siteId, visitorId);
      setVisitor((prev) =>
        prev ? { ...prev, identity_status: result.status } : prev,
      );
    } catch {
      // Non-fatal: the badge stays as-is until the next load.
    } finally {
      setSavingCandidate(false);
    }
  }

  async function handleResolveSocial(force = false) {
    if (!siteId || !visitorId) return;
    setResolving(true);
    setResolveResult(null);

    try {
      const result = await api.resolveSocial(siteId, visitorId, force);
      setResolveResult({ status: result.status, message: result.message });

      if (result.status === "started" || result.status === "scanning") {
        const deadline = Date.now() + 120_000; // pipeline can take longer
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 5000));
          const updated = await api.getVisitor(siteId, visitorId);
          setVisitor(updated);
          const st = updated.social_context?.social_resolution?.status;
          if (st && st !== "scanning") break;
        }
      } else {
        const updated = await api.getVisitor(siteId, visitorId);
        setVisitor(updated);
      }
    } catch (err) {
      setResolveResult({
        status: "error",
        message: err instanceof Error ? err.message : "Social resolution failed",
      });
    } finally {
      setResolving(false);
    }
  }

  if (loading)
    return (
      <div className="max-w-5xl space-y-6">
        <PageHeaderSkeleton />
        <StatGridSkeleton cols={4} />
        <CardGridSkeleton cards={2} cols={1} />
      </div>
    );
  if (!visitor)
    return (
      <div className="max-w-5xl">
        <Link
          href="/dashboard/visitors"
          className="mb-6 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Back to visitors
        </Link>
        <p className="text-destructive">Visitor not found</p>
      </div>
    );

  const completeness = visitor.enrichment_completeness ?? 0;
  const hasDeepResearch = !!visitor.social_context?.deep_research;
  const identified =
    visitor.identity_status !== "anonymous" &&
    visitor.identity_status !== "unresolvable" &&
    visitor.identity_status !== "vpn_filtered";
  const isCompanyLevel = visitor.identity_level === "company";
  // Identity-honesty Phase 1: an unconfirmed identity-graph match awaiting the
  // owner's verdict. The score is shown, but it is explicitly NOT a promotion
  // mechanism — only the Confirm button below moves them to "identified".
  const isCandidate = visitor.identity_status === "candidate";
  const candidateTooltip = `Unconfirmed match${
    typeof visitor.confidence_score === "number"
      ? ` — ${Math.round(visitor.confidence_score * 100)}% confidence`
      : ""
  }. Not personalized in outreach until confirmed.`;

  const canOsint = identified;

  const resolution = visitor.social_context?.social_resolution;
  const resolveBusy = resolving || resolution?.status === "scanning";
  const resolvedProfiles = resolution?.profiles ?? [];
  const confirmedProfiles = resolvedProfiles.filter((p) => p.confidence === "confirmed");
  const likelyProfiles = resolvedProfiles.filter((p) => p.confidence !== "confirmed");
  const guessProfiles = resolution?.guesses ?? [];

  const statusMessage = resolveResult?.message || resolution?.message;
  const statusIsError =
    resolveResult?.status === "error" || resolution?.status === "error";
  const statusIsWarning =
    resolveResult?.status === "limit_reached" || resolveResult?.status === "disabled";

  // Header line: "Job Title at Company" / "Company" / anonymous fallback.
  const roleLine =
    [visitor.job_title, visitor.company_name].filter(Boolean).join(" at ") ||
    (visitor.identity_status === "verified" || visitor.identity_status === "identified"
      ? "Verified visitor"
      : visitor.identity_status === "provider_candidate"
        ? "Candidate visitor"
        : "Anonymous visitor");
  const locationLine = [visitor.city, visitor.region, visitor.country || visitor.country_code]
    .filter(Boolean)
    .join(", ");

  const renderProfileRow = (p: OsintAccount, i: number) => {
    const username = (p.extra?.username || p.extra?.name) as string | undefined;
    const isPaid = p.source_engine.includes("osint-industries");
    return (
      <div
        key={i}
        className="flex items-center justify-between gap-2 border-b border-border/40 py-2 text-sm last:border-0"
      >
        <span className="truncate">
          {p.url ? (
            <a
              href={p.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-foreground transition hover:text-primary"
            >
              {p.site_name}
            </a>
          ) : (
            <span className="font-medium">{p.site_name}</span>
          )}
          {username && <span className="text-muted-foreground"> · {username}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {isPaid && <Badge className="text-[10px]">Paid</Badge>}
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] capitalize",
              p.confidence === "confirmed"
                ? "text-success"
                : p.confidence === "likely"
                  ? "text-warning"
                  : "text-muted-foreground",
            )}
          >
            {p.confidence}
          </Badge>
        </span>
      </div>
    );
  };

  const researchButton = canOsint ? (
    <Button
      size="sm"
      onClick={() => handleResolveSocial(resolution?.status === "complete")}
      disabled={resolveBusy}
    >
      {resolveBusy ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Researching…
        </>
      ) : (
        <>
          <Sparkles className="mr-2 h-4 w-4" />
          {resolution ? "Re-research" : "Deep-dive research"}
        </>
      )}
    </Button>
  ) : null;

  return (
    <div className="mx-auto max-w-5xl space-y-6 duration-500 animate-in fade-in slide-in-from-bottom-2">
      <Link
        href="/dashboard/visitors"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back to visitors
      </Link>

      {/* ---- Profile hero ---- */}
      <section className="rounded-2xl border bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="font-serif text-2xl font-semibold tracking-tight">
                {visitor.full_name || (identified ? "Unnamed visitor" : "Anonymous visitor")}
              </h1>
              {visitor.identity_status === "candidate" ? (
                <span title={candidateTooltip}>
                  <StatusBadge status="candidate" label="Candidate" />
                </span>
              ) : (
                <StatusBadge status={visitor.identity_status} />
              )}
              {isCompanyLevel && (
                <StatusBadge status="company" label="Company-level" tone="warning" />
              )}
              {visitor.ai_source && (
                <span
                  className="rounded-full bg-info-muted px-2.5 py-0.5 text-xs font-medium text-info"
                  title={`Arrived via ${aiSourceLabel(visitor.ai_source)}, from an AI answer-engine citation`}
                >
                  via {aiSourceLabel(visitor.ai_source)}
                </span>
              )}
              {visitor.is_bot_suspect && (
                <span
                  className="rounded-full bg-warning-muted px-2.5 py-0.5 text-xs font-medium text-warning"
                  title="Bot-suspect: this visitor's visit schedule is unusually regular (cron-like) and their sessions are pageview-only, with no scrolling, clicks or dwell time. Visibility signal only: they stay fully contactable and fully counted."
                >
                  Bot-suspect
                </span>
              )}
              {visitor.is_agent_operated && (
                <span
                  className="rounded-full bg-warning-muted px-2.5 py-0.5 text-xs font-medium text-warning"
                  title="Agent-operated: this session behaved like it was driven by an AI agent or browser automation — either a hard automation tell (headless/webdriver) or very low pointer movement combined with a high rate of dead-centre clicks. Visibility signal only: they stay fully contactable and fully counted."
                >
                  Agent-operated
                </span>
              )}
              {visitor.is_internal_suspect && (
                <span
                  className="rounded-full bg-warning-muted px-2.5 py-0.5 text-xs font-medium text-warning"
                  title="Unusually high activity for this site. Is this you? This visitor's traffic volume is a statistical outlier. It's only a suggestion for you to review: nothing changes unless you confirm below. Until then they stay fully contactable and fully counted."
                >
                  Unusually high activity. Is this you?
                </span>
              )}
              {visitor.handoff_vendor && visitor.handoff_confidence && (
                <span
                  className="rounded-full bg-info-muted px-2.5 py-0.5 text-xs font-medium text-info"
                  title={handoffCopy(visitor)}
                >
                  {handoffVendorLabel(visitor.handoff_vendor)} fetch ·{" "}
                  {visitor.handoff_confidence} confidence
                </span>
              )}
            </div>

            {isCandidate && (
              <div className="rounded-lg border border-warning/40 bg-warning-muted/40 p-3">
                <p className="text-sm text-muted-foreground">{candidateTooltip}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={savingCandidate}
                    onClick={() => handleCandidateVerdict("confirm")}
                  >
                    {savingCandidate ? "Saving…" : "Confirm this is them"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={savingCandidate}
                    onClick={() => handleCandidateVerdict("reject")}
                  >
                    Not them
                  </Button>
                </div>
              </div>
            )}

            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Briefcase className="h-3.5 w-3.5" />
              {roleLine}
              {visitor.industry ? ` · ${visitor.industry}` : ""}
            </p>
            {locationLine && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <MapPin className="h-3.5 w-3.5" />
                {locationLine}
              </p>
            )}

            {/* Contact / social pills */}
            <div className="flex flex-wrap gap-2 pt-1">
              {visitor.email && (
                <LinkPill href={`mailto:${visitor.email}`} label={visitor.email} />
              )}
              {visitor.linkedin_url && <LinkPill href={withHttps(visitor.linkedin_url)} label="LinkedIn" />}
              {visitor.twitter_handle && (
                <LinkPill href={`https://x.com/${visitor.twitter_handle}`} label={`@${visitor.twitter_handle}`} />
              )}
            </div>

            <p className="pt-1 font-mono text-xs text-muted-foreground/70">{visitor.visitor_id}</p>
          </div>

          {/* Intent + primary action */}
          <div className="flex shrink-0 flex-row items-center gap-4 sm:flex-col sm:items-end">
            <IntentRing score={visitor.intent_score} />
            {/* ICP fit — band vocabulary only. Never renders raw site_profile
                text: the label and tooltip come from constant-only builders. */}
            {icpFitLabel(visitor.icp_fit) && (
              <Badge
                variant="outline"
                className="whitespace-nowrap"
                title={icpFitTooltip(visitor.icp_fit) ?? undefined}
              >
                {icpFitLabel(visitor.icp_fit)}
              </Badge>
            )}
            {researchButton}
          </div>
        </div>

        {visitor.conviction && (
          <div className="mt-5 rounded-lg border-l-2 border-primary bg-primary/5 px-4 py-3">
            <p className="text-xs font-medium uppercase tracking-wide text-primary/80">
              Why reach out
            </p>
            <p className="mt-0.5 text-sm">{visitor.conviction}</p>
          </div>
        )}

        {statusMessage && (
          <p
            className={cn(
              "mt-4 text-xs",
              statusIsError
                ? "text-destructive"
                : statusIsWarning
                  ? "text-warning"
                  : "text-muted-foreground",
            )}
          >
            {statusMessage}
          </p>
        )}
      </section>

      {/* ---- Hairline stat strip (no boxes) ---- */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-4">
        {[
          { label: "Pageviews", value: visitor.total_pageviews },
          { label: "Sessions", value: visitor.total_sessions },
          { label: "Avg time", value: `${Math.round(visitor.avg_time_on_page)}s` },
          { label: "Max scroll", value: `${visitor.max_scroll_depth}%` },
        ].map((s) => (
          <div key={s.label} className="bg-card px-4 py-4 text-center">
            <p className="font-mono text-2xl font-medium tabular-nums">{s.value}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{s.label}</p>
          </div>
        ))}
      </div>

      {/* ---- Honesty banners ---- */}
      {isCompanyLevel && (
        <div className="flex gap-3 rounded-xl border border-warning/30 bg-warning-muted px-4 py-3 text-xs text-warning">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <span className="font-semibold">Company-level match.</span> This visitor&apos;s IP maps
            to this company and an employee was inferred from it, likely{" "}
            <span className="font-semibold">not</span> the actual person who visited. Treat as an
            account signal, not a verified contact; don&apos;t email this address.
          </p>
        </div>
      )}
      {visitor.identity_status === "unresolvable" && visitor.coverage_note && (
        <div className="rounded-xl border bg-muted/40 px-4 py-3 text-xs text-muted-foreground">
          {visitor.coverage_note}
        </div>
      )}
      <ResolutionAttempts visitor={visitor} />

      {/* ---- Body: main + sidebar ---- */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {identified ? (
            <Section title="Enrichment" icon={Sparkles}>
              <CompletenessBar value={completeness} />
              <div className="divide-y divide-border/40">
                {visitor.job_title && <InfoRow label="Job title">{visitor.job_title}</InfoRow>}
                {visitor.company_name && <InfoRow label="Company">{visitor.company_name}</InfoRow>}
                {visitor.industry && <InfoRow label="Industry">{visitor.industry}</InfoRow>}
                {visitor.phone && <InfoRow label="Phone">{visitor.phone}</InfoRow>}
                {visitor.linkedin_headline && (
                  <InfoRow label="LinkedIn headline">{visitor.linkedin_headline}</InfoRow>
                )}
                {visitor.twitter_bio && <InfoRow label="Twitter bio">{visitor.twitter_bio}</InfoRow>}
              </div>
              {completeness === 0 && !hasDeepResearch && (
                <p className="pt-1 text-xs italic text-muted-foreground">
                  No enrichment data yet. Run Deep-dive research to populate this profile.
                </p>
              )}
            </Section>
          ) : (
            <Section title="Identity" icon={UserRound}>
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-secondary text-muted-foreground">
                  <UserRound className="h-5 w-5" />
                </div>
                <p className="text-sm font-medium">This visitor is anonymous</p>
                <p className="max-w-sm text-xs text-muted-foreground">
                  {visitor.coverage_note ||
                    "Not enough intent signal to resolve an identity yet. Intent 40+ unlocks resolution."}
                </p>
              </div>
            </Section>
          )}

          {hasDeepResearch && (
            <Section
              title="Deep research"
              icon={Search}
              action={
                visitor.social_context?.researched_at ? (
                  <span className="text-xs text-muted-foreground">
                    {new Date(visitor.social_context.researched_at).toLocaleDateString()}
                  </span>
                ) : undefined
              }
            >
              <div className="prose prose-sm max-w-none dark:prose-invert">
                {visitor.social_context!.deep_research!.split("\n").map((line, i) => {
                  if (!line.trim()) return <br key={i} />;
                  if (line.startsWith("## "))
                    return (
                      <h3 key={i} className="mb-2 mt-4 text-base font-semibold">
                        {line.replace("## ", "")}
                      </h3>
                    );
                  if (line.startsWith("### "))
                    return (
                      <h4 key={i} className="mb-1 mt-3 text-sm font-semibold">
                        {line.replace("### ", "")}
                      </h4>
                    );
                  if (line.startsWith("**") && line.endsWith("**"))
                    return (
                      <p key={i} className="text-sm font-semibold">
                        {line.replace(/\*\*/g, "")}
                      </p>
                    );
                  if (line.startsWith("- "))
                    return (
                      <li key={i} className="ml-4 list-disc text-sm">
                        {line.replace("- ", "")}
                      </li>
                    );
                  return (
                    <p key={i} className="text-sm leading-relaxed">
                      {line}
                    </p>
                  );
                })}
              </div>
            </Section>
          )}

          {visitor.twitter_handle && (
            <Section
              title="Recent posts"
              icon={MessageSquare}
              action={
                <a
                  href={`https://x.com/${visitor.twitter_handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-muted-foreground transition hover:text-primary"
                >
                  @{visitor.twitter_handle}
                </a>
              }
            >
              {posts === null ? (
                <div className="space-y-3">
                  {[0, 1].map((i) => (
                    <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
                  ))}
                </div>
              ) : posts.length === 0 ? (
                <p className="text-xs italic text-muted-foreground">
                  No recent posts pulled yet. Sync the EasyEngage feed to load @
                  {visitor.twitter_handle}&apos;s posts.
                </p>
              ) : (
                <div className="space-y-3">
                  {posts.map((p) => (
                    <a
                      key={p.id}
                      href={p.post_url ?? `https://x.com/${visitor.twitter_handle}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded-lg border border-border/60 p-3 transition hover:border-primary/40"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">@{p.author_username}</span>
                        <span>{timeAgo(p.posted_at)}</span>
                      </div>
                      {p.content && (
                        <p className="line-clamp-3 text-sm leading-relaxed">{p.content}</p>
                      )}
                      <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary">
                        <MessageSquare className="h-3 w-3" /> Reply
                        <ExternalLink className="h-3 w-3 opacity-60" />
                      </span>
                    </a>
                  ))}
                </div>
              )}
            </Section>
          )}

          {liPosts && liPosts.length > 0 && (
            <Section
              title="Recent LinkedIn posts"
              icon={Briefcase}
              action={
                visitor.linkedin_url ? (
                  <a
                    href={withHttps(visitor.linkedin_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground transition hover:text-primary"
                  >
                    View profile
                  </a>
                ) : undefined
              }
            >
              <div className="space-y-3">
                {liPosts.map((p) => (
                  <a
                    key={p.id}
                    href={p.post_url || visitor.linkedin_url ? withHttps((p.post_url ?? visitor.linkedin_url)!) : "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-lg border border-border/60 p-3 transition hover:border-primary/40"
                  >
                    <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{p.author_name}</span>
                      <span>{timeAgo(p.posted_at)}</span>
                    </div>
                    {p.content && (
                      <p className="line-clamp-4 whitespace-pre-wrap text-sm leading-relaxed">
                        {p.content}
                      </p>
                    )}
                    <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary">
                      <ExternalLink className="h-3 w-3 opacity-60" /> View on LinkedIn
                    </span>
                  </a>
                ))}
              </div>
            </Section>
          )}

          {canOsint && (
            <CollapsibleSection title="Social profiles" icon={Globe}>
              <div className="space-y-4">
                {confirmedProfiles.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-semibold text-success">
                      Verified ({confirmedProfiles.length}): same person
                    </p>
                    {confirmedProfiles.map(renderProfileRow)}
                  </div>
                )}

                {likelyProfiles.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-semibold text-warning">
                      Likely, unverified ({likelyProfiles.length})
                    </p>
                    {likelyProfiles.map(renderProfileRow)}
                  </div>
                )}

                {guessProfiles.length > 0 && (
                  <div className="border-t border-border/60 pt-3">
                    <button
                      type="button"
                      onClick={() => setShowGuesses((v) => !v)}
                      className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:underline"
                    >
                      <ChevronDown
                        className={cn("h-3 w-3 transition-transform", showGuesses && "rotate-180")}
                      />
                      {showGuesses ? "Hide" : "Show"} {guessProfiles.length} unverified guess
                      {guessProfiles.length > 1 ? "es" : ""} (likely wrong person)
                    </button>
                    {showGuesses && <div className="mt-2 opacity-70">{guessProfiles.map(renderProfileRow)}</div>}
                  </div>
                )}

                {resolution?.status === "complete" && resolvedProfiles.length === 0 && (
                  <p className="text-xs italic text-muted-foreground">
                    No verified profiles found for this person.
                  </p>
                )}
                {!resolution && !resolveResult && (
                  <p className="text-xs italic text-muted-foreground">
                    Run <span className="font-medium">Deep-dive research</span> to find verified
                    social profiles.
                  </p>
                )}
              </div>
            </CollapsibleSection>
          )}

        </div>

        {/* ---- Sidebar: activity ---- */}
        <div className="space-y-6">
          <CollapsibleSection title="Activity" icon={Activity}>
            <div className="divide-y divide-border/40">
              <InfoRow label="First seen">{new Date(visitor.first_seen).toLocaleString()}</InfoRow>
              <InfoRow label="Last seen">{new Date(visitor.last_seen).toLocaleString()}</InfoRow>
              <InfoRow label="Device">{visitor.device_type || "Unknown"}</InfoRow>
              <InfoRow label="Country">{visitor.country_code || "Unknown"}</InfoRow>
              {visitor.top_referrer && <InfoRow label="Referrer">{visitor.top_referrer}</InfoRow>}
              {visitor.ai_source && <InfoRow label="Arrived via">{aiSourceLabel(visitor.ai_source)}</InfoRow>}
              {visitor.is_bot_suspect && (
                <InfoRow label="Bot-suspect">Cron-like cadence, pageview-only sessions</InfoRow>
              )}
              {visitor.is_agent_operated && (
                <InfoRow label="Agent-operated">
                  Session behaved like an AI agent or browser automation
                </InfoRow>
              )}
              {(visitor.is_internal_suspect || visitor.internal_override) && (
                <InfoRow label="Activity volume">
                  <div className="space-y-1.5">
                    <p>
                      {visitor.internal_override === "internal"
                        ? "You marked this visitor as your own team's traffic."
                        : visitor.internal_override === "not_internal"
                          ? "You marked this visitor as a real outside visitor."
                          : "Unusually high activity for this site. Is this you? A statistical outlier, not a confirmed identity. This is a suggestion for you to review: until you confirm, this visitor is counted and prioritised exactly like any other."}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {visitor.internal_override !== "internal" && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={savingOverride}
                          onClick={() => handleInternalOverride("internal")}
                        >
                          This is me / my team
                        </Button>
                      )}
                      {visitor.internal_override !== "not_internal" && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={savingOverride}
                          onClick={() => handleInternalOverride("not_internal")}
                        >
                          Not me, clear flag
                        </Button>
                      )}
                      {visitor.internal_override && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={savingOverride}
                          onClick={() => handleInternalOverride(null)}
                        >
                          Undo my choice
                        </Button>
                      )}
                    </div>
                  </div>
                </InfoRow>
              )}
              {visitor.handoff_vendor && visitor.handoff_confidence && (
                <InfoRow label="AI research signal">{handoffCopy(visitor)}</InfoRow>
              )}
              {visitor.utm_source && <InfoRow label="Source">{visitor.utm_source}</InfoRow>}
            </div>
          </CollapsibleSection>

          {visitor.pages_visited.length > 0 && (
            <Section title="Pages visited" icon={Globe}>
              <div className="flex flex-wrap gap-1.5">
                {visitor.pages_visited.slice(0, 5).map((page, i) => (
                  <Badge
                    key={i}
                    variant="secondary"
                    title={page}
                    className="max-w-full truncate text-xs font-normal"
                  >
                    {shortenPath(page)}
                  </Badge>
                ))}
                {visitor.pages_visited.length > 5 && (
                  <Badge
                    variant="outline"
                    title={visitor.pages_visited.slice(5).join("\n")}
                    className="text-xs font-normal text-muted-foreground"
                  >
                    +{visitor.pages_visited.length - 5}
                  </Badge>
                )}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
