"use client";

import { useEffect, useRef, useState, type ComponentType } from "react";
import Link from "next/link";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Users, Layers, FileText, Megaphone, Send, Radio, CheckCircle2, X } from "lucide-react";
import { api, type Site } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ListCardSkeleton } from "@/components/skeletons";

type ActionItem = {
  key: string;
  icon: ComponentType<{ className?: string }>;
  text: string;
  href: string;
  cta: string;
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const IGNORE_KEY = "beam_today_ignored_v1";
// Remembers the day the "all caught up" card was dismissed, so it stays gone for
// the rest of that day instead of re-appearing on every navigation back.
const CAUGHT_UP_KEY = "beam_today_caughtup_v1";

const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
};

// Persisted set of action keys the user dismissed so they stop nagging.
function useIgnored() {
  const [ignored, setIgnored] = useState<Set<string>>(new Set());
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(IGNORE_KEY);
      if (raw) setIgnored(new Set(JSON.parse(raw) as string[]));
    } catch {
      /* ignore corrupt storage */
    }
    setHydrated(true);
  }, []);

  const ignore = (key: string) => {
    setIgnored((prev) => {
      const next = new Set(prev).add(key);
      try {
        localStorage.setItem(IGNORE_KEY, JSON.stringify(Array.from(next)));
      } catch {
        /* storage full / unavailable — keep in-memory */
      }
      return next;
    });
  };

  return { ignored, ignore, hydrated };
}

// Compose the day's to-do list from real data across the user's sites. Drafts
// are per-user (one global count); everything else is summed per site.
async function computeActions(sites: Site[], qc: QueryClient): Promise<ActionItem[]> {
  const pendingDraftsP = api
    .getDrafts("pending")
    .then((r) => r.total)
    .catch(() => 0);

  const perSite = await Promise.all(
    sites.map(async (s) => {
      const [stats, campaigns] = await Promise.all([
        qc
          .fetchQuery({
            queryKey: ["visitor-stats", s.site_id],
            queryFn: () => api.getVisitorStats(s.site_id),
          })
          .catch(() => null),
        api.listCampaigns(s.site_id).then((r) => r.campaigns).catch(() => []),
      ]);
      return { site: s, stats, campaigns };
    })
  );
  const pendingDrafts = await pendingDraftsP;

  let eligible = 0;
  let unsegmented = 0;
  let draftCampaigns = 0;
  let activeCampaigns = 0;
  let unverifiedSites = 0;
  for (const { site, stats, campaigns } of perSite) {
    eligible += stats?.eligible_for_resolution ?? 0;
    unsegmented += stats?.enriched_unsegmented ?? 0;
    draftCampaigns += campaigns.filter((c) => c.status === "draft").length;
    activeCampaigns += campaigns.filter((c) => c.status === "active").length;
    if (!site.pixel_verified) unverifiedSites += 1;
  }

  const items: ActionItem[] = [];
  if (unverifiedSites > 0)
    items.push({ key: "pixel", icon: Radio, text: `${plural(unverifiedSites, "site")} still need the Beam pixel installed`, href: "/dashboard/onboarding", cta: "Install" });
  if (eligible > 0)
    items.push({ key: "identify", icon: Users, text: `${plural(eligible, "visitor")} ready to identify`, href: "/dashboard/visitors", cta: "Review" });
  if (unsegmented > 0)
    items.push({ key: "segment", icon: Layers, text: `${plural(unsegmented, "enriched visitor")} ready to segment`, href: "/dashboard/segments", cta: "Segment" });
  if (pendingDrafts > 0)
    items.push({ key: "drafts", icon: FileText, text: `${plural(pendingDrafts, "reply draft")} waiting for approval`, href: "/dashboard/drafts", cta: "Review" });
  if (draftCampaigns > 0)
    items.push({ key: "campaign-approve", icon: Megaphone, text: `${plural(draftCampaigns, "campaign")} awaiting approval`, href: "/dashboard/campaigns", cta: "Review" });
  if (activeCampaigns > 0)
    items.push({ key: "campaign-send", icon: Send, text: `${plural(activeCampaigns, "campaign")} ready to send`, href: "/dashboard/campaigns", cta: "Send" });
  return items;
}

