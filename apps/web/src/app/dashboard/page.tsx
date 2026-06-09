"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { api, Site, SiteStats, EngagementROI } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

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
              <p className="text-2xl font-bold text-blue-600">
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

function BeamLoopWidget() {
  const [roi, setRoi] = useState<EngagementROI | null>(null);

  useEffect(() => {
    api.getEngagementRoi(7).then(setRoi).catch(() => {});
  }, []);

  if (!roi) return null;

  // Only show widget if there is activity to display
  const hasActivity = roi.total_engagements > 0 || roi.new_visitors_attributed > 0;

  return (
    <Card className="mb-6 border-blue-200 bg-blue-50/60">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-blue-700">
          Your Beam Loop this week
        </CardTitle>
        <CardDescription className="text-xs">
          Engagements driving new visitors back to your site
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hasActivity ? (
          <p className="text-sm font-medium">
            <span className="text-blue-600 font-bold">{roi.total_engagements}</span>
            {" engagements"}
            <span className="text-muted-foreground mx-2">→</span>
            <span className="text-green-600 font-bold">{roi.new_visitors_attributed}</span>
            {" new visitors"}
            <span className="text-muted-foreground mx-2">→</span>
            <span className="text-[#FF3366] font-bold">{roi.identified_from_engagement}</span>
            {" identified"}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            No engagement activity yet. Approve a draft in{" "}
            <Link href="/dashboard/engage" className="underline text-blue-600">
              Engage
            </Link>{" "}
            to start the flywheel.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DashboardContent({ onSitesLoaded }: { onSitesLoaded: (sites: Site[]) => void }) {
  const router = useRouter();

  useEffect(() => {
    api
      .listSites()
      .then((s) => {
        onSitesLoaded(s);
        if (s.length === 0) {
          router.push("/dashboard/onboarding");
        }
      })
      .catch(() => {});
  }, [router, onSitesLoaded]);

  return null;
}

function ClerkTokenGate({ children }: { children: React.ReactNode }) {
  // useAuth() is safe here: ClerkTokenGate is only rendered when HAS_CLERK is
  // true (see DashboardPage), so it always runs inside <ClerkProvider>.
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Wait for Clerk to resolve the session before deciding anything.
    if (!isLoaded) return;
    if (!isSignedIn) {
      setReady(true);
      return;
    }

    getToken().then((token: string | null) => {
      if (token) api.setClerkToken(token);
      setReady(true);
    }).catch(() => setReady(true));
  }, [isLoaded, isSignedIn, getToken]);

  if (!ready) return <p className="text-muted-foreground">Loading...</p>;
  return <>{children}</>;
}

export default function DashboardPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [loaded, setLoaded] = useState(false);

  const handleSites = useState(() => (s: Site[]) => {
    setSites(s);
    setLoaded(true);
  })[0];

  const content = (
    <>
      <DashboardContent onSitesLoaded={handleSites} />
      {!loaded ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : (
        <div>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-serif font-semibold tracking-tight">Dashboard</h2>
            <Link href="/dashboard/onboarding">
              <Button size="sm">Add site</Button>
            </Link>
          </div>

          <BeamLoopWidget />

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {sites.map((site) => (
              <SiteCard key={site.site_id} site={site} />
            ))}
          </div>
        </div>
      )}
    </>
  );

  if (HAS_CLERK) {
    return <ClerkTokenGate>{content}</ClerkTokenGate>;
  }

  return content;
}
