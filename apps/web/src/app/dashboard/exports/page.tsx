"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, Segment } from "@/lib/api";
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

  useEffect(() => {
    if (!siteId) return;
    api.listSegments(siteId).then((r) => setSegments(r.segments)).catch(() => {});
  }, [siteId]);

  function handleExport() {
    if (!selectedSegment || !siteId) return;
    const url = api.getExportUrl(siteId, selectedSegment, platform);
    window.open(url, "_blank");
  }

  return (
    <div className="max-w-lg">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Export Audiences</h2>
        <SiteSelector value={siteId} onChange={setSiteId} />
      </div>

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
            disabled={!selectedSegment}
          >
            Download CSV
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
