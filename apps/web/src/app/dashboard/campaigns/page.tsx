"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeletons";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
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
  const [confirmCampaign, setConfirmCampaign] = useState<{
    id: string;
    name: string;
    isEmail: boolean;
  } | null>(null);
  const [testCampaign, setTestCampaign] = useState<{ id: string; name: string } | null>(null);
  const [testEmail, setTestEmail] = useState("");
  const [testSending, setTestSending] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<{ id: string; name: string } | null>(
    null
  );
  const [deleting, setDeleting] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["campaigns", siteId, showArchived],
    queryFn: () => api.listCampaigns(siteId, showArchived),
    enabled: !!siteId,
  });
  const campaigns = data?.campaigns ?? [];

  function reload() {
    queryClient.invalidateQueries({ queryKey: ["campaigns", siteId] });
  }

  async function handleArchive(campaignId: string, name: string) {
    setActionError(null);
    setSendResult(null);
    setBusyId(campaignId);
    try {
      await api.archiveCampaign(siteId, campaignId);
      setSendResult(`"${name}" archived.`);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Archive failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleUnarchive(campaignId: string, name: string) {
    setActionError(null);
    setSendResult(null);
    setBusyId(campaignId);
    try {
      await api.unarchiveCampaign(siteId, campaignId);
      setSendResult(`"${name}" restored to draft.`);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unarchive failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete() {
    if (!confirmDelete) return;
    setActionError(null);
    setSendResult(null);
    setDeleting(true);
    try {
      await api.deleteCampaign(siteId, confirmDelete.id);
      setSendResult(`"${confirmDelete.name}" deleted.`);
      setConfirmDelete(null);
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
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

  async function handleStart(campaignId: string, campaignName: string, isEmail: boolean) {
    setActionError(null);
    setSendResult(null);
    setSendingId(campaignId);
    try {
      const { summary: s } = await api.startCampaign(siteId, campaignId);
      if (isEmail) {
        const parts = [`${s.sent} sent`];
        if (s.skipped_suppressed) parts.push(`${s.skipped_suppressed} unsubscribed/bounced skipped`);
        if (s.skipped_already_sent) parts.push(`${s.skipped_already_sent} already sent`);
        if (s.skipped_no_email) parts.push(`${s.skipped_no_email} without email`);
        if (s.throttled) parts.push(`${s.throttled} deferred by hourly cap — send again later`);
        if (s.failed) parts.push(`${s.failed} failed`);
        setSendResult(`"${campaignName}": ${parts.join(", ")} (audience ${s.total_audience}).`);
      } else {
        setSendResult(`"${campaignName}" is now active.`);
      }
      reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Start failed");
    } finally {
      setSendingId(null);
      setConfirmCampaign(null);
    }
  }

  function openTestDialog(campaignId: string, campaignName: string) {
    setActionError(null);
    setSendResult(null);
    setTestEmail(localStorage.getItem("beam_test_email") ?? "");
    setTestCampaign({ id: campaignId, name: campaignName });
  }

  async function handleTestSend() {
    if (!testCampaign) return;
    setActionError(null);
    setTestSending(true);
    try {
      const res = await api.testSendCampaign(siteId, testCampaign.id, testEmail.trim());
      localStorage.setItem("beam_test_email", testEmail.trim());
      setSendResult(`Test email for "${testCampaign.name}" sent to ${res.to}.`);
      setTestCampaign(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Test send failed");
    } finally {
      setTestSending(false);
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

      {siteId && (
        <label className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
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
                  <div className="flex flex-wrap gap-2">
                    {c.status === "archived" ? (
                      <IconButton
                        label="Restore to draft"
                        disabled={busyId === c.id}
                        onClick={() => handleUnarchive(c.id, c.name)}
                      >
                        <ArchiveRestore className="h-4 w-4" />
                      </IconButton>
                    ) : (
                      <>
                        {c.status !== "completed" && (
                          <Button
                            size="sm"
                            disabled={sendingId !== null}
                            onClick={() =>
                              setConfirmCampaign({
                                id: c.id,
                                name: c.name,
                                isEmail: c.campaign_type === "email",
                              })
                            }
                          >
                            {sendingId === c.id
                              ? "Starting..."
                              : c.status === "active"
                                ? "Send new"
                                : "Start beam"}
                          </Button>
                        )}
                        {c.status === "active" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={sendingId === c.id}
                            onClick={() => handleStatusChange(c.id, "paused")}
                          >
                            Pause
                          </Button>
                        )}
                        {c.campaign_type === "email" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={sendingId !== null}
                            onClick={() => openTestDialog(c.id, c.name)}
                          >
                            Send test
                          </Button>
                        )}
                        <IconButton
                          label="Archive"
                          disabled={busyId === c.id}
                          onClick={() => handleArchive(c.id, c.name)}
                        >
                          <Archive className="h-4 w-4" />
                        </IconButton>
                      </>
                    )}
                    <IconButton
                      label="Delete"
                      danger
                      disabled={busyId === c.id}
                      onClick={() => setConfirmDelete({ id: c.id, name: c.name })}
                    >
                      <Trash2 className="h-4 w-4" />
                    </IconButton>
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
            <DialogTitle>Start &ldquo;{confirmCampaign?.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              {confirmCampaign?.isEmail
                ? "This approves the campaign and sends real emails to its audience now. Unsubscribed and bounced contacts are skipped automatically."
                : "This approves and activates the campaign."}
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
                handleStart(
                  confirmCampaign.id,
                  confirmCampaign.name,
                  confirmCampaign.isEmail
                )
              }
              disabled={sendingId !== null}
            >
              {sendingId !== null ? "Starting..." : "Start beam"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!testCampaign}
        onOpenChange={(o) => {
          if (!o && !testSending) setTestCampaign(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send a test email</DialogTitle>
            <DialogDescription>
              Sends a preview of &ldquo;{testCampaign?.name}&rdquo; with a{" "}
              <span className="font-mono">[TEST]</span> subject prefix. Nothing
              is sent to the campaign audience.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (testEmail.trim() && !testSending) handleTestSend();
            }}
          >
            <Input
              type="email"
              required
              placeholder="you@company.com"
              value={testEmail}
              onChange={(e) => setTestEmail(e.target.value)}
              autoFocus
            />
            <DialogFooter className="mt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => setTestCampaign(null)}
                disabled={testSending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={testSending || !testEmail.trim()}>
                {testSending ? "Sending..." : "Send test"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!confirmDelete}
        onOpenChange={(o) => {
          if (!o && !deleting) setConfirmDelete(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete &ldquo;{confirmDelete?.name}&rdquo;?</DialogTitle>
            <DialogDescription>
              This permanently deletes the campaign and its send/open/click
              history. This cannot be undone. To keep it out of the way without
              losing data, use Archive instead.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmDelete(null)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
