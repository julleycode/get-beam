"use client";

import { useEffect, useState, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Sparkles, Users, FileText, Megaphone, AtSign } from "lucide-react";
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
import { StatTile } from "@/components/stat-tile";
import { AskAi } from "@/components/ask-ai";
import { TodayActions } from "@/components/today-actions";

const QUICK_ACTIONS: {
  href: string;
  title: string;
  subtitle: string;
  icon: ComponentType<{ className?: string }>;
}[] = [
  { href: "/dashboard/visitors", title: "Find leads", subtitle: "See who's visiting", icon: Users },
  { href: "/dashboard/drafts", title: "Review drafts", subtitle: "Approve AI replies", icon: FileText },
  { href: "/dashboard/campaigns", title: "Create a campaign", subtitle: "Reach a segment", icon: Megaphone },
  { href: "/dashboard/social-accounts", title: "Connect socials", subtitle: "Engage on their turf", icon: AtSign },
];

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
          <div className="grid grid-cols-3 gap-2">
            <StatTile label="Visitors" value={stats.total_visitors} />
            <StatTile label="Identified" value={stats.identified} tone="info" />
            <StatTile label="Enriched" value={stats.enriched} tone="success" />
          </div>
        )}

        {/* Enrichment nudge */}
        {stats && stats.could_enrich_more > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-warning">
            <Sparkles className="h-3.5 w-3.5 shrink-0" />
            <span>
              {stats.could_enrich_more} visitor
              {stats.could_enrich_more > 1 ? "s" : ""} could be enriched further
              with BYOK keys
            </span>
          </p>
        )}

        {/* Pixel status + re-verify */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs">
            {pixelVerified ? (
              <>
                <span className="h-2 w-2 rounded-full bg-success" />
                <span className="text-muted-foreground">Pixel active</span>
              </>
            ) : (
              <>
                <span className="h-2 w-2 rounded-full bg-warning" />
                <span className="font-medium text-warning">Pixel not verified</span>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={handleVerify}
                  disabled={verifying}
                  title={verifying ? "Checking…" : "Re-verify pixel"}
                  aria-label={verifying ? "Checking pixel" : "Re-verify pixel"}
                  className="ml-1 h-6 w-6"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${verifying ? "animate-spin" : ""}`} />
                </Button>
                <Link
                  href={`/dashboard/onboarding?site=${site.site_id}&step=install`}
                  className="ml-1 text-[11px] font-medium text-warning underline-offset-2 hover:underline"
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
    <Card className="mb-6 border-info/30 bg-info-muted">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-info">
          Your Beam Loop this week
        </CardTitle>
        <CardDescription className="text-xs">
          Engagements driving new visitors back to your site
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hasActivity ? (
          <p className="text-sm font-medium">
            <span className="font-mono font-bold tabular-nums text-info">{roi.total_engagements}</span>
            {" engagements"}
            <span className="mx-2 text-muted-foreground">→</span>
            <span className="font-mono font-bold tabular-nums text-success">{roi.new_visitors_attributed}</span>
            {" new visitors"}
            <span className="mx-2 text-muted-foreground">→</span>
            <span className="font-mono font-bold tabular-nums text-primary">{roi.identified_from_engagement}</span>
            {" identified"}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            No engagement activity yet.{" "}
            <Link href="/dashboard/drafts" className="text-info underline">
              Approve a draft
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

export default function DashboardPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60_000,
  });
  const firstName = me?.full_name?.trim().split(/\s+/)[0] || "there";

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
        <div className="space-y-8">
          {/* Greeting */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-serif text-2xl font-semibold tracking-tight">
                Hey {firstName}, ready to get started?
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Here&apos;s what&apos;s happening across your sites.
              </p>
            </div>
            <Link href="/dashboard/onboarding">
              <Button size="sm">Add site</Button>
            </Link>
          </div>

          {/* Ask Beam anything */}
          <AskAi siteId={sites[0]?.site_id} />

          {/* Quick actions */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {QUICK_ACTIONS.map((qa) => (
              <Link key={qa.href} href={qa.href}>
                <Card className="h-full transition-colors hover:bg-secondary/50">
                  <CardContent className="flex items-start gap-3 p-4">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary">
                      <qa.icon className="h-5 w-5" />
                    </span>
                    <div>
                      <p className="text-sm font-medium">{qa.title}</p>
                      <p className="text-xs text-muted-foreground">{qa.subtitle}</p>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>

          {/* Today's actions (real data) */}
          <TodayActions sites={sites} />

          <BeamLoopWidget />

          {/* Sites */}
          <div className="space-y-3">
            <h2 className="font-serif text-lg font-semibold tracking-tight">
              Your sites
            </h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {sites.map((site) => (
                <SiteCard key={site.site_id} site={site} />
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );

  // The Clerk token gate now lives in the dashboard layout (ClerkTokenGate),
  // so every page — not just Overview — waits for the token before fetching.
  return content;
}
