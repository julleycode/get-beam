"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ClassicOnboarding } from "@/components/onboarding/classic-onboarding";
import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";

/**
 * Thin router for the two onboarding surfaces. Three things survive from the
 * page this replaced, all deliberately:
 *
 * 1. `?site=<id>&step=install` resume — a real feature (recovers an
 *    interrupted setup instead of forcing a duplicate site). Handled inside
 *    ClassicOnboarding, and it WINS over ?welcome=1: a user coming back to
 *    finish an install should not be dropped into the intro conversation.
 * 2. `?welcome=1` — first-run users (from the dashboard's zero-site redirect)
 *    get the conversational flow. Existing users clicking "Add site" arrive
 *    without the param and get the bare form.
 * 3. The cross-tenant disclosure — a compliance requirement with a live e2e
 *    assertion on [data-testid="cross-tenant-disclosure"] and the literal
 *    string "cross-tenant identity". It now lives in one shared component
 *    (components/onboarding/cross-tenant-disclosure.tsx) rendered by BOTH
 *    install surfaces, so the two cannot drift apart.
 */
function OnboardingRouter() {
  const searchParams = useSearchParams();

  const resuming =
    !!searchParams.get("site") && searchParams.get("step") === "install";
  const firstRun = searchParams.get("welcome") === "1";

  if (firstRun && !resuming) return <OnboardingFlow />;
  return <ClassicOnboarding />;
}

export default function OnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="max-w-2xl mx-auto py-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      }
    >
      <OnboardingRouter />
    </Suspense>
  );
}
