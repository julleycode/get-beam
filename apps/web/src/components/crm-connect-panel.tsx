"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, CrmConnection, CrmProvider, Segment } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/empty-state";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Plug, Unplug } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";

// OAuth CRMs. HubSpot ships now; the rest are wired server-side later — shown
// disabled so the surface is discoverable without promising a broken click.
const OAUTH_CRMS: { provider: CrmProvider; name: string; ready: boolean }[] = [
  { provider: "hubspot", name: "HubSpot", ready: true },
  { provider: "pipedrive", name: "Pipedrive", ready: true },
  { provider: "salesforce", name: "Salesforce", ready: true },
];

function toneFor(status: string): "success" | "warning" | "destructive" | "neutral" {
  if (status === "connected") return "success";
  if (status === "error") return "destructive";
  if (status === "pending") return "warning";
  return "neutral";
}

export function CrmConnectPanel({
  siteId,
  segments,
}: {
  siteId: string;
  segments: Segment[];
}) {
  const searchParams = useSearchParams();
  const [connections, setConnections] = useState<CrmConnection[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Generic-webhook form
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");

  // Push dialog
  const [pushFor, setPushFor] = useState<CrmConnection | null>(null);
  const [pushSegment, setPushSegment] = useState("");

  const load = useCallback(() => {
    if (!siteId) return;
    api
      .listCrmConnections(siteId)
      .then((c) => setConnections(c))
      .catch(() => setConnections([]))
      .finally(() => setLoaded(true));
  }, [siteId]);

  useEffect(() => {
    setLoaded(false);
    setMsg(null);
    load();
  }, [load]);

  // Surface the result of an OAuth round-trip (?crm=connected|error).
  useEffect(() => {
    const crm = searchParams.get("crm");
    if (crm === "connected") setMsg("CRM connected.");
    else if (crm === "error") setMsg("Couldn't connect that CRM — please try again.");
  }, [searchParams]);

  const connectionFor = (provider: CrmProvider) =>
    connections.find((c) => c.provider === provider);

  async function handleConnectOAuth(provider: CrmProvider) {
    if (!siteId) return;
    setBusy(provider);
    setMsg(null);
    try {
      const { auth_url } = await api.connectCrm(siteId, provider);
      window.location.href = auth_url; // hand off to the provider's consent screen
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Couldn't start the connection");
      setBusy(null);
    }
  }

  async function handleSaveWebhook() {
    if (!siteId || !webhookUrl || webhookSecret.length < 8) return;
    setBusy("generic_webhook");
    setMsg(null);
    try {
      await api.saveGenericWebhook(siteId, webhookUrl, webhookSecret);
      setWebhookUrl("");
      setWebhookSecret("");
      setMsg("Webhook saved.");
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Couldn't save the webhook");
    } finally {
      setBusy(null);
    }
  }

  async function handleTest(conn: CrmConnection) {
    setBusy(conn.provider);
    setMsg(null);
    try {
      const r = await api.testCrmConnection(siteId, conn.provider);
      setMsg(r.message);
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleDisconnect(conn: CrmConnection) {
    if (!window.confirm(`Disconnect ${conn.provider.replace(/_/g, " ")}?`)) return;
    setBusy(conn.provider);
    setMsg(null);
    try {
      await api.disconnectCrm(siteId, conn.provider);
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Couldn't disconnect");
    } finally {
      setBusy(null);
    }
  }

  async function handlePush() {
    if (!pushFor || !pushSegment) return;
    const provider = pushFor.provider;
    setBusy(provider);
    setMsg(null);
    setPushFor(null);
    try {
      const r = await api.pushSegmentToCrm(siteId, provider, pushSegment);
      setMsg(
        r.queued
          ? "Push queued — running in the background."
          : `Pushed ${r.pushed}, failed ${r.failed}, skipped ${r.skipped}` +
              (r.errors.length ? ` — ${r.errors[0]}` : "") +
              "."
      );
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Push failed");
    } finally {
      setBusy(null);
      setPushSegment("");
    }
  }

  if (!siteId) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-muted-foreground">Select a site first.</p>
        </CardContent>
      </Card>
    );
  }

  const webhookConn = connectionFor("generic_webhook");

  return (
    <div className="space-y-6">
      {msg && (
        <p className="text-sm text-foreground" role="status">
          {msg}
        </p>
      )}

      {loaded && connections.length === 0 && (
        <EmptyState
          icon={Plug}
          title="No CRM connected yet"
          description="Connect a CRM below to push identified visitors straight into your pipeline — no CSV round-trips."
        />
      )}

      {/* Active connections */}
      {connections.map((conn) => (
        <Card key={conn.provider}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base capitalize">
                {conn.external_account_label || conn.provider.replace(/_/g, " ")}
              </CardTitle>
              <StatusBadge status={conn.status} tone={toneFor(conn.status)} />
            </div>
            {conn.webhook_url && (
              <CardDescription className="truncate">{conn.webhook_url}</CardDescription>
            )}
            {conn.last_error && conn.status === "error" && (
              <CardDescription className="text-destructive">
                {conn.last_error}
              </CardDescription>
            )}
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={busy === conn.provider || segments.length === 0}
              onClick={() => {
                setPushFor(conn);
                setPushSegment("");
              }}
            >
              Push segment
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === conn.provider}
              onClick={() => handleTest(conn)}
            >
              {busy === conn.provider ? "Working…" : "Test"}
            </Button>
            <IconButton
              label="Disconnect"
              danger
              disabled={busy === conn.provider}
              onClick={() => handleDisconnect(conn)}
            >
              <Unplug className="h-4 w-4" />
            </IconButton>
          </CardContent>
        </Card>
      ))}

      {/* Connect a new OAuth CRM */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Connect a CRM</CardTitle>
          <CardDescription>
            Authorize Beam to sync contacts into your CRM.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {OAUTH_CRMS.map(({ provider, name, ready }) => {
            const connected = !!connectionFor(provider);
            return (
              <Button
                key={provider}
                variant="outline"
                size="sm"
                disabled={!ready || connected || busy === provider}
                onClick={() => handleConnectOAuth(provider)}
              >
                {connected
                  ? `${name} connected`
                  : ready
                    ? `Connect ${name}`
                    : `${name} — coming soon`}
              </Button>
            );
          })}
        </CardContent>
      </Card>

      {/* Generic webhook */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Webhook</CardTitle>
          <CardDescription>
            Send contacts to any URL (Zapier, Make, or your own endpoint). Each
            request is signed with your secret in the{" "}
            <code className="text-xs">X-Beam-Signature</code> header.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {webhookConn && (
            <p className="text-sm text-muted-foreground">
              Current: {webhookConn.webhook_url} (secret {webhookConn.secret_hint})
            </p>
          )}
          <div className="space-y-2">
            <label className="text-sm font-medium">Webhook URL</label>
            <Input
              type="url"
              placeholder="https://hooks.example.com/beam"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Signing secret</label>
            <Input
              type="password"
              placeholder="At least 8 characters"
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
            />
          </div>
          <Button
            size="sm"
            disabled={
              busy === "generic_webhook" || !webhookUrl || webhookSecret.length < 8
            }
            onClick={handleSaveWebhook}
          >
            {busy === "generic_webhook" ? "Saving…" : webhookConn ? "Update webhook" : "Save webhook"}
          </Button>
        </CardContent>
      </Card>

      {/* Push-segment confirmation */}
      <Dialog open={!!pushFor} onOpenChange={(open) => !open && setPushFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Push a segment</DialogTitle>
            <DialogDescription>
              Send every identified, emailable contact in a segment to{" "}
              {pushFor?.external_account_label || pushFor?.provider.replace(/_/g, " ")}.
              Suppressed and unsubscribed contacts are skipped automatically.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-sm font-medium">Segment</label>
            <Select value={pushSegment} onValueChange={setPushSegment}>
              <SelectTrigger>
                <SelectValue placeholder="Select segment" />
              </SelectTrigger>
              <SelectContent>
                {segments.map((seg) => (
                  <SelectItem key={seg.id} value={seg.id}>
                    {seg.name} ({seg.visitor_count} visitors)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPushFor(null)}>
              Cancel
            </Button>
            <Button disabled={!pushSegment} onClick={handlePush}>
              Push now
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
