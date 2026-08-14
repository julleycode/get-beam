"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  flowReducer,
  initialFlowState,
  loadFlowState,
  saveFlowState,
  clearFlowState,
  STEP_ORDER,
  type StepId,
} from "@/lib/onboarding-flow";
import { linesFor, revealLines, type Line } from "@/lib/onboarding-script";
import type { CanaryResponse } from "@/lib/canary-format";
import { ChatTranscript } from "@/components/onboarding/chat-transcript";
import { useMessageQueue } from "@/components/onboarding/use-message-queue";
import { useAutoScroll } from "@/components/onboarding/use-auto-scroll";
import { useReducedMotion } from "@/components/onboarding/use-reduced-motion";
import { WelcomeStep } from "@/components/onboarding/steps/welcome-step";
import { SiteStep } from "@/components/onboarding/steps/site-step";
import { InstallStep } from "@/components/onboarding/steps/install-step";
import { DoneStep } from "@/components/onboarding/steps/done-step";
import { CanaryGoStep } from "@/components/onboarding/steps/canary-go-step";
import { ConfirmStep } from "@/components/onboarding/steps/confirm-step";
import { CanaryListen } from "@/components/onboarding/canary-listen";
import { CanaryReveal } from "@/components/onboarding/canary-reveal";
import type { FeedbackPayload } from "@/components/onboarding/identity-feedback-form";

// Plain CSS import — App Router bundles and hashes it, no FOUC, and (unlike
// the deleted onboarding-welcome-chat.tsx) no runtime <link> injection. Safe
// to import because src/styles/onboarding-chat.css drops every global rule
// and scopes its custom properties under .ob-root.
import "@/styles/onboarding-chat.css";

/** Inline so the logo needs no dangerouslySetInnerHTML. */
function SparkLogo() {
  return (
    <svg viewBox="0 0 100 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="obSparkGrad" x1="0" y1="0" x2="1" y2="0.35">
          <stop offset="0" stopColor="#FF6B9D" />
          <stop offset="0.55" stopColor="#FF3366" />
          <stop offset="1" stopColor="#FF7FA8" />
        </linearGradient>
      </defs>
      <path
        d="M26,15 Q26,32 90,32 Q26,32 26,49 Q26,32 9,32 Q26,32 26,15 Z"
        fill="url(#obSparkGrad)"
      />
      <circle cx="26" cy="32" r="3.4" fill="#fff" opacity="0.92" />
      <path
        d="M82,21 Q84,25 88,25 Q84,25 82,29 Q80,25 76,25 Q80,25 82,21 Z"
        fill="url(#obSparkGrad)"
        opacity="0.85"
      />
    </svg>
  );
}

/** 8 dots, one per STEP_ORDER entry — not 13 (legacy) and not 2 (the card form). */
function ProgressDots({ step }: { step: StepId }) {
  const index = STEP_ORDER.indexOf(step);
  return (
    <div className="ob-progress" aria-hidden="true">
      {STEP_ORDER.map((s, i) => (
        <span
          key={s}
          className={
            i === index ? "ob-dot active" : i < index ? "ob-dot done" : "ob-dot"
          }
        />
      ))}
    </div>
  );
}

function markOnboarded() {
  try {
    // dashboard/page.tsx reads this to decide whether to re-offer the funnel.
    // Keep writing it even though the flow now has its own v2 key.
    localStorage.setItem("beam_onboarded_v1", "1");
  } catch {
    /* storage blocked — worst case the funnel re-offers next visit */
  }
}

