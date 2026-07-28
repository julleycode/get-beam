"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { TOUR_STEPS } from "@/lib/tour-steps";
import { Button } from "@/components/ui/button";

/**
 * Just-in-time tab intro. Instead of dumping the whole product tour on a user's
 * first dashboard load, each section explains itself the first time the user
 * actually opens it — a one-time dismissible card at the top of that tab.
 * Content is shared with the replayable full tour (TOUR_STEPS); dismissal is
 * remembered per tab in localStorage so it never nags twice.
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
  // The step to show for the current tab, or null (unknown tab / already seen).
  const [stepId, setStepId] = useState<string | null>(null);

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

  if (!stepId) return null;
  const step = TOUR_STEPS.find((s) => s.id === stepId);
  if (!step) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(FLAG_PREFIX + stepId, "1");
    } catch {
      /* storage blocked — nothing to persist */
    }
    setStepId(null);
  };

  return (
    <div className="mb-6 flex items-start gap-3 rounded-lg border border-primary/25 bg-primary/5 p-4 shadow-sm">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{step.title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
        <Button size="sm" className="mt-3" onClick={dismiss}>
          Got it
        </Button>
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="flex-shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
