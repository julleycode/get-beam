"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { UpgradeModal } from "@/components/upgrade-modal";
import { useBillingStatus } from "@/lib/use-billing";

// Show the nudge once a user has burned this share of their monthly limit.
const WARN_THRESHOLD = 0.8;

/**
 * Proactive upsell banner. Appears on Overview + Visitors once monthly usage
 * reaches ~80% of the plan limit, before the user is hard-blocked. Self-contained:
 * owns its own UpgradeModal so pages just drop <UsageWarningBanner />. Hidden for
 * unlimited (Max) plans, while loading, on error, and after session dismissal.
 */
export function UsageWarningBanner() {
  const { data: billing } = useBillingStatus();
  const [dismissed, setDismissed] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  if (!billing || billing.monthly_limit === null || dismissed) return null;

  const { monthly_identified_count: used, monthly_limit: limit } = billing;
  if (used < Math.floor(limit * WARN_THRESHOLD)) return null;

  const reached = used >= limit;
  const message = reached
    ? `You've used all ${limit} identifications this month on the ${
        billing.plan === "free" ? "Free" : billing.plan
      } plan.`
    : `You've used ${used} of ${limit} identifications this month.`;

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/30 bg-warning-muted px-4 py-3 text-sm text-warning">
        <span>
          {message} Upgrade to keep identifying visitors.
        </span>
        <div className="flex items-center gap-1">
          <Button size="sm" onClick={() => setModalOpen(true)}>
            Upgrade
          </Button>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setDismissed(true)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-warning/70 transition-colors hover:bg-warning/10 hover:text-warning"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <UpgradeModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        currentPlan={billing.plan}
        reason={message}
      />
    </>
  );
}
