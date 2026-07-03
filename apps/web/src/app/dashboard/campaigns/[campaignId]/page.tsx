"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, Campaign } from "@/lib/api";
import type {
  LinkedInOutreachResponse,
  LinkedInScheduleResponse,
} from "@/lib/api-types";
import { ListCardSkeleton, PageHeaderSkeleton, StatGridSkeleton } from "@/components/skeletons";
import { StatTile } from "@/components/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

  // ── LinkedIn outreach ──
  const { data: outreachStatus } = useQuery({
    queryKey: ["linkedin-outreach-status"],
    queryFn: () => api.getLinkedInOutreachStatus(),
    enabled: !!siteId && !!campaignId,
  });
  const [dialog, setDialog] = useState<"send" | "schedule" | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [outreachLimit, setOutreachLimit] = useState(20);
  const [outreachJob, setOutreachJob] =
    useState<LinkedInOutreachResponse | null>(null);

  const outreachMut = useMutation({
    mutationFn: () =>
      api.sendLinkedInOutreach(siteId, campaignId, {
        dryRun,
        limit: outreachLimit,
        action: "connect",
      }),
    onSuccess: (res) => {
      setOutreachJob(res);
      setScheduleResult(null);
      setDialog(null);
    },
  });

  // ── Schedule LinkedIn outreach (durable drip campaign) ──
  const [scheduleDryRun, setScheduleDryRun] = useState(true);
  const [scheduleLimit, setScheduleLimit] = useState(20);
  const [scheduleResult, setScheduleResult] =
    useState<LinkedInScheduleResponse | null>(null);

  // The LinkedIn step's suggested start offset (hours), read off the plan.
  const linkedinDelayHours =
    (
      (campaign?.plan as { touchpoints?: Touchpoint[] })?.touchpoints || []
    ).find((tp) => tp.channel === "linkedin")?.delay_hours_from_start ?? 0;

  const scheduleMut = useMutation({
    mutationFn: () =>
      api.scheduleLinkedInOutreach(siteId, campaignId, {
        dryRun: scheduleDryRun,
        limit: scheduleLimit,
        action: "connect",
      }),
    onSuccess: (res) => {
      setScheduleResult(res);
      setOutreachJob(null);
      setDialog(null);
    },
  });

  // Poll the job until it reports done — react-query drives the interval.
  const { data: jobStatus } = useQuery({
    queryKey: ["linkedin-outreach-job", siteId, campaignId, outreachJob?.job_id],
    queryFn: () =>
      api.getLinkedInOutreachJob(siteId, campaignId, outreachJob!.job_id),
    enabled: !!outreachJob?.job_id,
    refetchInterval: (query) =>
      query.state.data?.status === "done" ? false : 3000,
  });

  // One config drives the single shared outreach dialog (send vs schedule).
  const dialogConfig =
    dialog === "send"
      ? {
          title: "Send LinkedIn outreach",
          lead: "Sends connection requests to this campaign's audience right now.",
          dry: dryRun,
          setDry: setDryRun,
          limit: outreachLimit,
          setLimit: setOutreachLimit,
          mut: outreachMut,
          busy: "Sending…",
          live: "Send for real",
        }
      : dialog === "schedule"
        ? {
            title: "Schedule LinkedIn outreach",
            lead: `Queues a drip that starts in ${linkedinDelayHours}h, then sends within daily limits.`,
            dry: scheduleDryRun,
            setDry: setScheduleDryRun,
            limit: scheduleLimit,
            setLimit: setScheduleLimit,
            mut: scheduleMut,
            busy: "Scheduling…",
            live: "Schedule for real",
          }
        : null;

  const renderOutreachResult = () => {
    if (outreachJob) {
      return (
        <>
          {outreachJob.dry_run && (
            <p className="font-medium text-warning">
              Dry run — nothing was sent.
            </p>
          )}
          <p>
            {jobStatus
              ? `${jobStatus.status} · ${jobStatus.done}/${jobStatus.total} processed · ${jobStatus.sent} sent`
              : "Starting…"}
          </p>
          <p className="text-muted-foreground">
            {outreachJob.total_targets} targeted ·{" "}
            {outreachJob.audience_skipped_no_linkedin} skipped (no LinkedIn URL)
          </p>
        </>
      );
    }
    if (scheduleResult) {
      return (
        <>
          {scheduleResult.dry_run ? (
            <p className="font-medium text-warning">
              Dry run — nothing was scheduled.
            </p>
          ) : (
            scheduleResult.campaign_id && (
              <p>
                Scheduled ·{" "}
                <span className="font-mono">{scheduleResult.campaign_id}</span>
              </p>
            )
          )}
          <p>
            Starts{" "}
            {scheduleResult.scheduled_at
              ? new Date(scheduleResult.scheduled_at).toLocaleString()
              : `in ${scheduleResult.delay_hours}h`}
          </p>
          <p className="text-muted-foreground">
            {scheduleResult.total_targets} targeted ·{" "}
            {scheduleResult.audience_skipped_no_linkedin} skipped (no LinkedIn URL)
          </p>
        </>
      );
    }
    return null;
  };

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

            {tp.channel === "linkedin" && (
              <div className="mt-3 border-t pt-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-muted-foreground">
                    LinkedIn outreach
                  </span>
                  <StatusBadge
                    status={outreachStatus?.outreach_connected ? "on" : "off"}
                    tone={
                      outreachStatus?.outreach_connected ? "success" : "neutral"
                    }
                    label={
                      outreachStatus?.outreach_connected
                        ? "Connected"
                        : "Not connected"
                    }
                  />
                </div>

                {!outreachStatus ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Checking LinkedIn connection…
                  </p>
                ) : !outreachStatus.outreach_connected ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Connect a LinkedIn session in{" "}
                    <Link
                      href="/dashboard/social-accounts"
                      className="underline hover:text-foreground"
                    >
                      Social Accounts
                    </Link>{" "}
                    to send connection requests.
                  </p>
                ) : (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button size="sm" onClick={() => setDialog("send")}>
                      Send now
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDialog("schedule")}
                    >
                      Schedule
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      Schedule drips after {tp.delay_hours_from_start}h, within
                      daily limits.
                    </span>
                  </div>
                )}

                {(outreachJob || scheduleResult) && (
                  <div className="mt-3 space-y-1 rounded-md border bg-muted/40 p-3 text-xs">
                    {renderOutreachResult()}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}

      <Dialog
        open={!!dialog}
        onOpenChange={(o) => {
          if (!o && !dialogConfig?.mut.isPending) setDialog(null);
        }}
      >
        <DialogContent>
          {dialogConfig && (
            <>
              <DialogHeader>
                <DialogTitle>{dialogConfig.title}</DialogTitle>
                <DialogDescription>{dialogConfig.lead}</DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning">
                  Automating LinkedIn breaks its Terms of Service and can get
                  your account restricted. Start with a dry run.
                </p>

                <div className="space-y-1.5">
                  <span className="text-sm font-medium">Mode</span>
                  <div className="flex rounded-md border p-0.5">
                    <button
                      type="button"
                      onClick={() => dialogConfig.setDry(true)}
                      className={cn(
                        "flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors",
                        dialogConfig.dry
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Dry run (preview)
                    </button>
                    <button
                      type="button"
                      onClick={() => dialogConfig.setDry(false)}
                      className={cn(
                        "flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors",
                        !dialogConfig.dry
                          ? "bg-destructive text-destructive-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Live send
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="outreach-limit"
                    className="text-sm font-medium"
                  >
                    Limit
                  </label>
                  <Input
                    id="outreach-limit"
                    type="number"
                    min={1}
                    max={50}
                    value={dialogConfig.limit}
                    onChange={(e) =>
                      dialogConfig.setLimit(
                        Math.max(1, Math.min(50, Number(e.target.value) || 1))
                      )
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    Max 50 profiles per run.
                  </p>
                </div>

                {dialogConfig.mut.isError && (
                  <p className="text-sm text-destructive">
                    {(dialogConfig.mut.error as Error)?.message ??
                      "Something went wrong"}
                  </p>
                )}
              </div>

              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setDialog(null)}
                  disabled={dialogConfig.mut.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant={dialogConfig.dry ? "default" : "destructive"}
                  onClick={() => dialogConfig.mut.mutate()}
                  disabled={dialogConfig.mut.isPending}
                >
                  {dialogConfig.mut.isPending
                    ? dialogConfig.busy
                    : dialogConfig.dry
                      ? "Run dry run"
                      : dialogConfig.live}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
