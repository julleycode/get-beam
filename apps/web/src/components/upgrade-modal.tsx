"use client";

import { useState } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { api } from "@/lib/api";
import { nextPaidPlans } from "@/lib/plans";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

/**
 * Upsell modal shown when a user hits their MONTHLY plan limit (the only limit
 * that upgrading lifts — daily caps are identical across tiers, so those keep a
 * BYOK-led notice instead). Leads with "Upgrade to Pro/Max"; keeps BYOK as a
 * secondary escape hatch per the chosen messaging.
 */
export function UpgradeModal({
  open,
  onOpenChange,
  currentPlan,
  reason,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentPlan: string;
  reason: string;
}) {
  const [actionPlan, setActionPlan] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const targets = nextPaidPlans(currentPlan);

  async function handleUpgrade(planId: "pro" | "max") {
    setActionPlan(planId);
    setError(null);
    try {
      const { checkout_url } = await api.createCheckout(planId, "monthly");
      window.location.href = checkout_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start checkout.");
    } finally {
      setActionPlan(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upgrade to keep going</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          {targets.map((plan) => (
            <div
              key={plan.id}
              className={`flex flex-col rounded-lg border p-4 ${
                plan.highlight ? "border-primary ring-1 ring-primary" : "border-border"
              }`}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-semibold">{plan.name}</span>
                <span>
                  <span className="text-xl font-bold">${plan.monthly}</span>
                  <span className="text-xs text-muted-foreground">/mo</span>
                </span>
              </div>
              <p className="mt-1 text-xs font-medium text-muted-foreground">
                {plan.limit}
              </p>
              <ul className="mt-3 flex-1 space-y-1">
                {plan.features.map((f) => (
                  <li key={f} className="flex gap-2 text-xs text-muted-foreground">
                    <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                    {f}
                  </li>
                ))}
              </ul>
              <Button
                size="sm"
                className="mt-4 w-full"
                onClick={() => handleUpgrade(plan.id as "pro" | "max")}
                disabled={actionPlan === plan.id}
              >
                {actionPlan === plan.id ? "Redirecting…" : `Upgrade to ${plan.name}`}
              </Button>
            </div>
          ))}
        </div>

        <p className="text-center text-xs text-muted-foreground">
          Prefer to stay free?{" "}
          <Link
            href="/dashboard/billing"
            onClick={() => onOpenChange(false)}
            className="font-medium text-foreground underline underline-offset-2 hover:text-primary"
          >
            Add your own API keys
          </Link>{" "}
          to unlock, or{" "}
          <Link
            href="/dashboard/billing"
            onClick={() => onOpenChange(false)}
            className="underline underline-offset-2 hover:text-primary"
          >
            save 20% yearly on Billing
          </Link>
          .
        </p>
      </DialogContent>
    </Dialog>
  );
}
