"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, BillingStatus, BillingInterval } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

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

function statusBadgeClass(status: string | null): string {
  if (!status) return "bg-gray-100 text-gray-600";
  if (status === "active" || status === "trialing")
    return "bg-green-100 text-green-700";
  if (status === "past_due") return "bg-yellow-100 text-yellow-700";
  if (status === "canceled") return "bg-red-100 text-red-600";
  return "bg-gray-100 text-gray-600";
}

// ── Main component ─────────────────────────────────────────────────────────

export default function BillingPage() {
  const searchParams = useSearchParams();
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [interval, setInterval] = useState<BillingInterval>("monthly");
  const [loading, setLoading] = useState(true);
  const [actionPlan, setActionPlan] = useState<string | null>(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const successParam = searchParams.get("success");
  const canceledParam = searchParams.get("canceled");

  useEffect(() => {
    api
      .getBillingStatus()
      .then(setBilling)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

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
        <h1 className="text-2xl font-bold">Billing</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage your plan and usage.
        </p>
      </div>

      {/* Success / canceled banners */}
      {successParam && (
        <div className="rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          Subscription activated. Your plan has been updated.
        </div>
      )}
      {canceledParam && (
        <div className="rounded-md bg-yellow-50 border border-yellow-200 px-4 py-3 text-sm text-yellow-700">
          Checkout canceled. No changes were made.
        </div>
      )}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
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
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : billing ? (
            <>
              <div className="flex items-center gap-3">
                <span className="text-lg font-semibold">
                  {planLabel(billing.plan)}
                </span>
                {billing.subscription_status && (
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${statusBadgeClass(
                      billing.subscription_status
                    )}`}
                  >
                    {billing.subscription_status}
                  </span>
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
                        usagePct >= 90 ? "bg-red-500" : "bg-primary"
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
                <p className="text-xs text-yellow-600">
                  Trial ends{" "}
                  {new Date(billing.trial_ends_at).toLocaleDateString("en-US", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </p>
              )}

              {billing.plan !== "free" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePortal}
                  disabled={portalLoading}
                >
                  {portalLoading ? "Redirecting..." : "Manage subscription"}
                </Button>
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
                  <span className="ml-1 text-xs text-green-600 font-semibold">
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
                        className="text-xs text-muted-foreground flex gap-2"
                      >
                        <span className="text-green-500 font-bold">+</span>
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
    </div>
  );
}
