"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LinkedInTosWarning } from "@/components/linkedin-tos-warning";
import {
  CHROME_WEB_STORE_URL,
  computeWizardStepIndex,
  WIZARD_REOPEN_PARAM,
  WIZARD_STEP_BROWSER,
  WIZARD_STEP_CONNECT,
  WIZARD_STEP_INSTALL,
  WIZARD_STEP_SIGNIN,
  type LinkedInExtensionStatus,
} from "@/lib/use-linkedin-extension-status";

// Guided 4-step LinkedIn connect wizard.
//
// This component NEVER calls useLinkedInExtensionStatus() itself — it receives
// that state as props from its single host (dashboard/social-accounts/page.tsx).
// A second live hook instance would double-register the D6 nonce and silently
// break the D7 popup-relay path (see the hook's header comment).
//
// The current step is DERIVED from the live signals on every render, never
// tracked separately — that is what makes the "already fully set up" case land
// straight on the connect step for free.

const STEPS = [
  { key: "browser", label: "Browser" },
  { key: "install", label: "Install" },
  { key: "linkedin-signin", label: "Sign in" },
  { key: "connect", label: "Connect" },
] as const;

export type LinkedInConnectWizardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Server has the outreach service configured (else connect is unavailable). */
  serverConfigured: boolean;
  /** An outreach session already exists → this run is a reconnect. */
  alreadyConnected: boolean;
  /** Reveal the advanced manual paste form on the host page (AC12). */
  onShowManualForm: () => void;
} & LinkedInExtensionStatus;

