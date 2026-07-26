"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Shared LinkedIn-extension state for the Connected Accounts page and the
// onboarding wizard it hosts (onboarding plan D8).
//
// HARD RULE — exactly ONE call site: `dashboard/social-accounts/page.tsx`.
// The wizard receives this hook's return value as PROPS. Two live hook instances
// would each register their own D6 nonce, and the extension's `nonceByTabId`
// registry is last-write-wins per tab — so the D7 popup-relay response (signed
// with whichever nonce landed last) would be silently rejected by the other
// consumer's nonce check. That is a real user-visible bug, not a style nit.
//
// KEEP IN SYNC with apps/extension/src/known-origins.js
// (KNOWN_EXTENSION_ID / MESSAGE_SOURCE). Two separate build targets with no
// shared package, so the constants are deliberately duplicated.
export const KNOWN_EXTENSION_ID = "ejllllimjoomfaacgbedjjelljciicii";
export const EXTENSION_MESSAGE_SOURCE = "beam-extension";

// ⚠️ PLACEHOLDER — replace with the real Chrome Web Store listing URL once the
// extension is published (the store assigns its own id on first upload; see
// apps/extension/src/known-origins.js for the matching id note).
export const CHROME_WEB_STORE_URL =
  "https://chromewebstore.google.com/detail/REPLACE_WITH_STORE_ID";

/** Query param that reopens the wizard after the install-step page reload (D2). */
export const WIZARD_REOPEN_PARAM = "connectLinkedIn";

/** Backstop poll cadence: every 2s, capped at 30 attempts (60s total) — D3. */
export const POLL_INTERVAL_MS = 2_000;
export const POLL_MAX_ATTEMPTS = 30;

export const WIZARD_STEP_BROWSER = 0;
export const WIZARD_STEP_INSTALL = 1;
export const WIZARD_STEP_SIGNIN = 2;
export const WIZARD_STEP_CONNECT = 3;

/**
 * Which wizard step the CURRENT signals put us on. Pure and derived on every
 * render — never a separately tracked "which step am I on" state that could
 * drift from reality. This is also what makes the already-fully-set-up
 * short-circuit free: both signals true simply computes to step 3.
 */
export function computeWizardStepIndex(
  extensionDetected: boolean,
  signedIn: boolean | null,
  isChromeOrEdge: boolean
): number {
  // Unsupported browser dead-ends on step 1 — there is no install path to offer.
  if (!isChromeOrEdge) return WIZARD_STEP_BROWSER;
  if (!extensionDetected) return WIZARD_STEP_INSTALL;
  if (signedIn !== true) return WIZARD_STEP_SIGNIN;
  return WIZARD_STEP_CONNECT;
}

/**
 * Chrome/Edge family check from a user-agent string. Pure so it is testable in
 * the node-env Vitest lane. Excludes other Chromium-UA-carrying browsers that
 * do not support Chrome Web Store extensions the same way.
 */
export function isChromeOrEdgeUserAgent(userAgent: string): boolean {
  if (!userAgent) return false;
  if (/OPR\/|Opera|SamsungBrowser|YaBrowser/i.test(userAgent)) return false;
  // Safari/Firefox carry neither token.
  return /Edg\//i.test(userAgent) || /Chrome\//i.test(userAgent);
}

type ExtensionResult = {
  ok?: boolean;
  cookie?: string;
  userAgent?: string;
  reason?: string;
};

type SessionCheckResult = {
  signedIn?: boolean;
  reason?: string;
};

export type LinkedInExtensionStatus = {
  /** Beam extension present in this browser. */
  extensionDetected: boolean;
  /** null = not probed yet. */
  signedIn: boolean | null;
  /** Chrome/Edge (the only families that can run the extension). */
  isChromeOrEdge: boolean;
  /** Backstop poll hit its 30-attempt cap without a state change. */
  pollExhausted: boolean;
  error: string | null;
  isPending: boolean;
  isConnected: boolean;
  connectedName: string | null;
  /** One-click connect over the D6 channel (unchanged behavior). */
  connect: () => void;
  /** Re-arm exactly ONE fresh check after poll-cap exhaustion (D3). */
  retry: () => void;
  /** Re-arm the detection wiring — callers use this on wizard step change (D3). */
  resetPoll: () => void;
};

