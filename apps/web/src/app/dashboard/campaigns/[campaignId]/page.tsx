"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, Campaign } from "@/lib/api";
import { ListCardSkeleton, PageHeaderSkeleton, StatGridSkeleton } from "@/components/skeletons";
import { StatTile } from "@/components/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface Touchpoint {
  order: number;
  channel: string;
  delay_hours_from_start: number;
  subject?: string;
  body?: string;
  connection_note?: string;
  followup_message?: string;
  ad_headline?: string;
  ad_body?: string;
  cta?: string;
  audience_description?: string;
}

export default function CampaignDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const campaignId = params.campaignId as string;
  const siteId = searchParams.get("site") || "";
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!siteId || !campaignId) return;
    api
      .getCampaign(siteId, campaignId)
      .then(setCampaign)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [siteId, campaignId]);

  const isEmail = campaign?.campaign_type === "email";
  const { data: stats } = useQuery({
    queryKey: ["campaign-stats", siteId, campaignId],
    queryFn: () => api.getCampaignStats(siteId, campaignId),
    enabled: !!siteId && !!campaignId && isEmail,
  });

  if (loading)
    return (
      <div className="space-y-6">
        <PageHeaderSkeleton />
        <StatGridSkeleton cols={3} />
        <ListCardSkeleton rows={3} />
      </div>
    );
  if (!campaign) return <p className="text-destructive">Campaign not found</p>;

  const touchpoints = (campaign.plan as { touchpoints?: Touchpoint[] }).touchpoints || [];

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-2xl font-serif font-semibold tracking-tight">{campaign.name}</h2>
        <Badge className="mt-1">{campaign.status}</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-3 text-sm">
        <div>
          <span className="text-muted-foreground">Created</span>
          <p>{new Date(campaign.created_at).toLocaleDateString()}</p>
        </div>
        {campaign.approved_at && (
          <div>
            <span className="text-muted-foreground">Approved</span>
            <p>{new Date(campaign.approved_at).toLocaleDateString()}</p>
          </div>
        )}
        {campaign.started_at && (
          <div>
            <span className="text-muted-foreground">Started</span>
            <p>{new Date(campaign.started_at).toLocaleDateString()}</p>
          </div>
        )}
      </div>

      {isEmail && stats && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatTile label="Sent" value={stats.sent} />
            <StatTile label="Opened" value={stats.opened} tone="info" />
            <StatTile label="Clicked" value={stats.clicked} tone="success" />
            <StatTile
              label="Open rate"
              value={
                <span className="inline-flex items-center gap-1.5">
                  {stats.sent ? `${Math.round(stats.open_rate * 100)}%` : "—"}
                  <InfoTooltip label="About open rate">
                    Opens can be overcounted: Apple Mail auto-loads images even
                    when the email isn&apos;t read. Clicks and return visits are
                    the reliable signals.
                  </InfoTooltip>
                </span>
              }
              tone="info"
            />
            <StatTile
              label="Click rate"
              value={stats.sent ? `${Math.round(stats.click_rate * 100)}%` : "—"}
              tone="success"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">
                Came back after email ({stats.returned_visitors.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {stats.returned_visitors.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No one has returned to your site after this email yet. Return
                  visits show up here as soon as a recipient lands on your site
                  again.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Visitor</TableHead>
                      <TableHead>Opened</TableHead>
                      <TableHead>Clicked</TableHead>
                      <TableHead>Last visit</TableHead>
                      <TableHead>Pageviews after</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stats.returned_visitors.map((rv) => (
                      <TableRow key={rv.visitor_id}>
                        <TableCell>
                          <Link
                            href={`/dashboard/visitors/${rv.visitor_id}?site=${siteId}`}
                            className="hover:underline font-medium"
                          >
                            {rv.full_name || rv.email_masked || rv.visitor_id.slice(0, 10)}
                          </Link>
                        </TableCell>
                        <TableCell className="text-sm">
                          {rv.opened_at ? new Date(rv.opened_at).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell className="text-sm">
                          {rv.clicked_at ? new Date(rv.clicked_at).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell className="text-sm">
                          {rv.last_visit_at
                            ? new Date(rv.last_visit_at).toLocaleString()
                            : "—"}
                        </TableCell>
                        <TableCell className="text-sm">{rv.pageviews_after}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <h3 className="text-lg font-semibold">
        Touchpoints ({touchpoints.length})
      </h3>

      {touchpoints.map((tp) => (
        <Card key={tp.order}>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Badge variant="outline">{tp.channel}</Badge>
              <span>Step {tp.order}</span>
              <span className="text-muted-foreground font-normal">
                +{tp.delay_hours_from_start}h
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {tp.subject && (
              <div>
                <span className="text-muted-foreground">Subject: </span>
                <span className="font-medium">{tp.subject}</span>
              </div>
            )}
            {tp.body && (
              <div>
                <span className="text-muted-foreground">Body:</span>
                <pre className="mt-1 whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                  {tp.body}
                </pre>
              </div>
            )}
            {tp.connection_note && (
              <div>
                <span className="text-muted-foreground">Connection note:</span>
                <p className="mt-1">{tp.connection_note}</p>
              </div>
            )}
            {tp.followup_message && (
              <div>
                <span className="text-muted-foreground">Follow-up:</span>
                <p className="mt-1">{tp.followup_message}</p>
              </div>
            )}
            {tp.ad_headline && (
              <div>
                <span className="text-muted-foreground">Ad headline:</span>
                <p className="mt-1 font-medium">{tp.ad_headline}</p>
              </div>
            )}
            {tp.ad_body && (
              <div>
                <span className="text-muted-foreground">Ad body:</span>
                <p className="mt-1">{tp.ad_body}</p>
              </div>
            )}
            {tp.cta && (
              <div>
                <span className="text-muted-foreground">CTA: </span>
                <span>{tp.cta}</span>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
