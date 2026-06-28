"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { Check } from "lucide-react";
import { api, BillingStatus, BillingInterval } from "@/lib/api";
import { CardGridSkeleton, PageHeaderSkeleton } from "@/components/skeletons";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

// ── Plan metadata ──────────────────────────────────────────────────────────

const PLANS = [
  {
    id: "free" as const,
    name: "Free",
    monthly: 0,
    yearly: 0,
    limit: "10 identified visitors/mo",
    features: ["Core enrichment", "Basic visitor analytics"],
    highlight: false,
  },
  {
    id: "pro" as const,
    name: "Pro",
    monthly: 19,
    yearly: 15,
    limit: "50 identified visitors/mo",
    features: ["Social enrichment", "AI reply drafts", "Priority support"],
    highlight: true,
  },
  {
    id: "max" as const,
    name: "Max",
    monthly: 49,
    yearly: 39,
    limit: "Unlimited identified visitors",
    features: [
      "Everything in Pro",
      "Priority identification",
      "Team seats",
      "API access",
    ],
    highlight: false,
  },
];

// ── Helpers ────────────────────────────────────────────────────────────────

function planLabel(plan: string): string {
  return PLANS.find((p) => p.id === plan)?.name ?? plan;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

// ── Main component ─────────────────────────────────────────────────────────

function BillingContent() {
  const searchParams = useSearchParams();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [interval, setInterval] = useState<BillingInterval>("monthly");
  const [loading, setLoading] = useState(true);
  const [actionPlan, setActionPlan] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelLoading, setCancelLoading] = useState(false);
  const [canceledUntil, setCanceledUntil] = useState<string | null>(null);

  const successParam = searchParams.get("success");
  const canceledParam = searchParams.get("canceled");

  useEffect(() => {
    // Wait for Clerk + ensure the API client has a token before fetching.
    // Firing on mount races ClerkTokenSync — the call goes out with no auth
    // header and 401s as "Unauthorized". Gate on auth, then sync the token.
    if (!isLoaded || !isSignedIn) return;
    let cancelled = false;
    (async () => {
      try {
        const t = await getToken();
        if (t) api.setClerkToken(t);
        const status = await api.getBillingStatus();
        if (!cancelled) setBilling(status);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken]);

  async function handleUpgrade(planId: string) {
    if (planId === "free") return;
    setActionPlan(planId);
    setError(null);
    try {
      const { checkout_url } = await api.createCheckout(
        planId as "pro" | "max",
        interval
      );
      window.location.href = checkout_url;
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setActionPlan(null);
    }
  }

  async function handlePortal() {
    setPortalLoading(true);
    setError(null);
    try {
      const { portal_url } = await api.createPortal();
      window.location.href = portal_url;
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setPortalLoading(false);
    }
  }

  async function handleCancel() {
    setCancelLoading(true);
    setError(null);
    try {
      const res = await api.cancelSubscription();
      // Show the date access lasts until; fall back to whatever the status has.
      const until =
        res.current_period_end ?? billing?.current_period_end ?? null;
      setCanceledUntil(until);
      setCancelOpen(false);
      // Refresh billing so the badge/status reflect the cancellation.
      try {
        const status = await api.getBillingStatus();
        setBilling(status);
      } catch {
        // Non-fatal: the success message already shows the key date.
      }
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setCancelLoading(false);
    }
  }

  const usagePct =
    billing && billing.monthly_limit !== null
      ? Math.min(
          100,
          Math.round(
            (billing.monthly_identified_count / billing.monthly_limit) * 100
          )
        )
      : 0;

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-serif font-semibold tracking-tight">Billing</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage your plan and usage.
        </p>
      </div>

      {/* Success / canceled banners */}
      {successParam && (
        <div className="rounded-md border border-success/30 bg-success-muted px-4 py-3 text-sm text-success">
          Subscription activated. Your plan has been updated.
        </div>
      )}
      {canceledParam && (
        <div className="rounded-md border border-warning/30 bg-warning-muted px-4 py-3 text-sm text-warning">
          Checkout canceled. No changes were made.
        </div>
      )}
      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive-muted px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Current plan + usage */}
      <Card>
        <CardHeader>
          <CardTitle>Current plan</CardTitle>
          <CardDescription>Your active subscription and usage.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : billing ? (
            <>
              <div className="flex items-center gap-3">
                <span className="text-lg font-semibold">
                  {planLabel(billing.plan)}
                </span>
                {billing.subscription_status && (
                  <StatusBadge status={billing.subscription_status} />
                )}
              </div>

              {/* Usage bar */}
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">
                    Identified visitors this month
                  </span>
                  <span className="font-medium">
                    {billing.monthly_identified_count}
                    {billing.monthly_limit !== null
                      ? ` / ${billing.monthly_limit}`
                      : " (unlimited)"}
                  </span>
                </div>
                {billing.monthly_limit !== null && (
                  <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        usagePct >= 90 ? "bg-destructive" : "bg-primary"
                      }`}
                      style={{ width: `${usagePct}%` }}
                    />
                  </div>
                )}
              </div>

              {billing.current_period_end && (
                <p className="text-xs text-muted-foreground">
                  Renews{" "}
                  {new Date(billing.current_period_end).toLocaleDateString(
                    "en-US",
                    { year: "numeric", month: "long", day: "numeric" }
                  )}
                </p>
              )}

              {billing.trial_ends_at && (
                <p className="text-xs text-warning">
                  Trial ends{" "}
                  {new Date(billing.trial_ends_at).toLocaleDateString("en-US", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </p>
              )}

              {canceledUntil && (
                <div className="rounded-md border border-warning/30 bg-warning-muted px-4 py-3 text-sm text-warning">
                  Your plan stays active until {formatDate(canceledUntil)}, then
                  drops to Free. Your data is kept.
                </div>
              )}

              {billing.plan !== "free" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePortal}
                    disabled={portalLoading}
                  >
                    {portalLoading ? "Redirecting..." : "Manage subscription"}
                  </Button>
                  {billing.subscription_status !== "cancelled" &&
                    !canceledUntil && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => setCancelOpen(true)}
                      >
                        Cancel plan
                      </Button>
                    )}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Unable to load billing status.
            </p>
          )}
        </CardContent>
      </Card>

      <Separator />

      {/* Plan picker */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Plans</h2>
          <div className="flex items-center gap-2 bg-secondary rounded-lg p-1">
            {(["monthly", "yearly"] as BillingInterval[]).map((iv) => (
              <button
                key={iv}
                onClick={() => setInterval(iv)}
                className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                  interval === iv
                    ? "bg-background shadow text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {iv === "monthly" ? "Monthly" : "Yearly"}
                {iv === "yearly" && (
                  <span className="ml-1 text-xs font-semibold text-success">
                    -20%
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {PLANS.map((plan) => {
            const isCurrent = billing?.plan === plan.id;
            const price =
              interval === "monthly" ? plan.monthly : plan.yearly;

            return (
              <Card
                key={plan.id}
                className={`relative flex flex-col ${
                  plan.highlight ? "border-primary ring-1 ring-primary" : ""
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground text-xs font-semibold px-3 py-0.5 rounded-full">
                    Most popular
                  </div>
                )}
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">{plan.name}</CardTitle>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-bold">${price}</span>
                    <span className="text-sm text-muted-foreground">/mo</span>
                  </div>
                  {interval === "yearly" && price > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Billed ${price * 12}/yr
                    </p>
                  )}
                </CardHeader>
                <CardContent className="flex-1 space-y-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    {plan.limit}
                  </p>
                  <ul className="space-y-1">
                    {plan.features.map((f) => (
                      <li
                        key={f}
                        className="flex gap-2 text-xs text-muted-foreground"
                      >
                        <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                        {f}
                      </li>
                    ))}
                  </ul>
                  {isCurrent ? (
                    <Button variant="secondary" size="sm" className="w-full" disabled>
                      Current plan
                    </Button>
                  ) : plan.id === "free" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={handlePortal}
                      disabled={portalLoading || billing?.plan === "free"}
                    >
                      Downgrade
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      className="w-full"
                      onClick={() => handleUpgrade(plan.id)}
                      disabled={actionPlan === plan.id}
                    >
                      {actionPlan === plan.id
                        ? "Redirecting..."
                        : isCurrent
                        ? "Current plan"
                        : "Upgrade"}
                    </Button>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Cancel confirmation */}
      <Dialog
        open={cancelOpen}
        onOpenChange={(o) => {
          if (!cancelLoading) setCancelOpen(o);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel {planLabel(billing?.plan ?? "")} plan?</DialogTitle>
            <DialogDescription>
              {billing?.current_period_end ? (
                <>
                  Your plan stays fully active until{" "}
                  <span className="font-medium text-foreground">
                    {formatDate(billing.current_period_end)}
                  </span>
                  , then your account drops to Free. All your data is kept — you
                  can resubscribe any time.
                </>
              ) : (
                <>
                  Your plan drops to Free at the end of the current billing
                  period. All your data is kept — you can resubscribe any time.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCancelOpen(false)}
              disabled={cancelLoading}
            >
              Keep plan
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancel}
              disabled={cancelLoading}
            >
              {cancelLoading ? "Cancelling..." : "Confirm cancellation"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={
        <div className="max-w-3xl mx-auto space-y-6">
          <PageHeaderSkeleton />
          <CardGridSkeleton cards={3} cols={3} />
        </div>
      }
    >
      <BillingContent />
    </Suspense>
  );
}
