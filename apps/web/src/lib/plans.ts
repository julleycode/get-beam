import type { BillingPlan } from "@/lib/api";

// ── Plan metadata ──────────────────────────────────────────────────────────
// Single source of truth for plan names, prices, limits, and features. Consumed
// by the Billing page plan grid, the sidebar plan/usage badge, and the upgrade
// modal so copy never drifts between surfaces.

export type Plan = {
  id: BillingPlan;
  name: string;
  monthly: number;
  yearly: number;
  limit: string;
  features: string[];
  highlight: boolean;
};

export const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    monthly: 0,
    yearly: 0,
    limit: "10 identified visitors/mo",
    features: ["Core enrichment", "Basic visitor analytics"],
    highlight: false,
  },
  {
    id: "pro",
    name: "Pro",
    monthly: 19,
    yearly: 15,
    limit: "50 identified visitors/mo",
    features: ["Social enrichment", "AI reply drafts", "Priority support"],
    highlight: true,
  },
  {
    id: "max",
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

export function planLabel(plan: string): string {
  return PLANS.find((p) => p.id === plan)?.name ?? plan;
}

// The paid tiers a user can move UP to from their current plan — the upgrade
// modal renders one card per returned plan. Max (unlimited) has no upgrade path.
export function nextPaidPlans(current: string): Plan[] {
  const order: BillingPlan[] = ["free", "pro", "max"];
  const idx = order.indexOf(current as BillingPlan);
  const currentIdx = idx === -1 ? 0 : idx;
  return PLANS.filter(
    (p) => p.id !== "free" && order.indexOf(p.id) > currentIdx
  );
}
