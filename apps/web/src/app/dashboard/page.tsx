"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { api, Site, SiteStats, EngagementROI } from "@/lib/api";
import { SiteCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const HAS_CLERK = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

function OverviewSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <SiteCardSkeleton />
      <SiteCardSkeleton />
      <SiteCardSkeleton />
    </div>
  );
}

function SiteCard({ site }: { site: Site }) {
  const [stats, setStats] = useState<SiteStats | null>(null);
  // Local pixel status so a successful re-verify flips the card immediately
  // without refetching the whole site list.
  const [pixelVerified, setPixelVerified] = useState(site.pixel_verified);
  const [verifying, setVerifying] = useState(false);
  const [verifyMessage, setVerifyMessage] = useState<string | null>(null);

  useEffect(() => {
    api.getVisitorStats(site.site_id).then(setStats).catch(() => {});
  }, [site.site_id]);

  async function handleVerify() {
    setVerifying(true);
    setVerifyMessage(null);
    try {
      const result = await api.verifyPixel(site.site_id);
      setPixelVerified(result.verified);
      if (!result.verified) {
        setVerifyMessage(result.message || "Pixel not detected yet — check the install snippet in Settings.");
      }
    } catch (err) {
      setVerifyMessage(err instanceof Error ? err.message : "Verification failed — try again.");
    } finally {
      setVerifying(false);
    }
  }

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

        {/* Pixel status + re-verify */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs">
            {pixelVerified ? (
              <>
                <span className="h-2 w-2 rounded-full bg-green-500" />
                <span className="text-muted-foreground">Pixel active</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-yellow-500" />
                <span className="font-medium text-yellow-700">Pixel not verified</span>
                <button
                  onClick={handleVerify}
                  disabled={verifying}
                  className="ml-1 rounded-full border border-yellow-400 bg-yellow-50 px-2.5 py-0.5 text-[11px] font-medium text-yellow-800 transition-colors hover:bg-yellow-100 disabled:opacity-60"
                >
                  {verifying ? "Checking..." : "Re-verify"}
                </button>
                <Link
                  href={`/dashboard/onboarding?site=${site.site_id}&step=install`}
                  className="ml-1 text-[11px] font-medium text-yellow-800 underline-offset-2 hover:underline"
                >
                  Finish setup →
                </Link>
              </>
            )}
          </div>
          {verifyMessage && !pixelVerified && (
            <p className="text-[11px] text-muted-foreground">{verifyMessage}</p>
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

function DashboardContent({
  onSitesLoaded,
  onError,
  retryKey,
}: {
  onSitesLoaded: (sites: Site[]) => void;
  onError: (message: string) => void;
  retryKey: number;
}) {
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
      .catch((e: Error) => onError(e.message));
  }, [router, onSitesLoaded, onError, retryKey]);

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

  if (!ready) return <OverviewSkeleton />;
  return <>{children}</>;
}

export default function DashboardPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  const handleSites = useState(() => (s: Site[]) => {
    setSites(s);
    setLoaded(true);
  })[0];

  const content = (
    <>
      <DashboardContent
        onSitesLoaded={handleSites}
        onError={setError}
        retryKey={retryKey}
      />
      {error ? (
        <ErrorBanner
          message={`Couldn't load your sites — ${error}`}
          onRetry={() => {
            setError(null);
            setRetryKey((k) => k + 1);
          }}
        />
      ) : !loaded ? (
        <OverviewSkeleton />
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