export function TodayActions({ sites }: { sites: Site[] }) {
  const qc = useQueryClient();
  const { ignored, ignore, hydrated } = useIgnored();
  const { data: actions, isLoading } = useQuery({
    queryKey: ["today-actions", sites.map((s) => s.site_id).sort().join(",")],
    queryFn: () => computeActions(sites, qc),
    enabled: sites.length > 0,
  });

  const visible = (actions ?? []).filter((a) => !ignored.has(a.key));
  // Hold the empty state until localStorage hydrates, else SSR shows
  // "caught up" then flickers to the real list.
  const showEmpty =
    hydrated && !isLoading && sites.length > 0 && visible.length === 0;

  // When everything's done, linger on the "all caught up" note briefly, then
  // collapse + fade the whole card out and unmount so "Your sites" slides up.
  const [leavePhase, setLeavePhase] = useState<"show" | "leaving" | "gone">(
    "show"
  );
  // Whether we already dismissed the empty card earlier today (persisted). Once
  // true, the card never re-appears that day — no second show/fade on return.
  const [cuReady, setCuReady] = useState(false);
  const caughtUpToday = useRef(false);

  useEffect(() => {
    try {
      caughtUpToday.current = localStorage.getItem(CAUGHT_UP_KEY) === todayKey();
    } catch {
      /* storage blocked — treat as not dismissed */
    }
    setCuReady(true);
  }, []);

  useEffect(() => {
    if (!cuReady) return;
    if (!showEmpty) {
      setLeavePhase("show");
      return;
    }
    // Already dismissed today → vanish instantly, skip the linger/animation.
    if (caughtUpToday.current) {
      setLeavePhase("gone");
      return;
    }
    const t = setTimeout(() => setLeavePhase("leaving"), 1600);
    return () => clearTimeout(t);
  }, [showEmpty, cuReady]);

  useEffect(() => {
    if (leavePhase !== "leaving") return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(CAUGHT_UP_KEY, todayKey());
      } catch {
        /* storage blocked — at least stays gone this session */
      }
      caughtUpToday.current = true;
      setLeavePhase("gone");
    }, 550); // match duration-500
    return () => clearTimeout(t);
  }, [leavePhase]);

  if (sites.length === 0 || leavePhase === "gone") return null;
  // Dismissed earlier today: don't even flash the card while effects settle.
  if (cuReady && showEmpty && caughtUpToday.current) return null;

  return (
    <div
      className={`grid transition-all duration-500 ease-in-out ${
        leavePhase === "leaving"
          ? "grid-rows-[0fr] opacity-0"
          : "grid-rows-[1fr] opacity-100"
      }`}
    >
      <div className="min-h-0 overflow-hidden">
        <Card>
      <CardHeader>
        <CardTitle className="text-base">Today&apos;s actions</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading || !hydrated || !cuReady ? (
          <ListCardSkeleton rows={3} />
        ) : showEmpty ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success-muted text-success">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <p className="font-serif text-base font-semibold">You&apos;re all caught up</p>
            <p className="text-sm text-muted-foreground">
              No actions need your attention right now.
            </p>
          </div>
        ) : (
          // Horizontal carousel: ~3.5 cards per view, snap-scroll, min-width
          // floor so cards stay usable (and scrollable) on narrow screens.
          <div className="-mx-1 flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-1 pb-2">
            {visible.map((a) => (
              <div
                key={a.key}
                className="relative flex min-w-[160px] shrink-0 snap-start flex-col gap-2 rounded-lg border border-border bg-secondary/30 p-3 basis-[23%]"
              >
                <button
                  type="button"
                  onClick={() => ignore(a.key)}
                  aria-label="Ignore this"
                  title="Ignore — don't show again"
                  className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-muted-foreground">
                  <a.icon className="h-3.5 w-3.5" />
                </span>
                <span className="flex-1 pr-3 text-xs font-medium leading-snug">{a.text}</span>
                <Link href={a.href} className="mt-auto">
                  <Button variant="outline" size="sm" className="h-7 w-full px-2 text-xs">
                    {a.cta}
                  </Button>
                </Link>
              </div>
            ))}
          </div>
        )}
      </CardContent>
        </Card>
      </div>
    </div>
  );
}
