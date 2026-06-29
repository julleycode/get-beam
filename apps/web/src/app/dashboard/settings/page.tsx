"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, Site, ApiKeyInfo } from "@/lib/api";
import { FormCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { CheckCircle2 } from "lucide-react";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
import { PixelUninstallGuide } from "@/components/pixel-uninstall-guide";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";

// Reusable "download your data before you leave" link shown inside each exit dialog.
function ExportDataLink({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      href="/dashboard/connectors"
      onClick={onNavigate}
      className="text-sm text-info hover:underline"
    >
      📥 Download your data before you go
    </Link>
  );
}

function formatPeriodEnd(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

const PROVIDERS = [
  {
    id: "openrouter",
    name: "OpenRouter",
    description: "AI replies — 100+ models (Grok, Llama, GPT-4o-mini, etc.)",
    docsUrl: "https://openrouter.ai/keys",
    color: "text-primary",
  },
  {
    id: "proxycurl",
    name: "Proxycurl",
    description: "LinkedIn profile enrichment",
    docsUrl: "https://nubela.co/proxycurl",
    color: "text-info",
  },
  {
    id: "twitter",
    name: "Twitter / X",
    description: "Twitter bio & followers",
    docsUrl: "https://developer.twitter.com",
    color: "text-info",
  },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [site, setSite] = useState<Site | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [siteRetryKey, setSiteRetryKey] = useState(0);
  const [snippet, setSnippet] = useState("");
  const [copied, setCopied] = useState(false);

  // Verify state
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{
    status: string;
    message: string;
  } | null>(null);

  // API Keys state
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([]);
  const [showAddKey, setShowAddKey] = useState(false);
  const [addProvider, setAddProvider] = useState("proxycurl");
  const [addKeyValue, setAddKeyValue] = useState("");
  const [addingKey, setAddingKey] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [keysLoadError, setKeysLoadError] = useState<string | null>(null);

  // Tracking pause (offboarding "soft" toggle)
  const [pauseBusy, setPauseBusy] = useState(false);
  const [pauseError, setPauseError] = useState<string | null>(null);

  // "Leaving Beam?" offboarding flows
  const [uninstallOpen, setUninstallOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelDone, setCancelDone] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId) return;
    setSiteError(null);
    api
      .getSite(siteId)
      .then(setSite)
      .catch((e: Error) => setSiteError(e.message));
    api
      .getPixelSnippet(siteId)
      .then((r) => setSnippet(r.snippet))
      .catch(() => {});
    setVerifyResult(null);
    setUninstallOpen(false);
    setCancelOpen(false);
    setCancelReason("");
    setCancelError(null);
    setCancelDone(null);
  }, [siteId, siteRetryKey]);

  // Load API keys (not site-specific)
  function loadApiKeys() {
    setKeysLoadError(null);
    api
      .listApiKeys()
      .then(setApiKeys)
      .catch((e: Error) => setKeysLoadError(e.message));
  }

  useEffect(loadApiKeys, []);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable (insecure origin / permission denied) — no-op
    }
  }

  async function handleVerify() {
    if (!siteId) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = await api.verifyPixel(siteId);
      setVerifyResult({ status: result.status, message: result.message });
      if (result.verified && site) {
        setSite({ ...site, pixel_verified: true });
      }
    } catch {
      setVerifyResult({
        status: "error",
        message: "Could not verify. Please try again.",
      });
    } finally {
      setVerifying(false);
    }
  }

  async function handleToggleTracking() {
    if (!siteId || !site) return;
    const next = !site.tracking_enabled;
    setPauseBusy(true);
    setPauseError(null);
    try {
      const updated = await api.updateSite(siteId, { tracking_enabled: next });
      setSite(updated);
    } catch (err) {
      setPauseError(err instanceof Error ? err.message : "Could not update");
    } finally {
      setPauseBusy(false);
    }
  }

  // Offboarding: pause directly from the "Leaving Beam?" card (reuses the same
  // backend toggle as the standalone pause Card — no duplicated logic).
  async function handlePauseFromExit() {
    if (!site || !site.tracking_enabled) return;
    if (!window.confirm("Pause tracking? The pixel stays on your site — turn it back on any time.")) {
      return;
    }
    await handleToggleTracking();
  }

  async function handleCancelSubscription() {
    setCancelBusy(true);
    setCancelError(null);
    try {
      const res = await api.cancelSubscription(cancelReason.trim() || undefined);
      setCancelDone(res.current_period_end);
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : "Couldn't cancel the plan");
    } finally {
      setCancelBusy(false);
    }
  }

  async function handleAddKey() {
    if (!addKeyValue.trim()) return;
    setAddingKey(true);
    setKeyError("");
    try {
      const saved = await api.saveApiKey(addProvider, addKeyValue.trim());
      setApiKeys((prev) => [
        ...prev.filter((k) => k.provider !== addProvider),
        saved,
      ]);
      setShowAddKey(false);
      setAddKeyValue("");
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setAddingKey(false);
    }
  }

  async function handleDeleteKey(provider: string) {
    try {
      await api.deleteApiKey(provider);
      setApiKeys((prev) => prev.filter((k) => k.provider !== provider));
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to delete key");
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader
        title="Settings"
        actions={<SiteSelector value={siteId} onChange={setSiteId} />}
      />

      {/* ── API Keys (BYOK) ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">API Keys (BYOK)</CardTitle>
          <CardDescription>
            Add your API keys to power AI replies (OpenRouter) and deep
            enrichment (LinkedIn, Twitter). Keys are encrypted at rest.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Existing keys */}
          {keysLoadError ? (
            <ErrorBanner
              message={`Couldn't load API keys — ${keysLoadError}`}
              onRetry={loadApiKeys}
            />
          ) : apiKeys.length > 0 ? (
            <div className="space-y-2">
              {apiKeys.map((key) => {
                const provider = PROVIDERS.find((p) => p.id === key.provider);
                return (
                  <div
                    key={key.provider}
                    className="flex items-center justify-between p-3 rounded-md bg-muted"
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`font-medium text-sm ${provider?.color || ""}`}
                      >
                        {provider?.name || key.provider}
                      </span>
                      <code className="text-xs text-muted-foreground">
                        {key.key_hint}
                      </code>
                      <StatusBadge status={key.is_valid ? "valid" : "invalid"} />
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => handleDeleteKey(key.provider)}
                    >
                      Remove
                    </Button>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No API keys configured. Add a key to unlock Tier 2 enrichment.
            </p>
          )}

          {/* Add key form */}
          {showAddKey ? (
            <div className="space-y-3 p-4 rounded-md border border-border">
              <div className="space-y-2">
                <label className="text-sm font-medium">Provider</label>
                <select
                  value={addProvider}
                  onChange={(e) => setAddProvider(e.target.value)}
                  className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border"
                >
                  {PROVIDERS.filter(
                    (p) => !apiKeys.find((k) => k.provider === p.id)
                  ).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — {p.description}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">API Key</label>
                <input
                  type="password"
                  value={addKeyValue}
                  onChange={(e) => setAddKeyValue(e.target.value)}
                  placeholder="Paste your API key here"
                  className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border font-mono"
                />
              </div>
              {keyError && (
                <p className="text-sm text-destructive">{keyError}</p>
              )}
              <div className="flex gap-2">
                <Button
                  onClick={handleAddKey}
                  disabled={!addKeyValue.trim() || addingKey}
                  size="sm"
                >
                  {addingKey ? "Validating..." : "Test & Save"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowAddKey(false);
                    setAddKeyValue("");
                    setKeyError("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddKey(true)}
              disabled={apiKeys.length >= PROVIDERS.length}
            >
              + Add API Key
            </Button>
          )}
        </CardContent>
      </Card>

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view settings.</p>
      ) : siteError ? (
        <ErrorBanner
          message={`Couldn't load site settings — ${siteError}`}
          onRetry={() => setSiteRetryKey((k) => k + 1)}
        />
      ) : !site ? (
        <div className="space-y-6">
          <FormCardSkeleton />
          <FormCardSkeleton fields={2} />
        </div>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Site Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name</span>
                <span>{site.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">URL</span>
                <span>{site.url}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Site ID</span>
                <span className="font-mono text-xs">{site.site_id}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Pixel verified</span>
                <div className="flex items-center gap-2">
                  {site.pixel_verified ? (
                    <span className="inline-flex items-center gap-1 font-medium text-success">
                      <CheckCircle2 className="h-4 w-4" />
                      Verified
                    </span>
                  ) : (
                    <>
                      <span className="text-warning">Not yet</span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleVerify}
                        disabled={verifying}
                      >
                        {verifying ? "Checking..." : "Verify Now"}
                      </Button>
                    </>
                  )}
                </div>
              </div>
              {verifyResult && (
                <p
                  className={`text-right text-xs ${
                    verifyResult.status === "verified"
                      ? "text-success"
                      : "text-warning"
                  }`}
                >
                  {verifyResult.message}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Pixel Snippet</CardTitle>
              <CardDescription>
                Paste this before the closing &lt;/head&gt; tag
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="relative">
                <pre className="rounded-md bg-muted p-4 text-xs overflow-x-auto whitespace-pre-wrap break-all">
                  {snippet}
                </pre>
                <Button
                  variant="outline"
                  size="sm"
                  className="absolute top-2 right-2"
                  onClick={handleCopy}
                >
                  {copied ? "Copied!" : "Copy"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Pause tracking</CardTitle>
              <CardDescription>
                Stop collecting data while keeping your plan, data, and pixel.
                Turn it back on any time — nothing is lost.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Status</span>
                  <StatusBadge
                    status={site.tracking_enabled ? "active" : "paused"}
                    label={site.tracking_enabled ? "Collecting" : "Paused"}
                  />
                </div>
                <Button
                  variant={site.tracking_enabled ? "outline" : "default"}
                  size="sm"
                  onClick={handleToggleTracking}
                  disabled={pauseBusy}
                >
                  {pauseBusy
                    ? "Saving…"
                    : site.tracking_enabled
                      ? "Pause tracking"
                      : "Resume tracking"}
                </Button>
              </div>
              {!site.tracking_enabled && (
                <p className="text-xs text-muted-foreground">
                  The pixel stays on your site — turn it back on any time.
                </p>
              )}
              {pauseError && (
                <p className="text-xs text-destructive">{pauseError}</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Budget Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">
                  Daily resolution budget
                </span>
                <span>{site.daily_resolution_budget} lookups/day</span>
              </div>
              <Separator />
              <p className="text-xs text-muted-foreground">
                Contact support to adjust budget limits. Billing dashboard
                coming soon.
              </p>
            </CardContent>
          </Card>

          {/* ── Leaving Beam? (offboarding — reassuring, not destructive) ── */}
          <Card className="border-warning">
            <CardHeader>
              <CardTitle className="text-base">Leaving Beam?</CardTitle>
              <CardDescription>
                We keep your account and data — you can come back any time.
                Pick what fits, from gentle to final.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {/* 1. Pause (softest) — reuse pause toggle above */}
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-foreground">Pause tracking</p>
                  <p className="text-muted-foreground">
                    Not sure yet? Just pause collection and keep everything as is.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={handlePauseFromExit}
                  disabled={pauseBusy || !site.tracking_enabled}
                >
                  {!site.tracking_enabled
                    ? "Paused"
                    : pauseBusy
                      ? "Saving…"
                      : "Pause"}
                </Button>
              </div>

              <Separator />

              {/* 2. Remove pixel */}
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-foreground">Remove pixel</p>
                  <p className="text-muted-foreground">
                    A guide to take the snippet off your site — reinstall any time.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={() => setUninstallOpen(true)}
                >
                  Remove pixel
                </Button>
              </div>

              <Separator />

              {/* 3. Cancel plan (most final) */}
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium text-foreground">Cancel plan</p>
                  <p className="text-muted-foreground">
                    Drop to Free at the end of the period. Account and data are kept.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={() => {
                    setCancelDone(null);
                    setCancelError(null);
                    setCancelOpen(true);
                  }}
                >
                  Cancel plan
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Remove pixel dialog */}
          <Dialog open={uninstallOpen} onOpenChange={setUninstallOpen}>
            <DialogContent className="max-h-[85vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>Remove the pixel from your site</DialogTitle>
                <DialogDescription>
                  Follow the steps below to take the pixel off. Data you&apos;ve
                  already collected is kept.
                </DialogDescription>
              </DialogHeader>
              <PixelUninstallGuide
                platform={site.detected_platform ?? "unknown"}
                snippet={snippet}
                siteId={site.site_id}
              />
              <DialogFooter className="sm:justify-start">
                <ExportDataLink onNavigate={() => setUninstallOpen(false)} />
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* Cancel plan dialog */}
          <Dialog
            open={cancelOpen}
            onOpenChange={(o) => {
              if (!cancelBusy) setCancelOpen(o);
            }}
          >
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Cancel plan?</DialogTitle>
                <DialogDescription>
                  {cancelDone !== null ? (
                    <>
                      Cancellation requested. Your plan stays active
                      {cancelDone ? (
                        <>
                          {" "}until{" "}
                          <span className="font-medium text-foreground">
                            {formatPeriodEnd(cancelDone)}
                          </span>
                        </>
                      ) : (
                        " until the end of the current billing period"
                      )}
                      , then drops to Free. Your account and data are kept — come
                      back any time.
                    </>
                  ) : (
                    <>
                      Your plan drops to Free at the end of the current billing
                      period. Your account and data are kept — you can resubscribe
                      any time.
                    </>
                  )}
                </DialogDescription>
              </DialogHeader>

              {cancelDone === null && (
                <div className="space-y-2">
                  <label
                    htmlFor="cancel-reason"
                    className="text-sm font-medium"
                  >
                    Why are you leaving? (optional)
                  </label>
                  <textarea
                    id="cancel-reason"
                    value={cancelReason}
                    onChange={(e) => setCancelReason(e.target.value)}
                    rows={3}
                    placeholder="Your feedback helps make Beam better…"
                    className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border resize-none"
                    disabled={cancelBusy}
                  />
                  {cancelError && (
                    <p className="text-sm text-destructive">{cancelError}</p>
                  )}
                  <ExportDataLink onNavigate={() => setCancelOpen(false)} />
                </div>
              )}

              <DialogFooter>
                {cancelDone === null ? (
                  <>
                    <Button
                      variant="outline"
                      onClick={() => setCancelOpen(false)}
                      disabled={cancelBusy}
                    >
                      Keep plan
                    </Button>
                    <Button onClick={handleCancelSubscription} disabled={cancelBusy}>
                      {cancelBusy ? "Cancelling…" : "Confirm cancellation"}
                    </Button>
                  </>
                ) : (
                  <Button onClick={() => setCancelOpen(false)}>Got it</Button>
                )}
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}