export function OnboardingFlow() {
  const router = useRouter();
  const reduced = useReducedMotion();
  const [state, dispatch] = useReducer(flowReducer, initialFlowState);
  const { scrollRef, contentRef } = useAutoScroll<HTMLDivElement, HTMLDivElement>();

  // ── resume ───────────────────────────────────────────────────────────────
  // One-shot on mount. loadFlowState() already sanitizes: unknown ids and any
  // canary step (while the canary is off) come back as `welcome`, and
  // canary_listen never resumes as itself — its 90s deadline is unresumable.
  const resumed = useRef(false);
  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;
    const saved = loadFlowState();
    if (!saved || saved.step === "welcome") return;
    // Only resume a step we can actually rehydrate. `install` needs a snippet
    // we do not persist, so re-fetch it before landing there.
    if (saved.step === "install" && saved.siteId) {
      let cancelled = false;
      (async () => {
        try {
          const pixel = await api.getPixelSnippet(saved.siteId as string);
          if (cancelled) return;
          dispatch({
            type: "RESUME",
            step: "install",
            siteId: saved.siteId,
            snippet: pixel.snippet,
          });
        } catch {
          // Bad/expired site id — start the site step over rather than
          // stranding the user on an install screen with no snippet.
          clearFlowState();
        }
      })();
      return () => {
        cancelled = true;
      };
    }
    dispatch({ type: "RESUME", step: saved.step, siteId: saved.siteId });
  }, []);

  // ── persist ──────────────────────────────────────────────────────────────
  useEffect(() => {
    saveFlowState({
      step: state.step,
      siteId: state.siteId,
      canaryOutcome: state.canaryOutcome,
    });
  }, [state.step, state.siteId, state.canaryOutcome]);

  // ── site creation (real API, no fakes) ───────────────────────────────────
  const handleCreateSite = useCallback(
    async (values: { name: string; url: string; description: string }) => {
      dispatch({ type: "SITE_SUBMIT" });
      try {
        const site = await api.createSite(
          values.name,
          values.url,
          values.description || undefined,
        );
        markOnboarded();
        const pixel = await api.getPixelSnippet(site.site_id);
        dispatch({
          type: "SITE_CREATED",
          siteId: site.site_id,
          snippet: pixel.snippet,
          url: values.url,
        });
      } catch (err) {
        const detail = (err as { detail?: { code?: string } } | null)?.detail;
        dispatch({
          type: "SITE_FAILED",
          message: err instanceof Error ? err.message : "Failed to create site",
          showUpgrade: detail?.code === "site_limit_reached",
        });
      }
    },
    [],
  );

  // ── platform detection, with the reducer's retry-once ────────────────────
  // Re-runs while `detecting` stays true; PLATFORM_FAILED keeps it true for
  // exactly one retry, then flips it false with platform "unknown".
  useEffect(() => {
    if (!state.detecting || !state.siteUrl) return;
    let cancelled = false;
    (async () => {
      try {
        const detected = await api.detectPlatform(state.siteUrl as string);
        if (cancelled) return;
        dispatch({
          type: "PLATFORM_DETECTED",
          platform: detected.platform,
          hasGtm: detected.has_gtm,
          gtmId: detected.gtm_id,
        });
      } catch {
        if (cancelled) return;
        dispatch({ type: "PLATFORM_FAILED" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state.detecting, state.siteUrl, state.detectAttempts]);

  const handleExit = useCallback(() => {
    markOnboarded();
    clearFlowState();
    router.push("/dashboard");
  }, [router]);

  const handleFinish = useCallback(() => {
    markOnboarded();
    clearFlowState();
    router.push("/dashboard");
  }, [router]);

  // ── the canary ───────────────────────────────────────────────────────────
  // An extra line prepended to the `site` step when we arrive there from a
  // canary that produced nothing, or from "not quite". Acknowledging the
  // outcome specifically is the difference between a conversation and a form.
  const [handoffLine, setHandoffLine] = useState<string | null>(null);

  const handleCanaryResult = useCallback(
    (outcome: "landed" | "geo_only" | "nothing", response: CanaryResponse | null) => {
      if (outcome === "nothing") {
        // NEVER fake a detection — say plainly that nothing landed.
        setHandoffLine(
          "couldn't catch you this time — an adblocker, a privacy setting, or the tab just never loaded. no matter; let's set you up properly.",
        );
      }
      dispatch({ type: "CANARY_RESULT", outcome, response });
    },
    [],
  );

  const handleSkipCanary = useCallback(() => {
    dispatch({ type: "SKIP_CANARY" });
  }, []);

  const handleFeedback = useCallback(
    (payload: FeedbackPayload) => {
      const geo = state.canary?.geo ?? null;
      const network = state.canary?.network ?? null;
      // OPTIMISTIC: fire and advance in the same tick. A feedback write must
      // never block onboarding, so failures are swallowed deliberately.
      void api
        .submitIdentityFeedback({
          reasons: payload.reasons,
          note: payload.note || null,
          actual_city: payload.actualCity || null,
          shown: {
            city: geo?.city ?? null,
            region: geo?.region ?? null,
            country_code: geo?.country_code ?? null,
            // Rounded: this is a feedback record, not a location store.
            lat: geo ? Math.round(geo.lat * 100) / 100 : null,
            lng: geo ? Math.round(geo.lng * 100) / 100 : null,
            org: network?.label ?? null,
            kind: network?.kind ?? null,
            // Whether the reveal had already hedged. A `wrong_city` report
            // against a `high`-confidence pin means two providers agreed and
            // were BOTH wrong — a different (and worse) failure than one
            // against `unverified`, and indistinguishable without this field.
            confidence: geo?.confidence ?? null,
          },
          site_id: state.siteId,
          fingerprint: state.fingerprint,
        })
        .catch(() => {
          /* swallowed on purpose — see above */
        });

      setHandoffLine(
        payload.actualCity
          ? `${payload.actualCity} it is — that correction is worth more than the guess was.`
          : payload.reasons.includes("wrong_city")
            ? "noted — 'wrong city' goes straight to the team that tunes IP geo."
            : "noted, thanks — that goes straight to the team that tunes this.",
      );
      dispatch({ type: "GOTO", step: "site" });
    },
    [state.canary, state.siteId, state.fingerprint],
  );

  // ── chat ─────────────────────────────────────────────────────────────────
  const lines: Line[] = useMemo(() => {
    if (state.step === "canary_reveal") {
      return revealLines(state.canaryOutcome === "landed");
    }
    const base = linesFor(state.step, { site: state.siteUrl ?? "your site" });
    if (state.step === "site" && handoffLine) {
      return [{ text: handoffLine, lead: true }, ...base];
    }
    return base;
  }, [state.step, state.canaryOutcome, state.siteUrl, handoffLine]);

  const queue = useMessageQueue(lines, state.step, reduced);

  return (
    <div className="ob-root">
      <div className="ob-bg" />

      <header className="ob-top">
        <span className="ob-logo">
          <SparkLogo />
          beam
        </span>
        <ProgressDots step={state.step} />
        {/* The dashboard layout owns the real "Exit to dashboard" control, so
            this is a plain skip that also marks the user onboarded. */}
        <button type="button" className="ob-exit" onClick={handleExit}>
          exit
        </button>
      </header>

      <main className="ob-stage">
        <div className="ob-scroll" ref={scrollRef}>
          <div className="ob-chat" ref={contentRef}>
            <ChatTranscript lines={queue.visible} typing={queue.typing} />

            {queue.done && state.step === "welcome" && (
              <WelcomeStep
                onAdvance={() => dispatch({ type: "ADVANCE" })}
                onExit={handleExit}
              />
            )}

            {queue.done && state.step === "canary_go" && (
              <CanaryGoStep
                onStart={(fingerprint) =>
                  dispatch({ type: "CANARY_START", fingerprint })
                }
                onSkip={handleSkipCanary}
              />
            )}

            {/* The radar renders as soon as the step opens — it IS the "we're
                working" state, so it must not wait on the typing queue. */}
            {state.step === "canary_listen" && (
              <CanaryListen
                fingerprint={state.fingerprint ?? ""}
                onResult={handleCanaryResult}
                onSkip={handleSkipCanary}
              />
            )}

            {queue.done && state.step === "canary_reveal" && state.canary && (
              <CanaryReveal
                response={state.canary}
                onConfirm={() => dispatch({ type: "GOTO", step: "confirm" })}
              />
            )}

            {queue.done && state.step === "confirm" && (
              <ConfirmStep
                onYes={() => dispatch({ type: "GOTO", step: "site" })}
                onFeedback={handleFeedback}
              />
            )}

            {queue.done && state.step === "site" && (
              <SiteStep
                onSubmit={handleCreateSite}
                submitting={state.submitting}
                error={state.error}
                showUpgrade={state.showUpgrade}
              />
            )}

            {queue.done && state.step === "install" && state.siteId && (
              <InstallStep
                siteId={state.siteId}
                siteUrl={state.siteUrl}
                snippet={state.snippet}
                platform={state.platform}
                hasGtm={state.hasGtm}
                gtmId={state.gtmId}
                detecting={state.detecting}
                onVerified={() => dispatch({ type: "VERIFIED" })}
              />
            )}

            {queue.done && state.step === "done" && (
              <DoneStep onFinish={handleFinish} />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
