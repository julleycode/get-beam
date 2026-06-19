"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeletons";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
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

export default function CampaignsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [actionError, setActionError] = useState<string | null>(null);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sendResult, setSendResult] = useState<string | null>(null);
  const [confirmCampaign, setConfirmCampaign] = useState<{ id: string; name: string } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["campaigns", siteId],
    queryFn: () => api.listCampaigns(siteId),
    enabled: !!siteId,
  });
  const campaigns = data?.campaigns ?? [];

  function reload() {
    queryClient.invalidateQueries({ queryKey: ["campaigns", siteId] });
  }

  async function handleStatusChange(campaignId: string, newStatus: string) {
    setActionError(null);
    try {
      await api.updateCampaignStatus(siteId, campaignId, newStatus);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Action failed");
    }
  }

  async function handleSend(campaignId: string, campaignName: string) {
    setActionError(null);
    setSendResult(null);
    setSendingId(campaignId);
    try {
      const { summary: s } = await api.sendCampaign(siteId, campaignId);
      const parts = [`${s.sent} sent`];
      if (s.skipped_suppressed) parts.push(`${s.skipped_suppressed} unsubscribed/bounced skipped`);
      if (s.skipped_already_sent) parts.push(`${s.skipped_already_sent} already sent`);
      if (s.skipped_no_email) parts.push(`${s.skipped_no_email} without email`);
      if (s.throttled) parts.push(`${s.throttled} deferred by hourly cap — send again later`);
      if (s.failed) parts.push(`${s.failed} failed`);
      setSendResult(`"${campaignName}": ${parts.join(", ")} (audience ${s.total_audience}).`);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setSendingId(null);
      setConfirmCampaign(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Campaigns"
        actions={<SiteSelector value={siteId} onChange={setSiteId} />}
      />

      {actionError && (
        <p className="mb-3 text-sm text-destructive">{actionError}</p>
      )}
      {sendResult && (
        <p className="mb-3 text-sm rounded-md bg-secondary px-3 py-2">{sendResult}</p>
      )}

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view campaigns.</p>
      ) : isLoading ? (
        <TableSkeleton cols={4} rows={6} />
      ) : campaigns.length === 0 ? (
        <p className="text-muted-foreground">
          No campaigns yet. Campaigns are auto-generated when segments are created.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Campaign</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {campaigns.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <Link
                    href={`/dashboard/campaigns/${c.id}?site=${siteId}`}
                    className="hover:underline font-medium"
                  >
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.status} />
                </TableCell>
                <TableCell className="text-sm">
                  {new Date(c.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-2">
                    {c.status === "draft" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleStatusChange(c.id, "approved")}
                      >
                        Approve
                      </Button>
                    )}
                    {c.status === "approved" && (
                      <Button
                        size="sm"
                        onClick={() => handleStatusChange(c.id, "active")}
                      >
                        Start
                      </Button>
                    )}
                    {c.status === "active" && (
                      <>
                        <Button
                          size="sm"
                          disabled={sendingId !== null}
                          onClick={() => setConfirmCampaign({ id: c.id, name: c.name })}
                        >
                          {sendingId === c.id ? "Sending..." : "Send emails"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={sendingId === c.id}
                          onClick={() => handleStatusChange(c.id, "paused")}
                        >
                          Pause
                        </Button>
                      </>
                    )}
                    {c.status === "paused" && (
                      <Button
                        size="sm"
                        onClick={() => handleStatusChange(c.id, "active")}
                      >
                        Resume
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog
        open={!!confirmCampaign}
        onOpenChange={(o) => {
          if (!o && sendingId === null) setConfirmCampaign(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send &ldquo;{confirmCampaign?.name}&rdquo; now?</DialogTitle>
            <DialogDescription>
              Real emails go out to this campaign&apos;s audience. Unsubscribed
              and bounced contacts are skipped automatically.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmCampaign(null)}
              disabled={sendingId !== null}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                confirmCampaign &&
                handleSend(confirmCampaign.id, confirmCampaign.name)
              }
              disabled={sendingId !== null}
            >
              {sendingId !== null ? "Sending..." : "Send emails"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