export function LinkedInConnectWizard({
  open,
  onOpenChange,
  serverConfigured,
  alreadyConnected,
  onShowManualForm,
  extensionDetected,
  signedIn,
  isChromeOrEdge,
  pollExhausted,
  error,
  isPending,
  isConnected,
  connectedName,
  connect,
  retry,
  resetPoll,
}: LinkedInConnectWizardProps) {
  const currentStepIndex = computeWizardStepIndex(
    extensionDetected,
    signedIn,
    isChromeOrEdge
  );

  // Re-arm the detection wiring whenever the step changes, so a poller started
  // for the install step never keeps firing once we're on the connect step (D3).
  useEffect(() => {
    if (open) resetPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, currentStepIndex]);

  const openInNewTab = (url: string) => {
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // Install step: we cannot detect a brand-new install in an already-open tab,
  // so the user tells us instead. The param reopens this dialog after reload.
  const handleInstalledClick = () => {
    const url = new URL(window.location.href);
    url.searchParams.set(WIZARD_REOPEN_PARAM, "1");
    window.history.replaceState(null, "", url.toString());
    window.location.reload();
  };

  const showManualForm = () => {
    onShowManualForm();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {alreadyConnected ? "Reconnect LinkedIn" : "Connect LinkedIn"}
          </DialogTitle>
        </DialogHeader>

        {/* Progress bar — mirrors the onboarding page's numbered-circle pattern. */}
        <div className="flex items-center gap-2" data-testid="wizard-progress">
          {STEPS.map((s, i) => (
            <div key={s.key} className="flex items-center gap-2 flex-1">
              <div className="flex items-center gap-2 flex-1">
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                    i <= currentStepIndex
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {i < currentStepIndex ? (
                    <svg
                      className="w-4 h-4"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </div>
                <span
                  className={`text-sm font-medium hidden sm:inline ${
                    i <= currentStepIndex
                      ? "text-foreground"
                      : "text-muted-foreground"
                  }`}
                >
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`flex-1 h-0.5 rounded ${
                    i < currentStepIndex ? "bg-primary" : "bg-muted"
                  }`}
                />
              )}
            </div>
          ))}
        </div>

        {/* ── Step 1: browser check (dead end for unsupported browsers) ── */}
        {currentStepIndex === WIZARD_STEP_BROWSER && (
          <div className="space-y-3" data-testid="wizard-step-browser">
            <p className="text-sm text-foreground">
              This one-click setup needs Chrome or Edge, and it looks like
              you&apos;re using a different browser.
            </p>
            <p className="text-sm text-muted-foreground">
              You can still set LinkedIn up here. Use the manual option instead,
              it takes about a minute.
            </p>
            <Button type="button" variant="outline" onClick={showManualForm}>
              Use the manual option
            </Button>
          </div>
        )}

        {/* ── Step 2: install (reload-based; never promises silent detection) ── */}
        {currentStepIndex === WIZARD_STEP_INSTALL && (
          <div className="space-y-3" data-testid="wizard-step-install">
            <p className="text-sm text-foreground">
              Add the Beam browser add-on. It connects LinkedIn in one click, so
              you never have to copy anything by hand.
            </p>

            {/* Permission transparency BEFORE the install action (AC13). */}
            <div
              className="rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground"
              data-testid="wizard-permission-transparency"
            >
              <p className="font-medium text-foreground">
                What the add-on can see
              </p>
              <p className="mt-1">
                Only your LinkedIn sign-in for linkedin.com, so Beam can send
                connection requests on your behalf.
              </p>
              <p className="mt-1 font-medium text-foreground">
                What it does not do
              </p>
              <p className="mt-1">
                It doesn&apos;t look at any other site you visit, it never posts
                anything on its own, and Beam doesn&apos;t keep a copy of your
                raw LinkedIn sign-in.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => openInNewTab(CHROME_WEB_STORE_URL)}
              >
                Get the add-on
              </Button>
              <Button type="button" variant="outline" onClick={handleInstalledClick}>
                I&apos;ve installed it
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              &quot;Get the add-on&quot; opens the Chrome Web Store in a new tab.
              Once it&apos;s added, come back here and click &quot;I&apos;ve
              installed it&quot; to refresh this page so Beam can see it.
            </p>
            <button
              type="button"
              onClick={showManualForm}
              className="text-xs underline text-muted-foreground hover:text-foreground"
            >
              Rather not install anything? Use the manual option
            </button>
          </div>
        )}

        {/* ── Step 3: LinkedIn sign-in (genuinely auto-advances on return) ── */}
        {currentStepIndex === WIZARD_STEP_SIGNIN && (
          <div className="space-y-3" data-testid="wizard-step-signin">
            <p className="text-sm text-foreground">
              Sign in to LinkedIn, then come back to this tab. We&apos;ll pick
              up right where you left off.
            </p>
            <Button
              type="button"
              onClick={() => openInNewTab("https://www.linkedin.com")}
            >
              Sign in to LinkedIn
            </Button>
            {pollExhausted && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Still not seeing your LinkedIn sign-in.
                </p>
                <Button type="button" variant="outline" onClick={retry}>
                  Check again
                </Button>
              </div>
            )}
            <button
              type="button"
              onClick={showManualForm}
              className="text-xs underline text-muted-foreground hover:text-foreground"
            >
              Use the manual option instead
            </button>
          </div>
        )}

        {/* ── Step 4: connect ── */}
        {currentStepIndex === WIZARD_STEP_CONNECT && (
          <div className="space-y-3" data-testid="wizard-step-connect">
            {/* Identical wording to the card's banner — shared component (AC8). */}
            <LinkedInTosWarning />

            {isConnected ? (
              <div className="space-y-3">
                <p className="text-sm text-success" data-testid="wizard-connected">
                  Connected{connectedName ? ` as ${connectedName}` : ""}.
                </p>
                <Button type="button" onClick={() => onOpenChange(false)}>
                  Done
                </Button>
              </div>
            ) : (
              <>
                <p className="text-sm text-foreground">
                  You&apos;re all set. {alreadyConnected ? "Refresh" : "Finish"}{" "}
                  the connection and Beam can start sending LinkedIn steps for
                  your campaigns.
                </p>
                {!serverConfigured && (
                  <p className="text-sm text-muted-foreground">
                    LinkedIn outreach is not enabled on this server yet. Ask your
                    admin to configure the outreach service.
                  </p>
                )}
                <Button
                  type="button"
                  onClick={connect}
                  disabled={isPending || !serverConfigured}
                >
                  {isPending
                    ? "Connecting..."
                    : alreadyConnected
                      ? "Refresh connection"
                      : "Connect LinkedIn"}
                </Button>
                {error && (
                  <p className="text-sm text-destructive" data-testid="wizard-error">
                    {error}
                  </p>
                )}
                <button
                  type="button"
                  onClick={showManualForm}
                  className="text-xs underline text-muted-foreground hover:text-foreground"
                >
                  Use the manual option instead
                </button>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
