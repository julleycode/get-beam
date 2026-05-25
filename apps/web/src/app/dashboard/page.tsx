"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, Site, SiteStats } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function SiteCard({ site }: { site: Site }) {
  const [stats, setStats] = useState<SiteStats | null>(null);

  useEffect(() => {
    api.getVisitorStats(site.site_id).then(setStats).catch(() => {});
  }, [site.site_id]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{site.name}</CardTitle>
        <CardDescription className="truncate">{site.url}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Stats row */}
        {stats && stats.total_visitors > 0 && (
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-2xl font-bold">{stats.total_visitors}</p>
              <p className="text-xs text-muted-foreground">Visitors</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-blue-400">
                {stats.identified}
              </p>
              <p className="text-xs text-muted-foreground">Identified</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-green-500">
                {stats.enriched}
              </p>
              <p className="text-xs text-muted-foreground">Enriched</p>
            </div>
          </div>
        )}

        {/* Enrichment nudge */}
        {stats && stats.could_enrich_more > 0 && (
          <p className="text-xs text-yellow-500">
            {stats.could_enrich_more} visitor
            {stats.could_enrich_more > 1 ? "s" : ""} could be enriched further
            with BYOK keys
          </p>
        )}

        {/* Pixel status */}
        <div className="flex items-center gap-1.5 text-xs">
          {site.pixel_verified ? (
            <>
              <span className="h-2 w-2 rounded-full bg-green-500" />
              <span className="text-muted-foreground">Pixel active</span>
            </>
          ) : (
            <>
              <span className="h-2 w-2 rounded-full bg-yellow-500" />
              <span className="text-muted-foreground">Pixel not verified</span>
            </>
          )}
        </div>

        <div className="flex gap-2">
          <Link href={`/dashboard/visitors?site=${site.site_id}`}>
            <Button variant="outline" size="sm">
              Visitors
            </Button>
          </Link>
          <Link href={`/dashboard/segments?site=${site.site_id}`}>
            <Button variant="outline" size="sm">
              Segments
            </Button>
          </Link>
          <Link href={`/dashboard/campaigns?site=${site.site_id}`}>
            <Button variant="outline" size="sm">
              Campaigns
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [sites, setSites] = useState<Site[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listSites()
      .then((s) => {
        setSites(s);
        if (s.length === 0) {
          router.push("/dashboard/onboarding");
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Dashboard</h2>
        <Link href="/dashboard/onboarding">
          <Button size="sm">Add site</Button>
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {sites.map((site) => (
          <SiteCard key={site.site_id} site={site} />
        ))}
      </div>
    </div>
  );
}
