"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { TOUR_STEPS } from "@/lib/tour-steps";
import { Button } from "@/components/ui/button";
import { BeamMascot } from "@/components/beam-mascot";

/**
 * Just-in-time tab intro. Instead of dumping the whole product tour on a user's
 * first dashboard load, each section explains itself the first time the user
 * actually opens it — a single dimmed-backdrop dialog (same mascot card look as
 * the full tour) shown once per tab. Content is shared with the replayable tour
 * (TOUR_STEPS); dismissal is remembered per tab in localStorage so it never
 * nags twice.
 */

const FLAG_PREFIX = "beam_tab_intro_v1_";

// Which TOUR_STEPS entry (by id) introduces each dashboard route.
const ROUTE_STEP: Record<string, string> = {
  "/dashboard": "overview",
  "/dashboard/visitors": "visitors",
  "/dashboard/segments": "segments",
  "/dashboard/campaigns": "campaigns",
  "/dashboard/connectors": "connectors",
  "/dashboard/feed": "feed",
};

export function TabIntro({
  pathname,
  isAdmin,
}: {
  pathname: string;
  isAdmin: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  // The step to show for the current tab, or null (unknown tab / already seen).
  const [stepId, setStepId] = useState<string | null>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const id = ROUTE_STEP[pathname];
    if (!id) {
      setStepId(null);
      return;
    }
    const step = TOUR_STEPS.find((s) => s.id === id);
    if (!step || (step.adminOnly && !isAdmin)) {
      setStepId(null);
      return;
    }
    let seen = false;
    try {
      seen = localStorage.getItem(FLAG_PREFIX + id) === "1";
    } catch {
      // Storage blocked — skip the intro rather than risk showing it every visit.
      seen = true;
    }
    setStepId(seen ? null : id);
  }, [pathname, isAdmin]);

  const dismiss = () => {
    if (stepId) {
      try {
        localStorage.setItem(FLAG_PREFIX + stepId, "1");
      } catch {
        /* storage blocked — nothing to persist */
      }
    }
    setStepId(null);
  };

  // Esc dismisses, matching the tour's keyboard behaviour.
  useEffect(() => {
    if (!stepId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId]);

  if (!mounted || !stepId) return null;
  const step = TOUR_STEPS.find((s) => s.id === stepId);
  if (!step) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tab-intro-title"
      onClick={dismiss}
    >
      {/* Dim + soft blur behind the card so the tab underneath recedes. */}
      <div className="absolute inset-0 bg-foreground/60 backdrop-blur-sm" />
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(90vw, 360px)" }}
        className="pointer-events-auto relative rounded-lg border bg-card px-5 pb-5 pt-6 shadow-lg outline-none animate-in fade-in zoom-in-95"
      >
        <BeamMascot className="pointer-events-none absolute -top-12 left-4 h-16 w-auto drop-shadow-md" />
        <h2
          id="tab-intro-title"
          className="mt-3 font-serif text-lg font-semibold tracking-tight"
        >
          {step.title}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
        <div className="mt-4 flex justify-end">
          <Button size="sm" onClick={dismiss}>
            Got it
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
