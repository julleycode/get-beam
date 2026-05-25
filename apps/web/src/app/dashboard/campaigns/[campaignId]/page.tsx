"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api, Campaign } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

  if (loading) return <p className="text-muted-foreground">Loading...</p>;
  if (!campaign) return <p className="text-destructive">Campaign not found</p>;

  const touchpoints = (campaign.plan as { touchpoints?: Touchpoint[] }).touchpoints || [];

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold">{campaign.name}</h2>
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
