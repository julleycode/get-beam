"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Platform } from "@/lib/api";
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

export default function SocialAccountsPage() {
  const queryClient = useQueryClient();

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
          ? `${name} isn't available to connect yet — its API keys haven't been set up. An admin needs to add them before you can connect ${name}.`
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

  // ── LinkedIn outreach via the Beam browser extension (additive) ──
  // The manual cookie-paste form above always stays as the fallback. The
  // extension is a "dumb pipe": it hands us the li_at cookie + UA over a
  // locally-scoped, nonce-verified message channel, and we call the SAME
  // existing enableLinkedInOutreach endpoint. No backend change.
  //
  // KEEP IN SYNC with apps/extension/src/known-origins.js
  // (KNOWN_EXTENSION_ID / BEAM_ORIGINS / MESSAGE_SOURCE). These are two separate
  // build targets with no shared package, so the constants are duplicated.
  // KNOWN_EXTENSION_ID stays a placeholder until the extension's first Chrome
  // Web Store upload assigns the real id (plan OI-4 / Step 9).
  const KNOWN_EXTENSION_ID = "PENDING_STORE_LISTING";
  const EXTENSION_MESSAGE_SOURCE = "beam-extension";

  const [extensionDetected, setExtensionDetected] = useState(false);
  const [extensionError, setExtensionError] = useState<string | null>(null);
  // Per-page-load nonce. Registered with the extension over the Chrome
  // sender-verified channel; the popup-relay (D7) message must echo it back or
  // we reject it, so a co-resident copy-cat extension cannot forge a response
  // (plan D10 / OI-3). Never rendered into the DOM or a CustomEvent.
  const [extensionNonce] = useState(() =>
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2)
  );

  const extensionMut = useMutation({
    mutationFn: (creds: { cookie: string; userAgent: string }) =>
      api.enableLinkedInOutreach(creds.cookie, creds.userAgent),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["linkedin-outreach-status"] });
    },
    onError: (err: Error) => {
      setExtensionError(err.message || "Couldn't connect via the extension.");
    },
  });

  // Never log the cookie / userAgent / raw response anywhere (plan AC8).
  const handleExtensionResult = (data: {
    ok?: boolean;
    cookie?: string;
    userAgent?: string;
    reason?: string;
  }) => {
    if (!data.ok || !data.cookie) {
      setExtensionError(
        data.reason === "not_signed_in"
          ? "You're not signed into LinkedIn in this browser. Sign in at linkedin.com, then try again."
          : "Couldn't read your LinkedIn login. Make sure you're signed in at linkedin.com."
      );
      return;
    }
    setExtensionError(null);
    extensionMut.mutate({
      cookie: data.cookie,
      userAgent: data.userAgent || navigator.userAgent,
    });
  };

  // Primary channel (D6): page → extension via externally_connectable. Same
  // one-click flow is reused for first connect and refresh/reconnect (AC10).
  const connectViaExtension = () => {
    setExtensionError(null);
    try {
      window.chrome?.runtime?.sendMessage(
        KNOWN_EXTENSION_ID,
        { type: "beam-connect-request" },
        (response) => {
          if (window.chrome?.runtime?.lastError || !response) {
            setExtensionError(
              "Couldn't reach the Beam extension. Is it installed and enabled?"
            );
            return;
          }
          handleExtensionResult(
            response as {
              ok?: boolean;
              cookie?: string;
              userAgent?: string;
              reason?: string;
            }
          );
        }
      );
    } catch {
      setExtensionError(
        "Couldn't reach the Beam extension. Is it installed and enabled?"
      );
    }
  };

  useEffect(() => {
    // Firefox/Safari expose no `window.chrome` extension API — every guard here
    // naturally no-ops and only the manual form renders (AC9). Do NOT add an
    // "install extension" prompt for unsupported browsers.
    const markDetected = () => {
      setExtensionDetected(true);
      // Register the nonce over the D6 (externally_connectable) channel — the
      // only sender-verified path. Never expose it on any page-readable surface.
      try {
        window.chrome?.runtime?.sendMessage(KNOWN_EXTENSION_ID, {
          type: "register-nonce",
          nonce: extensionNonce,
        });
      } catch {
        /* extension not installed / unreachable — ignore */
      }
    };

    // (a) first-paint DOM-attribute fallback; (b) event path if it fires later.
    if (document.documentElement.dataset.beamExtension === "1") markDetected();
    window.addEventListener("beam-extension-detected", markDetected);

    // Secondary channel (D7) popup relay: trust a message only when it is from
    // our own origin AND carries the known source discriminator AND the nonce we
    // registered (D10/OI-3 — origin + source alone are forgeable by a
    // co-resident copy-cat extension in the same page context).
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as {
        source?: string;
        nonce?: string;
        ok?: boolean;
        cookie?: string;
        userAgent?: string;
        reason?: string;
      } | null;
      if (!data || data.source !== EXTENSION_MESSAGE_SOURCE) return;
      if (data.nonce !== extensionNonce) return; // forged / replayed → reject
      handleExtensionResult(data);
    };
    window.addEventListener("message", onMessage);

    return () => {
      window.removeEventListener("beam-extension-detected", markDetected);
      window.removeEventListener("message", onMessage);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-serif font-semibold tracking-tight">Connected Accounts</h1>

      {isLoading ? (
        <ListCardSkeleton rows={3} leading />
      ) : isError ? (
        <ErrorBanner
          message={`Couldn't load accounts — ${error?.message ?? "request failed"}`}
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
            encrypted in the outreach service — Beam never keeps a copy and never
            shows it again.
          </p>
          <div className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
            <strong>Warning:</strong> automating LinkedIn is against LinkedIn&apos;s
            Terms of Service and can get your account restricted or banned. Use a
            low daily volume and only with accounts you&apos;re willing to risk.
          </div>

          {/* Extension path (additive). Renders only when the Beam extension is
              detected; always sits BELOW the ToS warning above (AC7), never
              bypassing it. The manual form below always renders regardless. */}
          {extensionDetected && (
            <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
              <p className="text-sm font-medium text-foreground">
                Beam extension detected
              </p>
              <p className="text-xs text-muted-foreground">
                Skip the manual steps below — connect your LinkedIn session in
                one click.
              </p>
              <Button
                type="button"
                onClick={connectViaExtension}
                disabled={
                  extensionMut.isPending || outreachStatus?.configured === false
                }
              >
                {extensionMut.isPending
                  ? "Connecting..."
                  : outreachStatus?.outreach_connected
                    ? "Refresh connection with extension"
                    : "Connect with extension"}
              </Button>
              {extensionError && (
                <p className="text-sm text-destructive">{extensionError}</p>
              )}
              {extensionMut.isSuccess && (
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
                    (Mac) — a technical panel opens. Don&apos;t worry, you can&apos;t break anything.
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
                Browser details — filled in automatically
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
                Couldn&apos;t connect LinkedIn outreach —{" "}
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
        </CardContent>
      </Card>
    </div>
  );
}
