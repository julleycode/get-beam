"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings } from "lucide-react";
import { api, ConsentMode } from "@/lib/api";
import type { GoalCreatePayload } from "@/lib/api-types";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { Separator } from "@/components/ui/separator";
import { PixelUninstallGuide } from "@/components/pixel-uninstall-guide";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

/**
 * Per-site settings, opened from a gear next to the SiteSelector. This is the
 * home for everything that used to live on the (now-removed) Settings tab that
 * is scoped to a single site: details, pixel snippet, cookie consent, pause
 * tracking, budget, and pixel removal. Account-level settings (API keys,
 * billing/cancel) live on the Billing page instead.
 *
 * Uses the same react-query cache key (["site", siteId]) as the Visitors page
 * quick-toggles so the two surfaces stay in sync automatically.
 */
export function SiteSettingsDialog({ siteId }: { siteId: string }) {
  const [open, setOpen] = useState(false);

  if (!siteId) return null;

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Site settings"
        title="Site settings"
        onClick={() => setOpen(true)}
      >
        <Settings className="h-4 w-4" />
      </Button>
      {/* Mount body only while open so we don't fetch for every page's selector. */}
      {open && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Site settings</DialogTitle>
              <DialogDescription>
                Configure this site&apos;s pixel, consent, and data collection.
              </DialogDescription>
            </DialogHeader>
            <SiteSettingsBody siteId={siteId} />
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

function SiteSettingsBody({ siteId }: { siteId: string }) {
  const queryClient = useQueryClient();

  const { data: site } = useQuery({
    queryKey: ["site", siteId],
    queryFn: () => api.getSite(siteId),
    enabled: !!siteId,
  });
  const { data: snippetData } = useQuery({
    queryKey: ["snippet", siteId],
    queryFn: () => api.getPixelSnippet(siteId),
    enabled: !!siteId,
  });
  const snippet = snippetData?.snippet ?? "";

  const [copied, setCopied] = useState(false);
  const [promptCopied, setPromptCopied] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{
    status: string;
    message: string;
  } | null>(null);
  const [uninstallOpen, setUninstallOpen] = useState(false);
  // Booking link is a free-text field, so it needs local draft state; seeded
  // from the server value once the site query resolves.
  const [bookingUrl, setBookingUrl] = useState("");
  const [bookingSeeded, setBookingSeeded] = useState(false);
  const [goalPath, setGoalPath] = useState("/thanks");

  const invalidateSite = () =>
    queryClient.invalidateQueries({ queryKey: ["site", siteId] });

  const consentMut = useMutation({
    mutationFn: (mode: ConsentMode) => api.setConsentMode(siteId, mode),
    onSettled: () => {
      invalidateSite();
      // consent mode changes data-consent → refresh the snippet card too.
      queryClient.invalidateQueries({ queryKey: ["snippet", siteId] });
    },
  });
  const pauseMut = useMutation({
    mutationFn: (enabled: boolean) => api.updateSite(siteId, { tracking_enabled: enabled }),
    onSettled: invalidateSite,
  });
  const dampingMut = useMutation({
    mutationFn: (enabled: boolean) => api.setInternalDamping(siteId, enabled),
    onSettled: invalidateSite,
  });
  const bookingMut = useMutation({
    mutationFn: (url: string) => api.updateSite(siteId, { booking_url: url }),
    onSuccess: invalidateSite,
  });
  const goalMut = useMutation({
    mutationFn: (payload: GoalCreatePayload) =>
      api.createConversionGoal(siteId, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["conversionGoals", siteId] }),
  });
  const verifyMut = useMutation({
    mutationFn: () => api.verifyPixel(siteId),
    onSuccess: (r) => {
      setVerifyResult({ status: r.status, message: r.message });
      if (r.verified) invalidateSite();
    },
    onError: () =>
      setVerifyResult({ status: "error", message: "Could not verify. Please try again." }),
  });

  async function copyText(text: string, flag: (v: boolean) => void) {
    try {
      await navigator.clipboard.writeText(text);
      flag(true);
      setTimeout(() => flag(false), 2000);
    } catch {
      // clipboard unavailable (insecure origin / permission denied) — no-op
    }
  }

  function handleCopyConsentPrompt() {
    const mode = site?.consent_mode ?? "off";
    const lines =
      mode === "cmp"
        ? [
            "Wire my cookie-consent tool to the Beam tracking pixel so Beam only",
            "tracks after the visitor accepts analytics/marketing cookies.",
            "",
            "The Beam pixel is installed as:",
            snippet,
            "",
            "Beam exposes a global function `window.beamConsent(granted)`. Call it",
            "with `true` when the user grants analytics/marketing consent and",
            "`false` when they decline. Examples:",
            "- OneTrust: in the OptanonWrapper() callback, call",
            "  window.beamConsent(OnetrustActiveGroups.indexOf('C0004') > -1).",
            "- Cookiebot: on 'CookiebotOnAccept' call",
            "  window.beamConsent(Cookiebot.consent.marketing); on 'CookiebotOnDecline'",
            "  call window.beamConsent(false).",
            "- Custom banner: call window.beamConsent(true) in your Accept handler and",
            "  window.beamConsent(false) in your Decline handler.",
            "",
            "Do not fire Beam before consent.",
          ]
        : [
            "I use the Beam tracking pixel. It ships its own cookie-consent banner —",
            `my Beam consent mode is "${mode}", so Beam handles the Accept/Decline`,
            "banner automatically; I do NOT need to build a popup.",
            "",
            "My Beam pixel snippet is:",
            snippet,
            "",
            "Please add a link to my privacy policy so I can pass its URL to Beam via",
            'the data-consent-policy attribute on the <script> tag, e.g.',
            'data-consent-policy="https://mysite.com/privacy". Point it at my real',
            "privacy policy page (create a simple one if I don't have it yet).",
          ];
    copyText(lines.join("\n").trim(), setPromptCopied);
  }

  if (!site) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  // Seed the booking-link draft once, without clobbering an in-progress edit.
  if (!bookingSeeded) {
    setBookingSeeded(true);
    setBookingUrl(site.booking_url ?? "");
  }

  const platform = site.detected_platform || "unknown";

  return (
    <div className="space-y-5 text-sm">
      {/* Site details */}
      <section className="space-y-2">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Name</span>
          <span className="font-medium">{site.name}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">URL</span>
          <span className="truncate">{site.url}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Pixel</span>
          <div className="flex items-center gap-2">
            <StatusBadge
              status={site.pixel_verified ? "active" : "paused"}
              label={site.pixel_verified ? "Verified" : "Not verified"}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => verifyMut.mutate()}
              disabled={verifyMut.isPending}
            >
              {verifyMut.isPending ? "Checking…" : "Verify now"}
            </Button>
          </div>
        </div>
        {verifyResult && (
          <p
            className={`text-xs ${
              verifyResult.status === "verified" ? "text-success" : "text-warning"
            }`}
          >
            {verifyResult.message}
          </p>
        )}
      </section>

      <Separator />

      {/* Pixel snippet */}
      <section className="space-y-2">
        <p className="font-medium text-foreground">Pixel snippet</p>
        <div className="relative">
          <pre className="rounded-md bg-muted p-3 text-xs overflow-x-auto whitespace-pre-wrap break-all">
            {snippet || "Loading…"}
          </pre>
          <Button
            variant="outline"
            size="sm"
            className="absolute top-2 right-2"
            onClick={() => copyText(snippet, setCopied)}
            disabled={!snippet}
          >
            {copied ? "Copied!" : "Copy"}
          </Button>
        </div>
      </section>

      <Separator />

      {/* Demo booking link */}
      <section className="space-y-2">
        <p className="font-medium text-foreground">Demo booking link</p>
        <p className="text-xs text-muted-foreground">
          Your Calendly / Cal.com link, or a booking page on your own site. Beam
          drops it into campaign drafts wherever the AI writes{" "}
          <code className="rounded bg-muted px-1">{"{{booking_link}}"}</code>.
          Leave it empty and that placeholder simply disappears.
        </p>
        <div className="flex gap-2">
          <input
            id="booking-url"
            type="url"
            className="flex-1 rounded-md border bg-muted px-3 py-2 text-sm"
            placeholder="https://cal.com/you/demo"
            value={bookingUrl}
            onChange={(e) => setBookingUrl(e.target.value)}
            disabled={bookingMut.isPending}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => bookingMut.mutate(bookingUrl.trim())}
            disabled={bookingMut.isPending || bookingUrl.trim() === (site.booking_url ?? "")}
          >
            {bookingMut.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {bookingMut.isError && (
          <p className="text-xs text-warning">
            That link was rejected. Use a full http(s) URL with no spaces and no
            {" "}
            <code className="rounded bg-muted px-1">{`< > " ' )`}</code> characters.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Note: if your booking link is on a subdomain of your own site, campaign
          links to it will carry Beam&apos;s encrypted click token. Use a path on
          your own site, or a third-party booking host, if you&apos;d rather they
          didn&apos;t.
        </p>

        {/* D3 — one-click "Demo booked" conversion goal preset. Pre-fills the
            normal goal form and posts to the existing goals endpoint; nothing is
            created automatically when the booking URL is saved. */}
        {site.booking_url && (
          <div className="space-y-2 rounded-md border p-3">
            <p className="text-xs font-medium text-foreground">
              Track demo bookings
            </p>
            <p className="text-xs text-muted-foreground">
              Point your booking tool&apos;s confirmation redirect at a thank-you
              page on your own site, then enter{" "}
              <strong>the path of that page</strong> (e.g.{" "}
              <code className="rounded bg-muted px-1">/thanks</code>) — not a full
              URL. It must start with{" "}
              <code className="rounded bg-muted px-1">/</code>.
            </p>
            <div className="flex gap-2">
              <input
                id="demo-goal-path"
                className="flex-1 rounded-md border bg-muted px-3 py-2 text-sm"
                placeholder="/thanks"
                value={goalPath}
                onChange={(e) => setGoalPath(e.target.value)}
                disabled={goalMut.isPending}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  goalMut.mutate({
                    name: "Demo booked",
                    goal_type: "url_match",
                    match_type: "prefix",
                    pattern: goalPath.trim(),
                  })
                }
                disabled={goalMut.isPending || !goalPath.trim().startsWith("/")}
              >
                {goalMut.isPending ? "Creating…" : "Create goal"}
              </Button>
            </div>
            {goalMut.isSuccess && (
              <p className="text-xs text-success">
                &quot;Demo booked&quot; goal created.
              </p>
            )}
            {goalMut.isError && (
              <p className="text-xs text-warning">
                Could not create the goal — it may already exist, or the path is
                invalid.
              </p>
            )}
          </div>
        )}
      </section>

      <Separator />

      {/* Cookie consent */}
      <section className="space-y-2">
        <p className="font-medium text-foreground">Cookie consent</p>
        <p className="text-xs text-muted-foreground">
          Show visitors a cookie banner before Beam collects data. Beam builds
          the banner for you, no popup to code.
        </p>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="consent-mode" className="text-muted-foreground text-xs">
            When to ask for consent
          </label>
          <select
            id="consent-mode"
            className="rounded-md border bg-muted px-3 py-2 text-sm"
            value={site.consent_mode}
            disabled={consentMut.isPending}
            onChange={(e) => consentMut.mutate(e.target.value as ConsentMode)}
          >
            <option value="off">Off, no banner (default)</option>
            <option value="eu">EU visitors only (recommended)</option>
            <option value="all">Everyone</option>
            <option value="cmp">Use my own consent tool (CMP)</option>
          </select>
        </div>
        <p className="text-xs text-muted-foreground">
          {site.consent_mode === "off" &&
            "No banner. Browser opt-out signals (GPC / Do-Not-Track) are still honored."}
          {site.consent_mode === "eu" &&
            "EU/EEA visitors see an Accept/Decline banner and Beam waits for consent. Everyone else is unchanged, so your US match rate stays intact."}
          {site.consent_mode === "all" &&
            "Every visitor sees the banner and Beam waits for consent before collecting anything."}
          {site.consent_mode === "cmp" &&
            "Beam shows no banner. Your own consent tool calls window.beamConsent(true/false). Use the prompt below to wire it up."}
        </p>
        <p className="text-xs text-muted-foreground">
          Beam provides the banner and gating; you&apos;re still responsible for
          your privacy policy and lawful basis. This isn&apos;t legal advice.
        </p>
        <Button variant="outline" size="sm" onClick={handleCopyConsentPrompt} disabled={!snippet}>
          {promptCopied ? "Prompt copied ✓" : "Copy prompt to Claude"}
        </Button>
      </section>

      <Separator />

      {/* Pause tracking */}
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium text-foreground">Pause tracking</p>
            <p className="text-xs text-muted-foreground">
              Stop collecting while keeping your plan, data, and pixel.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <StatusBadge
              status={site.tracking_enabled ? "active" : "paused"}
              label={site.tracking_enabled ? "Collecting" : "Paused"}
            />
            <Button
              variant={site.tracking_enabled ? "outline" : "default"}
              size="sm"
              onClick={() => pauseMut.mutate(!site.tracking_enabled)}
              disabled={pauseMut.isPending}
            >
              {pauseMut.isPending
                ? "Saving…"
                : site.tracking_enabled
                  ? "Pause"
                  : "Resume"}
            </Button>
          </div>
        </div>
      </section>

      <Separator />

      {/* Damp outlier traffic */}
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium text-foreground">Damp outlier traffic</p>
            <p className="text-xs text-muted-foreground">
              Flags visitors with unusually high activity (for example your own
              team browsing the site) so you can review them. Flagging alone
              changes nothing: only the ones you confirm are damped in your
              analytics and identity-resolution budget. Their data is always
              stored and they stay fully contactable either way.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <StatusBadge
              status={site.internal_damping_enabled ? "active" : "paused"}
              label={site.internal_damping_enabled ? "On" : "Off"}
            />
            <Button
              variant={site.internal_damping_enabled ? "outline" : "default"}
              size="sm"
              onClick={() => dampingMut.mutate(!site.internal_damping_enabled)}
              disabled={dampingMut.isPending}
            >
              {dampingMut.isPending
                ? "Saving…"
                : site.internal_damping_enabled
                  ? "Turn off"
                  : "Turn on"}
            </Button>
          </div>
        </div>
      </section>

      <Separator />

      {/* Budget (read-only) */}
      <section className="flex justify-between gap-4">
        <span className="text-muted-foreground">Daily resolution budget</span>
        <span>{site.daily_resolution_budget} lookups/day</span>
      </section>

      <Separator />

      {/* Danger zone */}
      <section className="flex items-center justify-between gap-4">
        <div>
          <p className="font-medium text-foreground">Remove pixel</p>
          <p className="text-xs text-muted-foreground">
            A guide to take the snippet off your site. Reinstall any time.
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
      </section>

      <Dialog open={uninstallOpen} onOpenChange={setUninstallOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Remove the Beam pixel</DialogTitle>
            <DialogDescription>
              Follow these steps to take the snippet off your site.
            </DialogDescription>
          </DialogHeader>
          <PixelUninstallGuide
            platform={platform}
            snippet={snippet}
            siteId={siteId}
            onRemoved={() => setUninstallOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
