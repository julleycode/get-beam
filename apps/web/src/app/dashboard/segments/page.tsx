"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import { api } from "@/lib/api";
import { CardGridSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
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
  const [triggering, setTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["segments", siteId],
    queryFn: () => api.listSegments(siteId),
    enabled: !!siteId,
  });
  const segments = data?.segments ?? [];

  async function handleTrigger() {
    setTriggering(true);
    setTriggerError(null);
    try {
      await api.triggerSegmentation(siteId);
      // Segmentation runs async on the backend — give it a moment, then refetch.
      setTimeout(
        () => queryClient.invalidateQueries({ queryKey: ["segments", siteId] }),
        3000
      );
    } catch (e) {
      setTriggerError(e instanceof Error ? e.message : "Couldn't start segmentation");
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Segments"
        actions={
          <>
            <SiteSelector value={siteId} onChange={setSiteId} />
            {siteId && (
              <Button size="sm" onClick={handleTrigger} disabled={triggering}>
                {triggering ? "Running..." : "Re-run segmentation"}
              </Button>
            )}
          </>
        }
      />

      {triggerError && (
        <div className="mt-4">
          <ErrorBanner message={triggerError} onRetry={handleTrigger} />
        </div>
      )}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view segments.</p>
      ) : isLoading ? (
        <CardGridSkeleton cards={4} cols={2} />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load segments — ${error instanceof Error ? error.message : "unknown error"}`}
          onRetry={() => refetch()}
        />
      ) : segments.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No segments yet"
          description="Segments are auto-generated when 10+ new visitors are enriched. You can also trigger one manually."
          action={
            <Button size="sm" onClick={handleTrigger} disabled={triggering}>
              {triggering ? "Running..." : "Re-run segmentation"}
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
