"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, Segment, SiteStats } from "@/lib/api";
import { CardGridSkeleton } from "@/components/skeletons";
import { EmptyState } from "@/components/empty-state";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function priorityColor(priority: string) {
  switch (priority) {
    case "high": return "destructive" as const;
    case "medium": return "default" as const;
    default: return "secondary" as const;
  }
}

export default function SegmentsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [stats, setStats] = useState<SiteStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  function loadSegments() {
    if (!siteId) return;
    setLoading(true);
    setError(null);
    api
      .listSegments(siteId)
      .then((r) => setSegments(r.segments))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(loadSegments, [siteId]);

  // Powers the empty state's "X of 10" progress bar — non-blocking.
  useEffect(() => {
    if (!siteId) {
      setStats(null);
      return;
    }
    api
      .getVisitorStats(siteId)
      .then(setStats)
      .catch(() => setStats(null));
  }, [siteId]);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await api.triggerSegmentation(siteId);
      setTimeout(loadSegments, 3000);
    } catch {
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Segments</h2>
        <div className="flex items-center gap-3">
          <SiteSelector value={siteId} onChange={setSiteId} />
          {siteId && (
            <Button size="sm" onClick={handleTrigger} disabled={triggering}>
              {triggering ? "Running..." : "Re-run segmentation"}
            </Button>
          )}
        </div>
      </div>

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view segments.</p>
      ) : loading ? (
        <CardGridSkeleton cards={4} cols={2} />
      ) : error ? (
        <ErrorBanner
          message={`Couldn't load segments — ${error}`}
          onRetry={loadSegments}
        />
      ) : segments.length === 0 ? (
        <EmptyState
          title="No segments yet"
          description={
            <>
              Beam groups visitors into segments automatically once{" "}
              <strong>10 newly enriched visitors</strong> accumulate. Each segment ships with
              recommended channels and a messaging angle — or click &quot;Re-run
              segmentation&quot; to trigger manually.
            </>
          }
          progress={{
            current: stats?.enriched_unsegmented ?? stats?.enriched ?? 0,
            target: 10,
            label: "enriched visitors toward your next segments",
          }}
          action={
            <Button asChild variant="outline">
              <Link href={`/dashboard/visitors?site=${siteId}`}>View visitors</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {segments.map((seg) => (
            <Card key={seg.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{seg.name}</CardTitle>
                  <Badge variant={priorityColor(seg.priority)}>{seg.priority}</Badge>
                </div>
                <CardDescription>{seg.description}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Visitors</span>
                  <span className="font-medium">{seg.visitor_count}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Channels:</span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {seg.recommended_channels.map((ch) => (
                      <Badge key={ch} variant="outline" className="text-xs">
                        {ch}
                      </Badge>
                    ))}
                  </div>
                </div>
                {seg.messaging_angle && (
                  <div>
                    <span className="text-muted-foreground">Messaging angle:</span>
                    <p className="mt-1">{seg.messaging_angle}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
