"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BadgeCheck,
  Globe,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
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
  const featuredPlan = targets[0] ?? null;
  const alternatePlans = targets.slice(1);

  const featureIcons = [Sparkles, Users, Globe, Zap, BadgeCheck];

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

  if (!featuredPlan) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[720px] gap-0 border-none bg-transparent p-0 shadow-none">
        <div className="relative mx-auto w-full max-w-[420px] px-4 pb-4 pt-20 sm:max-w-[520px] sm:px-0 sm:pt-24">
          <div className="absolute inset-x-0 top-0 mx-auto w-[78%] rounded-[28px] border border-border/70 bg-background/95 px-6 py-7 text-center shadow-[0_24px_60px_rgba(15,23,42,0.14)] backdrop-blur">
            <DialogHeader className="space-y-2 text-center">
              <DialogTitle className="font-sans text-[1.95rem] font-semibold tracking-[-0.03em] text-foreground sm:text-[2.1rem]">
                Keep Beam running
              </DialogTitle>
              <DialogDescription className="mx-auto max-w-[300px] text-sm leading-6 text-muted-foreground sm:max-w-[360px]">
                {reason}
              </DialogDescription>
            </DialogHeader>
          </div>

          <div className="relative rounded-[36px] border border-border/70 bg-background px-6 pb-6 pt-8 shadow-[0_40px_100px_rgba(15,23,42,0.18)] sm:px-8 sm:pb-8 sm:pt-9">
            <div className="inline-flex rounded-full bg-muted px-4 py-2 text-sm font-medium text-foreground/80">
              Most teams start with {featuredPlan.name}
            </div>

            <div className="mt-5">
              <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
                <h3 className="text-4xl font-semibold tracking-[-0.04em] text-foreground sm:text-5xl">
                  ${featuredPlan.monthly}
                  <span className="ml-2 text-lg font-medium text-muted-foreground">
                    /month
                  </span>
                </h3>
                {featuredPlan.yearly > 0 && (
                  <div className="pb-1 text-sm text-muted-foreground">
                    or ${featuredPlan.yearly}/mo billed yearly
                  </div>
                )}
              </div>
              <p className="mt-3 text-base text-muted-foreground">
                {featuredPlan.limit}. Cancel or switch anytime.
              </p>
            </div>

            {error && (
              <div className="mt-5 rounded-2xl border border-destructive/30 bg-destructive-muted px-4 py-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <Button
              size="lg"
              className="mt-6 h-14 w-full rounded-full text-base font-semibold"
              onClick={() => handleUpgrade(featuredPlan.id as "pro" | "max")}
              disabled={actionPlan === featuredPlan.id}
            >
              {actionPlan === featuredPlan.id ? "Redirecting..." : `Upgrade to ${featuredPlan.name}`}
            </Button>

            <ul className="mt-7 space-y-4">
              {featuredPlan.features.map((feature, index) => {
                const Icon = featureIcons[index % featureIcons.length];
                return (
                  <li
                    key={feature}
                    className="flex items-start gap-3 text-base text-foreground"
                  >
                    <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="leading-7">{feature}</span>
                  </li>
                );
              })}
            </ul>

            {alternatePlans.length > 0 && (
              <div className="mt-7 rounded-[24px] border border-border/70 bg-muted/40 p-4">
                <p className="text-sm font-medium text-foreground">
                  Need more headroom?
                </p>
                <div className="mt-3 flex flex-col gap-3">
                  {alternatePlans.map((plan) => (
                    <button
                      key={plan.id}
                      type="button"
                      onClick={() => handleUpgrade(plan.id as "pro" | "max")}
                      disabled={actionPlan === plan.id}
                      className="flex items-center justify-between rounded-2xl bg-background px-4 py-3 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <div>
                        <div className="font-medium text-foreground">{plan.name}</div>
                        <div className="text-sm text-muted-foreground">
                          {plan.limit}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <span>${plan.monthly}/mo</span>
                        <ArrowRight className="h-4 w-4" />
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <p className="mt-6 text-center text-sm leading-6 text-muted-foreground">
              Prefer to stay free?{" "}
              <Link
                href="/dashboard/billing"
                onClick={() => onOpenChange(false)}
                className="font-medium text-foreground underline underline-offset-2 hover:text-primary"
              >
                Add your own API keys
              </Link>{" "}
              or{" "}
              <Link
                href="/dashboard/billing"
                onClick={() => onOpenChange(false)}
                className="underline underline-offset-2 hover:text-primary"
              >
                switch to yearly billing
              </Link>
              .
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
