"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { SocialAccountsHelp } from "@/components/page-help";
import { api, type Platform } from "@/lib/api";
import { LinkedInConnectWizard } from "@/components/linkedin-connect-wizard";
import { LinkedInTosWarning } from "@/components/linkedin-tos-warning";
import {
  useLinkedInExtensionStatus,
  WIZARD_REOPEN_PARAM,
} from "@/lib/use-linkedin-extension-status";
import { ListCardSkeleton } from "@/components/skeletons";
import { ErrorBanner } from "@/components/error-banner";
import { PlatformBadge } from "@/components/platform-badge";
import {
  ConnectionHealthBadge,
  connectionHealth,
} from "@/components/connection-health";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const ALL_PLATFORMS: { platform: Platform; label: string; color: string }[] = [
  { platform: "twitter", label: "Twitter / X", color: "bg-sky-500" },
  { platform: "facebook", label: "Facebook", color: "bg-blue-600" },
  { platform: "instagram", label: "Instagram", color: "bg-pink-500" },
  { platform: "linkedin", label: "LinkedIn", color: "bg-blue-700" },
  { platform: "tiktok", label: "TikTok", color: "bg-gray-900" },
];

function SocialAccountsPageInner() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();

  const { data: accounts, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["social-accounts"],
    queryFn: () => api.getSocialAccounts(),
  });

  const connectMut = useMutation({
    mutationFn: (platform: Platform) => api.connectPlatform(platform),
    onSuccess: (data) => {
      window.open(data.auth_url, "_blank");
    },
    onError: (error: Error, platform: Platform) => {
      const name =
        ALL_PLATFORMS.find((p) => p.platform === platform)?.label ?? platform;
      // Backend returns a "missing credentials" 400 when the platform's API keys
      // aren't configured yet. Translate that dev-facing message into something
      // an end user can act on, and fall back to the raw error otherwise.
      const notConfigured = /credential/i.test(error.message);
      alert(
        notConfigured
          ? `${name} isn't available to connect yet. Its API keys haven't been set up. An admin needs to add them before you can connect ${name}.`
          : error.message || `Couldn't connect ${name}. Please try again in a moment.`
      );
    },
  });

  const disconnectMut = useMutation({
    mutationFn: (accountId: string) => api.disconnectAccount(accountId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["social-accounts"] }),
  });

  const connectedPlatforms = new Set(accounts?.map((a) => a.platform) ?? []);

  // ── LinkedIn outreach (advanced) ──
  const [liCookie, setLiCookie] = useState("");
  const [liUserAgent, setLiUserAgent] = useState("");
  // Pre-fill from this browser — the cookie is almost always copied in the
  // same browser the dashboard is open in. useEffect (not initial state)
  // because navigator is unavailable during SSR.
  useEffect(() => {
    setLiUserAgent((prev) => prev || navigator.userAgent);
  }, []);
  const { data: outreachStatus } = useQuery({
    queryKey: ["linkedin-outreach-status"],
    queryFn: () => api.getLinkedInOutreachStatus(),
  });
  const outreachMut = useMutation({
    mutationFn: () =>
      api.enableLinkedInOutreach(liCookie.trim(), liUserAgent.trim()),
    onSuccess: () => {
      setLiCookie("");
      queryClient.invalidateQueries({ queryKey: ["linkedin-outreach-status"] });
    },
  });

  // ── LinkedIn outreach via the Beam browser extension ──
  // All extension state (detection, the D6/D7 nonce channels, the read-only
  // signed-in probe, and the one-click connect) lives in one shared hook.
  //
  // THIS IS THE ONLY CALL SITE. The wizard below receives the state as props —
  // a second live hook instance would double-register the D6 nonce and silently
  // break the popup-relay path (see the hook's header comment).
  const linkedInExt = useLinkedInExtensionStatus();

  // Wizard dialog. `?connectLinkedIn=1` reopens it after the install step's
  // page reload; the param is stripped so a plain refresh doesn't re-trigger it.
  const [wizardOpen, setWizardOpen] = useState(false);
  const [manualFormOpen, setManualFormOpen] = useState(false);
  const manualFormRef = useRef<HTMLDetailsElement | null>(null);
  const reopenParam = searchParams.get(WIZARD_REOPEN_PARAM);

  useEffect(() => {
    if (reopenParam !== "1") return;
    setWizardOpen(true);
    router.replace("/dashboard/social-accounts");
  }, [reopenParam, router]);

  const showManualForm = () => {
    setManualFormOpen(true);
    requestAnimationFrame(() => {
      manualFormRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="flex items-center gap-1.5 text-2xl font-serif font-semibold tracking-tight">
        Connected Accounts
        <InfoTooltip label="About Connected Accounts" align="start">
          <SocialAccountsHelp />
        </InfoTooltip>
      </h1>

      {isLoading ? (
        <ListCardSkeleton rows={3} leading />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load accounts: ${error?.message ?? "request failed"}`}
          onRetry={() => refetch()}
        />
      ) : accounts && accounts.length > 0 ? (
        <div className="space-y-3">
          {accounts.map((account) => {
            const health = connectionHealth(account);
            return (
              <div
                key={account.id}
                className="bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between gap-3"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-sm font-bold">
                    {account.username.charAt(0).toUpperCase()}
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{account.username}</p>
                    <div className="flex items-center gap-2">
                      <PlatformBadge platform={account.platform} />
                      {!account.is_outreach && (
                        <ConnectionHealthBadge health={health} />
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {/* Reconnect re-runs the OAuth connect flow. The callback upserts
                      by (platform, platform_user_id, user) so the SAME account row is
                      refreshed — no duplicate. Outreach (cookie) accounts have no
                      OAuth token, so use the LinkedIn outreach form to refresh those. */}
                  {!account.is_outreach && (
                    <button
                      onClick={() => connectMut.mutate(account.platform)}
                      disabled={connectMut.isPending}
                      className={`text-xs px-3 py-1.5 rounded-md border ${
                        health === "connected"
                          ? "border-gray-200 text-gray-600 hover:bg-gray-50"
                          : "border-[#FFA8BD] bg-[#FFF1F5] text-[#c2185b] font-medium hover:bg-[#ffe4ec]"
                      }`}
                    >
                      Reconnect
                    </button>
                  )}
                  <button
                    onClick={() => disconnectMut.mutate(account.id)}
                    disabled={disconnectMut.isPending}
                    className="text-xs px-3 py-1.5 rounded-md border border-red-200 text-red-600 hover:bg-red-50"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-gray-400">
          No accounts connected yet. Connect one below.
        </p>
      )}

      <div>
        <h2 className="text-lg font-semibold mb-3">Connect a Platform</h2>
        <div className="grid grid-cols-2 gap-3">
          {ALL_PLATFORMS.map(({ platform, label, color }) => {
            const connected = connectedPlatforms.has(platform);
            return (
              <button
                key={platform}
                onClick={() => !connected && connectMut.mutate(platform)}
                disabled={connected || connectMut.isPending}
                className={`flex items-center gap-3 p-4 rounded-lg border text-left transition-colors ${
                  connected
                    ? "border-green-200 bg-green-50 cursor-default"
                    : "border-gray-200 bg-white hover:border-[#FFA8BD] hover:bg-[#FFF1F5]"
                }`}
              >
                <div
                  className={`w-8 h-8 rounded-md ${color} flex items-center justify-center text-white text-xs font-bold`}
                >
                  {label.charAt(0)}
                </div>
                <div>
                  <p className="text-sm font-medium">{label}</p>
                  <p className="text-xs text-gray-400">
                    {connected ? "Connected" : "Click to connect"}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            LinkedIn outreach
            <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
              Advanced
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Lets Beam send real LinkedIn connection requests from your account
            for a campaign&apos;s LinkedIn step. Your login key is stored
            encrypted in the outreach service. Beam never keeps a copy and never
            shows it again.
          </p>
          <LinkedInTosWarning />

          {/* Guided wizard — the primary entry point. Only offered on browsers
              that can actually run the extension; Firefox/Safari fall straight
              through to the manual form below (AC9/AC12). */}
          {linkedInExt.isChromeOrEdge && (
            <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
              <p className="text-sm font-medium text-foreground">
                Guided setup (about a minute)
              </p>
              <p className="text-xs text-muted-foreground">
                Walks you through it step by step. No copying anything by hand.
              </p>
              <Button type="button" onClick={() => setWizardOpen(true)}>
                {outreachStatus?.outreach_connected
                  ? "Reconnect LinkedIn"
                  : "Connect LinkedIn"}
              </Button>
            </div>
          )}

          {/* Extension path (additive). Renders only when the Beam extension is
              detected; always sits BELOW the ToS warning above (AC7), never
              bypassing it. The manual form below always renders regardless. */}
          {linkedInExt.extensionDetected && (
            <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
              <p className="text-sm font-medium text-foreground">
                Beam extension detected
              </p>
              <p className="text-xs text-muted-foreground">
                Skip the manual steps below. Connect your LinkedIn session in
                one click.
              </p>
              <Button
                type="button"
                onClick={linkedInExt.connect}
                disabled={
                  linkedInExt.isPending || outreachStatus?.configured === false
                }
              >
                {linkedInExt.isPending
                  ? "Connecting..."
                  : outreachStatus?.outreach_connected
                    ? "Refresh connection with extension"
                    : "Connect with extension"}
              </Button>
              {linkedInExt.error && (
                <p className="text-sm text-destructive">{linkedInExt.error}</p>
              )}
              {linkedInExt.isConnected && (
                <p className="text-sm text-success">Connected via extension.</p>
              )}
            </div>
          )}

          {outreachStatus?.outreach_connected ? (
            <div className="rounded-md border border-success/30 bg-success/10 p-3 text-sm text-success">
              LinkedIn outreach is connected. You can re-paste a fresh cookie
              below to update it.
            </div>
          ) : outreachStatus && !outreachStatus.configured ? (
            <div className="rounded-md border border-border bg-muted p-3 text-sm text-muted-foreground">
              LinkedIn outreach is not enabled on this server yet. Ask your admin
              to configure the outreach service.
            </div>
          ) : null}

          {/* Manual paste form — de-emphasized as the advanced/fallback path, but
              always reachable (AC12) and the ONLY path on Firefox/Safari (D12).
              Kept expanded until the one-click extension path is actually
              available, so a user with no working alternative is never left
              staring at a collapsed section. */}
          <details
            ref={manualFormRef}
            open={!linkedInExt.extensionDetected || manualFormOpen}
            onToggle={(e) => setManualFormOpen(e.currentTarget.open)}
            className="rounded-md border border-border px-3 py-2 [&[open]>summary]:mb-3"
          >
            <summary className="cursor-pointer select-none text-sm font-medium text-foreground">
              Advanced: paste your login key manually
            </summary>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (liCookie.trim() && liUserAgent.trim() && !outreachMut.isPending) {
                outreachMut.mutate();
              }
            }}
            className="space-y-3"
          >
            <div className="space-y-1.5">
              <Label htmlFor="li-cookie">
                LinkedIn login key{" "}
                <span className="font-normal text-muted-foreground">
                  (the &quot;li_at&quot; cookie)
                </span>
              </Label>
              <Textarea
                id="li-cookie"
                value={liCookie}
                onChange={(e) => setLiCookie(e.target.value)}
                placeholder="Looks like: AQEDAxxxxxxxxxxxxxxx…"
                rows={2}
                autoComplete="off"
                disabled={outreachMut.isPending}
              />
              <details className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground [&[open]>summary]:mb-2">
                <summary className="cursor-pointer select-none font-medium text-foreground">
                  How to find your login key (about 1 minute)
                </summary>
                <ol className="list-decimal space-y-1.5 pl-4">
                  <li>
                    Open <span className="font-medium">linkedin.com</span> in this browser
                    and make sure you&apos;re signed in.
                  </li>
                  <li>
                    Press <kbd className="rounded border border-border bg-background px-1 font-mono">F12</kbd>{" "}
                    (Windows) or{" "}
                    <kbd className="rounded border border-border bg-background px-1 font-mono">⌥⌘I</kbd>{" "}
                    (Mac). A technical panel opens. Don&apos;t worry, you can&apos;t break anything.
                  </li>
                  <li>
                    At the top of that panel, click the{" "}
                    <span className="font-medium">Application</span> tab (Chrome/Edge) or{" "}
                    <span className="font-medium">Storage</span> tab (Firefox/Safari). Then in
                    the left list, open <span className="font-medium">Cookies</span> →{" "}
                    <span className="font-medium">https://www.linkedin.com</span>.
                  </li>
                  <li>
                    In the table, find the row named{" "}
                    <span className="font-mono font-medium">li_at</span>. Double-click its{" "}
                    <span className="font-medium">Value</span>, copy it, and paste it above.
                  </li>
                </ol>
              </details>
            </div>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer select-none">
                Browser details (filled in automatically)
              </summary>
              <div className="mt-2 space-y-1.5">
                <Label htmlFor="li-ua">Browser User-Agent</Label>
                <Input
                  id="li-ua"
                  value={liUserAgent}
                  onChange={(e) => setLiUserAgent(e.target.value)}
                  placeholder="Mozilla/5.0 (...) Chrome/... Safari/..."
                  autoComplete="off"
                  disabled={outreachMut.isPending}
                />
                <p className="text-xs text-muted-foreground">
                  We detected this from your current browser. Only change it if you
                  copied the login key in a different browser.
                </p>
              </div>
            </details>

            {outreachMut.isError && (
              <p className="text-sm text-destructive">
                Couldn&apos;t connect LinkedIn outreach:{" "}
                {(outreachMut.error as Error)?.message ?? "request failed"}
              </p>
            )}
            {outreachMut.isSuccess && (
              <p className="text-sm text-success">
                Connected
                {outreachMut.data?.name ? ` as ${outreachMut.data.name}` : ""}.
              </p>
            )}

            <Button
              type="submit"
              disabled={
                outreachMut.isPending ||
                !liCookie.trim() ||
                !liUserAgent.trim() ||
                outreachStatus?.configured === false
              }
            >
              {outreachMut.isPending
                ? "Connecting..."
                : outreachStatus?.outreach_connected
                  ? "Update session"
                  : "Enable LinkedIn outreach"}
            </Button>
          </form>
          </details>
        </CardContent>
      </Card>

      <LinkedInConnectWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        serverConfigured={outreachStatus?.configured !== false}
        alreadyConnected={!!outreachStatus?.outreach_connected}
        onShowManualForm={showManualForm}
        {...linkedInExt}
      />
    </div>
  );
}

export default function SocialAccountsPage() {
  // useSearchParams (the wizard reopen param) needs a Suspense boundary — same
  // pattern as the onboarding page's resume params.
  return (
    <Suspense
      fallback={<ListCardSkeleton rows={3} leading />}
    >
      <SocialAccountsPageInner />
    </Suspense>
  );
}
