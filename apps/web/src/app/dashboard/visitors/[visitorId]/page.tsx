"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, VisitorDetail } from "@/lib/api";
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

  // Enrich state
  const [enriching, setEnriching] = useState(false);
  const [enrichResult, setEnrichResult] = useState<{
    status: string;
    message: string;
  } | null>(null);

  useEffect(() => {
    if (!siteId || !visitorId) return;
    api
      .getVisitor(siteId, visitorId)
      .then(setVisitor)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [siteId, visitorId]);

  async function handleEnrich() {
    if (!siteId || !visitorId) return;
    setEnriching(true);
    setEnrichResult(null);

    try {
      const result = await api.enrichVisitor(siteId, visitorId);
      setEnrichResult({ status: result.status, message: result.message });

      if (result.status === "enriched") {
        const updated = await api.getVisitor(siteId, visitorId);
        setVisitor(updated);
      }
    } catch (err) {
      setEnrichResult({
        status: "error",
        message: err instanceof Error ? err.message : "Enrichment failed",
      });
    } finally {
      setEnriching(false);
    }
  }

  if (loading) return <p className="text-muted-foreground">Loading...</p>;
  if (!visitor) return <p className="text-destructive">Visitor not found</p>;

  const completeness = visitor.enrichment_completeness ?? 0;
  const hasDeepResearch = !!visitor.social_context?.deep_research;
  const canEnrich = visitor.identity_status !== "anonymous" && !hasDeepResearch;

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
              {canEnrich && (
                <Button
                  size="sm"
                  onClick={handleEnrich}
                  disabled={enriching}
                >
                  {enriching ? (
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
                  ) : (
                    "Enrich"
                  )}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <CompletenessBar value={completeness} />

            {enrichResult && (
              <p
                className={`text-xs ${
                  enrichResult.status === "enriched"
                    ? "text-green-500"
                    : enrichResult.status === "error"
                      ? "text-destructive"
                      : enrichResult.status === "limit_reached"
                        ? "text-yellow-600"
                        : "text-muted-foreground"
                }`}
              >
                {enrichResult.message}
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
    </div>
  );
}