export function useLinkedInExtensionStatus(): LinkedInExtensionStatus {
  const queryClient = useQueryClient();

  const [extensionDetected, setExtensionDetected] = useState(false);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [isChromeOrEdge, setIsChromeOrEdge] = useState(false);
  const [pollExhausted, setPollExhausted] = useState(false);
  const [extensionError, setExtensionError] = useState<string | null>(null);

  // Per-page-load nonce. Registered with the extension over the Chrome
  // sender-verified channel; the popup-relay (D7) message must echo it back or
  // we reject it, so a co-resident copy-cat extension cannot forge a response
  // (sibling plan D10 / OI-3). Never rendered into the DOM or a CustomEvent.
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

  // Never log the cookie / userAgent / raw response anywhere (sibling AC8).
  const handleExtensionResult = useCallback(
    (data: ExtensionResult) => {
      if (!data.ok || !data.cookie) {
        if (data.reason === "not_signed_in") setSignedIn(false);
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
    },
    // extensionMut identity is stable enough for this callback's lifetime; the
    // mutate reference does not change across renders in React Query v5.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // Primary channel (D6): page → extension via externally_connectable. Same
  // one-click flow is reused for first connect and refresh/reconnect.
  const connect = useCallback(() => {
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
          handleExtensionResult(response as ExtensionResult);
        }
      );
    } catch {
      setExtensionError(
        "Couldn't reach the Beam extension. Is it installed and enabled?"
      );
    }
  }, [handleExtensionResult]);

  // Read-only signed-in probe (D5). Status only — the extension's response
  // shape has no cookie field, so nothing sensitive crosses here.
  const probeSignedIn = useCallback(() => {
    try {
      window.chrome?.runtime?.sendMessage(
        KNOWN_EXTENSION_ID,
        { type: "beam-session-check" },
        (response) => {
          if (window.chrome?.runtime?.lastError || !response) return;
          const data = response as SessionCheckResult;
          setSignedIn(data.signedIn === true);
        }
      );
    } catch {
      /* extension unreachable — leave signedIn as-is */
    }
  }, []);

  // One-shot re-check of BOTH signals: is the extension there, and is the user
  // signed in? Used by the focus/visibility listeners, the backstop poll, and
  // the manual retry affordance.
  const checkOnceRef = useRef<() => void>(() => {});
  const markDetected = useCallback(() => {
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
  }, [extensionNonce]);

  const checkOnce = useCallback(() => {
    if (typeof document !== "undefined") {
      if (document.documentElement.dataset.beamExtension === "1") markDetected();
    }
    probeSignedIn();
  }, [markDetected, probeSignedIn]);
  checkOnceRef.current = checkOnce;

  // ── D3 detection wiring: visibility/focus one-shot + capped backstop poll ──
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptsRef = useRef(0);

  const clearPoll = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startPoll = useCallback(() => {
    clearPoll();
    attemptsRef.current = 0;
    setPollExhausted(false);
    intervalRef.current = setInterval(() => {
      attemptsRef.current += 1;
      if (attemptsRef.current > POLL_MAX_ATTEMPTS) {
        clearPoll();
        setPollExhausted(true);
        return;
      }
      checkOnceRef.current();
    }, POLL_INTERVAL_MS);
  }, [clearPoll]);

  const resetPoll = useCallback(() => {
    startPoll();
  }, [startPoll]);

  /** One manual click = exactly ONE fresh check (never an endless new cycle). */
  const retry = useCallback(() => {
    setPollExhausted(false);
    checkOnceRef.current();
  }, []);

  useEffect(() => {
    setIsChromeOrEdge(isChromeOrEdgeUserAgent(navigator.userAgent));

    // Firefox/Safari expose no `window.chrome` extension API — every guard here
    // naturally no-ops and only the manual form renders. Do NOT add an
    // "install extension" prompt for unsupported browsers.
    const onDetected = () => {
      markDetected();
      probeSignedIn();
    };

    // (a) first-paint DOM-attribute fallback; (b) event path if it fires later.
    if (document.documentElement.dataset.beamExtension === "1") onDetected();
    window.addEventListener("beam-extension-detected", onDetected);

    // Secondary channel (D7) popup relay: trust a message only when it is from
    // our own origin AND carries the known source discriminator AND the nonce we
    // registered (D10/OI-3 — origin + source alone are forgeable by a
    // co-resident copy-cat extension in the same page context).
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as (ExtensionResult & {
        source?: string;
        nonce?: string;
      }) | null;
      if (!data || data.source !== EXTENSION_MESSAGE_SOURCE) return;
      if (data.nonce !== extensionNonce) return; // forged / replayed → reject
      handleExtensionResult(data);
    };
    window.addEventListener("message", onMessage);

    // Tab-return re-check: the user leaves to install the extension or to sign
    // into LinkedIn and comes back. Immediate one-shot, plus the capped poll as
    // a backstop for browsers/cases where neither event fires.
    const onVisible = () => {
      if (document.visibilityState === "visible") checkOnceRef.current();
    };
    const onFocus = () => checkOnceRef.current();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onFocus);
    startPoll();

    return () => {
      window.removeEventListener("beam-extension-detected", onDetected);
      window.removeEventListener("message", onMessage);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onFocus);
      clearPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    extensionDetected,
    signedIn,
    isChromeOrEdge,
    pollExhausted,
    error: extensionError,
    isPending: extensionMut.isPending,
    isConnected: extensionMut.isSuccess,
    connectedName: extensionMut.data?.name ?? null,
    connect,
    retry,
    resetPoll,
  };
}
