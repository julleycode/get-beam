"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, AdConnection, AdProvider, Segment } from "@/lib/api";
import { Button } from "@/components/ui/button";
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
import { Megaphone, Unplug } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";

// Ad platforms. Meta + Google ship a live connect flow; LinkedIn has no usable
// Matched Audiences API for us, so it stays disabled — discoverable without
// promising a broken click. The CSV export below still covers LinkedIn.
const OAUTH_ADS: { provider: AdProvider; name: string; ready: boolean }[] = [
  { provider: "meta", name: "Meta Custom Audiences", ready: true },
  { provider: "google", name: "Google Customer Match", ready: true },
  { provider: "linkedin", name: "LinkedIn Matched Audiences", ready: false },
];

// AC7 pre-push warning threshold. Kept in sync by hand with
// ads_push.MIN_AUDIENCE_SIZE — the exact post-push number comes back on the
// push response (`minimum_threshold`); this constant only drives the
// approximate warning shown BEFORE the user confirms.
const MIN_AUDIENCE_SIZE = 1000;
const MIN_AUDIENCE_MATCHABLE = 100;

function toneFor(status: string): "success" | "warning" | "destructive" | "neutral" {
  if (status === "connected") return "success";
  if (status === "error") return "destructive";
  if (status === "pending") return "warning";
  return "neutral";
}

export function AdConnectPanel({
  siteId,
  segments,
}: {
  siteId: string;
  segments: Segment[];
}) {
  const searchParams = useSearchParams();
  const [connections, setConnections] = useState<AdConnection[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  // Push dialog
  const [pushFor, setPushFor] = useState<AdConnection | null>(null);
  const [pushSegment, setPushSegment] = useState("");

  const load = useCallback(() => {
    if (!siteId) return;
    api
      .listAdConnections(siteId)
      .then((c) => setConnections(c))
      .catch(() => setConnections([]))
      .finally(() => setLoaded(true));
  }, [siteId]);

  useEffect(() => {
    setLoaded(false);
    setMsg(null);
    load();
  }, [load]);

  // Surface the result of an OAuth round-trip (?ads=connected|error).
  useEffect(() => {
    const ads = searchParams.get("ads");
    if (ads === "connected") setMsg("Ad account connected.");
    else if (ads === "error")
      setMsg("Couldn't connect that ad account. Please try again.");
  }, [searchParams]);

  const connectionFor = (provider: AdProvider) =>
    connections.find((c) => c.provider === provider);

  // The selected segment, only when it's small enough to warrant the AC7
  // pre-push warning (null otherwise, so the banner simply doesn't render).
  const selected = segments.find((s) => s.id === pushSegment);
  const selectedSegmentSmall =
    selected && selected.visitor_count < MIN_AUDIENCE_SIZE ? selected : null;

  async function handleConnect(provider: AdProvider) {
    if (!siteId) return;
    setBusy(provider);
    setMsg(null);
    try {
      const { auth_url } = await api.connectAdProvider(siteId, provider);
      window.location.href = auth_url; // hand off to the platform's consent screen
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Couldn't start the connection");
      setBusy(null);
    }
  }

  async function handleTest(conn: AdConnection) {
    setBusy(conn.provider);
    setMsg(null);
    try {
      const r = await api.testAdConnection(siteId, conn.provider);
      setMsg(r.message);
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleDisconnect(conn: AdConnection) {
    if (!window.confirm(`Disconnect ${conn.provider}?`)) return;
    setBusy(conn.provider);
    setMsg(null);
    try {
      await api.disconnectAdProvider(siteId, conn.provider);
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
      const r = await api.pushAdSegment(siteId, provider, pushSegment);
      // AC7 post-push: prefer the backend's exact copy; if the response only
      // carries the structured flags, build the same sentence from the real
      // threshold rather than a hardcoded number.
      const sizeNote = r.warning
        ? ` ${r.warning}`
        : r.below_minimum
          ? ` This audience is below the ~${(
              r.minimum_threshold || MIN_AUDIENCE_SIZE
            ).toLocaleString()} matched contacts ad platforms typically need for reliable targeting, but the push still went through.`
          : "";
      setMsg(
        r.queued
          ? "Push queued, running in the background."
          : `Pushed ${r.pushed}, failed ${r.failed}, skipped ${r.skipped}.` +
              sizeNote +
              (r.errors.length ? ` (${r.errors[0]})` : "")
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

  return (
    <div className="space-y-6">
      {msg && (
        <p className="text-sm text-foreground" role="status">
          {msg}
        </p>
      )}

      {loaded && connections.length === 0 && (
        <EmptyState
          icon={Megaphone}
          title="No ad account connected yet"
          description="Connect an ad account below to push a segment straight into a custom audience, no CSV round-trips. Only hashed identifiers ever leave Beam."
        />
      )}

      {/* Active connections */}
      {connections.map((conn) => (
        <Card key={conn.provider}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base capitalize">
                {conn.external_account_label || conn.provider}
              </CardTitle>
              <StatusBadge status={conn.status} tone={toneFor(conn.status)} />
            </div>
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

      {/* Connect a new ad account */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Connect an ad account</CardTitle>
          <CardDescription>
            Authorize Beam to sync segments into your ad platform as a custom
            audience. Emails are hashed before they leave Beam.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {OAUTH_ADS.map(({ provider, name, ready }) => {
            const connected = !!connectionFor(provider);
            return (
              <Button
                key={provider}
                variant="outline"
                size="sm"
                disabled={!ready || connected || busy === provider}
                onClick={() => handleConnect(provider)}
              >
                {connected
                  ? `${name} connected`
                  : ready
                    ? `Connect ${name}`
                    : `${name} (coming soon)`}
              </Button>
            );
          })}
        </CardContent>
      </Card>

      {/* Push-segment confirmation */}
      <Dialog open={!!pushFor} onOpenChange={(open) => !open && setPushFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Push a segment</DialogTitle>
            <DialogDescription>
              Send every identified, emailable contact in a segment to{" "}
              {pushFor?.external_account_label || pushFor?.provider} as a custom
              audience. Suppressed and unsubscribed contacts are skipped
              automatically, and only hashed identifiers are sent. Ad platforms
              accept audiences from about {MIN_AUDIENCE_MATCHABLE} matched
              contacts, but typically need around{" "}
              {MIN_AUDIENCE_SIZE.toLocaleString()} before targeting works well.
            </DialogDescription>
          </DialogHeader>

          {/* AC7 pre-push warning. `visitor_count` is an APPROXIMATE estimate
              taken before the safety filters run, so the real matched count is
              usually lower — the exact number arrives in the push response. */}
          {selectedSegmentSmall && (
            <p className="text-sm text-amber-600" role="alert" data-testid="ads-pre-push-warning">
              Heads up: this segment has about{" "}
              {selectedSegmentSmall.visitor_count.toLocaleString()} visitors,
              below the ~{MIN_AUDIENCE_SIZE.toLocaleString()} that ad platforms
              usually need for reliable targeting, and the matched count after
              filtering will be lower still. You can push anyway, or cancel and
              pick a larger segment.
            </p>
          )}
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
