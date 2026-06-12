"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, Segment } from "@/lib/api";
import { EmptyState } from "@/components/empty-state";
import { SiteSelector } from "@/components/site-selector";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const PLATFORMS = [
  { value: "meta", label: "Meta Custom Audiences" },
  { value: "google", label: "Google Customer Match" },
  { value: "linkedin", label: "LinkedIn Matched Audiences" },
];

export default function ExportsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [selectedSegment, setSelectedSegment] = useState("");
  const [platform, setPlatform] = useState("meta");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId) return;
    api.listSegments(siteId).then((r) => setSegments(r.segments)).catch(() => {});
  }, [siteId]);

  async function handleExport() {
    if (!selectedSegment || !siteId) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      await api.downloadExport(siteId, selectedSegment, platform);
    } catch (err) {
      setDownloadError(
        err instanceof Error ? err.message : "Failed to download export"
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="max-w-lg">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Export Audiences</h2>
        <SiteSelector value={siteId} onChange={setSiteId} />
      </div>

      {siteId && segments.length === 0 ? (
        <EmptyState
          title="Nothing to export yet"
          description="Exports turn segments into CSV audiences for Meta, Google, and LinkedIn ads. Once you have segments, they'll appear here automatically."
          action={
            <Button asChild variant="outline">
              <Link href={`/dashboard/segments?site=${siteId}`}>View segments</Link>
            </Button>
          }
        />
      ) : (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Export segment for ads</CardTitle>
          <CardDescription>
            Download a CSV file formatted for your ad platform
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Segment</label>
            <Select value={selectedSegment} onValueChange={setSelectedSegment}>
              <SelectTrigger>
                <SelectValue placeholder="Select segment" />
              </SelectTrigger>
              <SelectContent>
                {segments.map((seg) => (
                  <SelectItem key={seg.id} value={seg.id}>
                    {seg.name} ({seg.visitor_count} visitors)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Platform</label>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLATFORMS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button
            className="w-full"
            onClick={handleExport}
            disabled={!selectedSegment || downloading}
          >
            {downloading ? "Downloading..." : "Download CSV"}
          </Button>

          {downloadError && (
            <p className="text-sm text-destructive">{downloadError}</p>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  );
}
