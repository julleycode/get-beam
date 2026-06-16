"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, OsintAccount, VisitorDetail } from "@/lib/api";
import { CardGridSkeleton, PageHeaderSkeleton, StatGridSkeleton } from "@/components/skeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

function CompletenessBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80
      ? "bg-green-500"
      : pct >= 50
        ? "bg-yellow-500"
        : "bg-orange-500";

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Profile completeness</span>
        <span className="font-medium">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted">
        <div
          className={`h-2 rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

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

  useEffect(() => {
    if (!siteId || !visitorId) return;
    api
      .getVisitor(siteId, visitorId)
      .then(setVisitor)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [siteId, visitorId]);

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
      <div className="space-y-6">
        <PageHeaderSkeleton />
        <StatGridSkeleton cols={3} />
        <CardGridSkeleton cards={2} cols={1} />
      </div>
    );
  if (!visitor) return <p className="text-destructive">Visitor not found</p>;

  const completeness = visitor.enrichment_completeness ?? 0;
  const hasDeepResearch = !!visitor.social_context?.deep_research;

  const osint = visitor.social_context?.osint_scan;
  const canOsint = visitor.identity_status !== "anonymous";
  const osintAccounts = osint?.accounts ?? [];
  const osintProfiles = osintAccounts.filter((a) => a.kind === "profile");
  const osintRegistered = osintAccounts.filter((a) => a.kind !== "profile");

  const resolution = visitor.social_context?.social_resolution;
  const resolveBusy = resolving || resolution?.status === "scanning";
  const resolvedProfiles = resolution?.profiles ?? [];
  const confirmedProfiles = resolvedProfiles.filter(
    (p) => p.confidence === "confirmed",
  );
  const likelyProfiles = resolvedProfiles.filter(
    (p) => p.confidence !== "confirmed",
  );
  const guessProfiles = resolution?.guesses ?? [];

  const renderProfileRow = (p: OsintAccount, i: number) => {
    const username = (p.extra?.username || p.extra?.name) as string | undefined;
    const isPaid = p.source_engine.includes("osint-industries");
    return (
      <div key={i} className="flex items-center justify-between gap-2 text-sm">
        <span className="truncate max-w-[300px]">
          {p.url ? (
            <a
              href={p.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline"
            >
              {p.site_name}
            </a>
          ) : (
            p.site_name
          )}
          {username && (
            <span className="text-muted-foreground"> · {username}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {isPaid && <Badge className="text-[10px]">Paid</Badge>}
          <Badge
            variant="outline"
            className={`text-[10px] ${
              p.confidence === "confirmed"
                ? "text-green-600"
                : p.confidence === "likely"
                  ? "text-yellow-600"
                  : "text-muted-foreground"
            }`}
          >
            {p.confidence === "confirmed" ? "strong match" : p.confidence}
          </Badge>
        </span>
      </div>
    );
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Visitor Detail</h2>
        <p className="text-sm font-mono text-muted-foreground">
          {visitor.visitor_id}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Intent Score
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">
              {Math.round(visitor.intent_score)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Pageviews
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{visitor.total_pageviews}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Sessions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-bold">{visitor.total_sessions}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Behavior</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">First seen</span>
            <span>{new Date(visitor.first_seen).toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Last seen</span>
            <span>{new Date(visitor.last_seen).toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Max scroll depth</span>
            <span>{visitor.max_scroll_depth}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Avg time on page</span>
            <span>{Math.round(visitor.avg_time_on_page)}s</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Device</span>
            <span>{visitor.device_type || "Unknown"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Country</span>
            <span>{visitor.country_code || "Unknown"}</span>
          </div>
          <Separator />
          <div>
            <span className="text-muted-foreground">Pages visited:</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {visitor.pages_visited.map((page, i) => (
                <Badge key={i} variant="secondary" className="text-xs">
                  {page}
                </Badge>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {visitor.identity_status !== "anonymous" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Identity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {visitor.full_name && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name</span>
                <span>{visitor.full_name}</span>
              </div>
            )}
            {visitor.email && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Email</span>
                <span>{visitor.email}</span>
              </div>
            )}
            {visitor.city && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Location</span>
                <span>
                  {visitor.city}, {visitor.region} {visitor.country}
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Enrichment Card — always show for identified visitors */}
      {visitor.identity_status !== "anonymous" && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Enrichment</CardTitle>
              {canOsint && (
                <Button
                  size="sm"
                  onClick={() =>
                    handleResolveSocial(resolution?.status === "complete")
                  }
                  disabled={resolveBusy}
                >
                  {resolveBusy ? (
                    <>
                      <svg
                        className="mr-2 h-4 w-4 animate-spin"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        />
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                        />
                      </svg>
                      Researching...
                    </>
                  ) : resolution ? (
                    "Re-research"
                  ) : (
                    "Deep-dive research"
                  )}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <CompletenessBar value={completeness} />

            {(resolveResult?.message || resolution?.message) && (
              <p
                className={`text-xs ${
                  resolveResult?.status === "error" ||
                  resolution?.status === "error"
                    ? "text-destructive"
                    : resolveResult?.status === "limit_reached" ||
                        resolveResult?.status === "disabled"
                      ? "text-yellow-600"
                      : "text-muted-foreground"
                }`}
              >
                {resolveResult?.message || resolution?.message}
              </p>
            )}

            {/* Enrichment fields */}
            <div className="space-y-2 text-sm">
              {visitor.job_title && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Job title</span>
                  <span>{visitor.job_title}</span>
                </div>
              )}
              {visitor.company_name && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Company</span>
                  <span>{visitor.company_name}</span>
                </div>
              )}
              {visitor.industry && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Industry</span>
                  <span>{visitor.industry}</span>
                </div>
              )}
              {visitor.linkedin_url && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">LinkedIn</span>
                  <a
                    href={visitor.linkedin_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline truncate max-w-[300px]"
                  >
                    {visitor.linkedin_url}
                  </a>
                </div>
              )}
              {visitor.twitter_handle && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Twitter/X</span>
                  <a
                    href={`https://x.com/${visitor.twitter_handle}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline"
                  >
                    @{visitor.twitter_handle}
                  </a>
                </div>
              )}

              {visitor.linkedin_headline && (
                <>
                  <Separator />
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">LinkedIn headline</span>
                    <span className="text-right max-w-[300px]">
                      {visitor.linkedin_headline}
                    </span>
                  </div>
                </>
              )}
              {visitor.twitter_bio && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Twitter bio</span>
                  <span className="text-right max-w-[300px]">
                    {visitor.twitter_bio}
                  </span>
                </div>
              )}

              {completeness === 0 && !hasDeepResearch && (
                <p className="text-xs text-muted-foreground italic">
                  No enrichment data yet. Click Enrich to research this visitor.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Deep Research Card */}
      {hasDeepResearch && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Deep Research</CardTitle>
              {visitor.social_context?.researched_at && (
                <span className="text-xs text-muted-foreground">
                  {new Date(visitor.social_context.researched_at).toLocaleDateString()}
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              {visitor.social_context!.deep_research!.split("\n").map((line, i) => {
                if (!line.trim()) return <br key={i} />;
                if (line.startsWith("## "))
                  return <h3 key={i} className="text-base font-semibold mt-4 mb-2">{line.replace("## ", "")}</h3>;
                if (line.startsWith("### "))
                  return <h4 key={i} className="text-sm font-semibold mt-3 mb-1">{line.replace("### ", "")}</h4>;
                if (line.startsWith("**") && line.endsWith("**"))
                  return <p key={i} className="font-semibold text-sm">{line.replace(/\*\*/g, "")}</p>;
                if (line.startsWith("- "))
                  return <li key={i} className="text-sm ml-4 list-disc">{line.replace("- ", "")}</li>;
                return <p key={i} className="text-sm leading-relaxed">{line}</p>;
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Social Profiles Card — full pipeline (OSINT + Maigret + rules → paid → AI) */}
      {canOsint && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Social Profiles</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {(resolveResult?.message || resolution?.message) && (
              <p
                className={`text-xs ${
                  resolution?.status === "error" ||
                  resolveResult?.status === "error"
                    ? "text-destructive"
                    : resolveResult?.status === "limit_reached" ||
                        resolveResult?.status === "disabled"
                      ? "text-yellow-600"
                      : "text-muted-foreground"
                }`}
              >
                {resolveResult?.message || resolution?.message}
              </p>
            )}

            {confirmedProfiles.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-green-700">
                  Strong matches ({confirmedProfiles.length})
                </p>
                <p className="text-[11px] text-muted-foreground">
                  High confidence — verify before contacting
                </p>
                {confirmedProfiles.map(renderProfileRow)}
              </div>
            )}

            {likelyProfiles.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-yellow-700">
                  Likely — unverified ({likelyProfiles.length})
                </p>
                {likelyProfiles.map(renderProfileRow)}
              </div>
            )}

            {guessProfiles.length > 0 && (
              <div className="space-y-2 border-t pt-2">
                <button
                  type="button"
                  onClick={() => setShowGuesses((v) => !v)}
                  className="text-xs text-muted-foreground underline"
                >
                  {showGuesses ? "Hide" : "Show"} {guessProfiles.length} unverified
                  guess{guessProfiles.length > 1 ? "es" : ""} (likely the wrong
                  person)
                </button>
                {showGuesses && (
                  <div className="space-y-2 opacity-70">
                    {guessProfiles.map(renderProfileRow)}
                  </div>
                )}
              </div>
            )}

            {resolution?.status === "complete" &&
              resolvedProfiles.length === 0 && (
                <p className="text-xs text-muted-foreground italic">
                  No verified profiles for this email. Email-keyed providers (PDL /
                  OSINT Industries) are the reliable source — add an OSINT
                  Industries key to improve hard cases.
                </p>
              )}
            {!resolution && !resolveResult && (
              <p className="text-xs text-muted-foreground italic">
                Click &quot;Deep-dive research&quot; (Enrichment card above) to
                resolve real social profiles — free OSINT + Maigret + rules, then
                AI, then paid lookup only if needed.
              </p>
            )}

            {resolution?.status === "complete" && (
              <p className="text-[11px] text-muted-foreground border-t pt-2">
                Stages: {(resolution.stages_run ?? []).join(" → ") || "—"}
                {resolution.paid?.used ? " · paid lookup used (1 credit)" : ""}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* OSINT Accounts Card — free stacked engines (user-scanner + holehe) */}
      {canOsint && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              OSINT Accounts
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                (raw — from Deep-dive research)
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {osint?.message && (
              <p
                className={`text-xs ${
                  osint?.status === "error"
                    ? "text-destructive"
                    : "text-muted-foreground"
                }`}
              >
                {osint.message}
              </p>
            )}

            {osint?.summary &&
              (osint.status === "complete" || osint.status === "cached") && (
                <p className="text-xs text-muted-foreground">
                  Checked {osint.summary.checked ?? 0}/{osint.summary.total ?? 0}{" "}
                  sites · {osint.summary.profile_count ?? 0} with details ·{" "}
                  {osint.summary.registered_count ?? 0} registration(s)
                  {osint.summary.partial ? " · partial (time cap reached)" : ""}
                </p>
              )}

            {/* Profiles with a real handle/detail surfaced by the engine */}
            {osintProfiles.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  Profiles found
                </p>
                {osintProfiles.map((a, i) => {
                  const username = (a.extra?.username || a.extra?.name) as
                    | string
                    | undefined;
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="truncate max-w-[320px]">
                        {a.url ? (
                          <a
                            href={a.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            {a.site_name}
                          </a>
                        ) : (
                          a.site_name
                        )}
                        {username && (
                          <span className="text-muted-foreground">
                            {" "}
                            · {username}
                          </span>
                        )}
                      </span>
                      <Badge variant="secondary" className="text-[10px]">
                        {a.source_engine}
                      </Badge>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Registered-on: existence only — NO profile link (honest) */}
            {osintRegistered.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  Registered on ({osintRegistered.length})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {osintRegistered.map((a, i) => (
                    <Badge
                      key={i}
                      variant="outline"
                      className="text-[11px] font-normal"
                    >
                      {a.site_name}
                    </Badge>
                  ))}
                </div>
                <p className="text-[11px] text-muted-foreground italic">
                  Email is registered on these sites (account exists; no public
                  profile detail returned).
                </p>
              </div>
            )}

            {(osint?.status === "complete" || osint?.status === "cached") &&
              osintAccounts.length === 0 && (
                <p className="text-xs text-muted-foreground italic">
                  No accounts found for this email.
                </p>
              )}
            {!osint && (
              <p className="text-xs text-muted-foreground italic">
                Run &quot;Deep-dive research&quot; to populate this — which sites
                this email is registered on (free OSINT engines).
              </p>
            )}

            <p className="text-[10px] text-muted-foreground/70 border-t pt-2">
              Existence checks use public password-reset/registration signals
              (OSINT) — a legal gray area under some sites&apos; ToS. Use
              responsibly on your own audience.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
