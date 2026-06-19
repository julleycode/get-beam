"use client";

import type { ComponentType } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Users, Layers, FileText, Megaphone, Send, Radio, CheckCircle2 } from "lucide-react";
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

// Compose the day's to-do list from real data across the user's sites. Drafts
// are per-user (one global count); everything else is summed per site.
async function computeActions(sites: Site[]): Promise<ActionItem[]> {
  const pendingDraftsP = api
    .getDrafts("pending")
    .then((r) => r.total)
    .catch(() => 0);

  const perSite = await Promise.all(
    sites.map(async (s) => {
      const [stats, campaigns] = await Promise.all([
        api.getVisitorStats(s.site_id).catch(() => null),
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
  const { data: actions, isLoading } = useQuery({
    queryKey: ["today-actions", sites.map((s) => s.site_id).sort().join(",")],
    queryFn: () => computeActions(sites),
    enabled: sites.length > 0,
  });

  if (sites.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Today&apos;s actions</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ListCardSkeleton rows={3} />
        ) : !actions || actions.length === 0 ? (
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
          <ul className="divide-y divide-border">
            {actions.map((a) => (
              <li
                key={a.key}
                className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
                  <a.icon className="h-4 w-4" />
                </span>
                <span className="flex-1 text-sm">{a.text}</span>
                <Link href={a.href}>
                  <Button variant="outline" size="sm">
                    {a.cta}
                  </Button>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
