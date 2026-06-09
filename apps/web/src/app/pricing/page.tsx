"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type BillingInterval = "monthly" | "yearly";

const PLANS = [
  {
    id: "free" as const,
    name: "Free",
    monthly: 0,
    yearly: 0,
    limit: "10 identified visitors/mo",
    features: [
      "Core enrichment",
      "Basic visitor analytics",
      "1 website",
      "Email support",
    ],
    highlight: false,
    cta: "Get started free",
  },
  {
    id: "pro" as const,
    name: "Pro",
    monthly: 19,
    yearly: 15,
    limit: "50 identified visitors/mo",
    features: [
      "Everything in Free",
      "Social enrichment",
      "AI reply drafts",
      "Priority support",
      "3 websites",
    ],
    highlight: true,
    cta: "Start with Pro",
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
      "Unlimited websites",
    ],
    highlight: false,
    cta: "Go Max",
  },
];

const FAQ = [
  {
    q: "How does visitor identification work?",
    a: "Beam uses a lightweight tracking pixel on your site. When a visitor matches our identity graph, we enrich their profile with LinkedIn, job title, company, and more — so you can follow up on their turf.",
  },
  {
    q: "What counts as an \"identified visitor\"?",
    a: "Only visitors we successfully resolve to a real person count toward your monthly limit. Anonymous page views are free and unlimited.",
  },
  {
    q: "Can I change plans later?",
    a: "Yes. Upgrade or downgrade anytime from your dashboard. Changes take effect immediately and billing is prorated.",
  },
  {
    q: "Is there a free trial?",
    a: "The Free plan is free forever with 10 identified visitors per month. No credit card required to start.",
  },
  {
    q: "How do I cancel?",
    a: "Cancel anytime from your billing settings. No lock-in, no cancellation fees. You keep access until the end of your billing period.",
  },
];

export default function PricingPage() {
  const router = useRouter();
  const [interval, setInterval] = useState<BillingInterval>("monthly");
  const [loadingPlan, setLoadingPlan] = useState<string | null>(null);

  async function handlePlanClick(planId: string) {
    if (planId === "free") {
      router.push("/signup");
      return;
    }

    const token = api.getToken();
    if (!token) {
      router.push(`/signup?plan=${planId}&interval=${interval}`);
      return;
    }

    setLoadingPlan(planId);
    try {
      const { checkout_url } = await api.createCheckout(
        planId as "pro" | "max",
        interval
      );
      window.location.href = checkout_url;
    } catch {
      router.push(`/dashboard/billing?plan=${planId}&interval=${interval}`);
    } finally {
      setLoadingPlan(null);
    }
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <nav className="border-b border-border/40">
        <div className="max-w-5xl mx-auto flex items-center justify-between px-6 py-4">
          <Link href="/" className="text-xl font-bold tracking-tight">
            Beam
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/sign-in">
              <Button variant="ghost" size="sm">
                Sign in
              </Button>
            </Link>
            <Link href="/signup">
              <Button size="sm">Get started</Button>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-3xl mx-auto text-center pt-16 pb-10 px-6">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Simple, transparent pricing
        </h1>
        <p className="mt-4 text-lg text-muted-foreground max-w-xl mx-auto">
          Know who visits your site. Reach out on their turf. Start free, upgrade when you need more.
        </p>
      </section>

      {/* Interval toggle */}
      <div className="flex justify-center mb-8">
        <div className="flex items-center gap-1 bg-secondary rounded-lg p-1">
          {(["monthly", "yearly"] as BillingInterval[]).map((iv) => (
            <button
              key={iv}
              onClick={() => setInterval(iv)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                interval === iv
                  ? "bg-background shadow text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {iv === "monthly" ? "Monthly" : "Yearly"}
              {iv === "yearly" && (
                <span className="ml-1.5 text-xs text-green-500 font-semibold">
                  Save 20%
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Plan cards */}
      <section className="max-w-5xl mx-auto px-6 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {PLANS.map((plan) => {
            const price = interval === "monthly" ? plan.monthly : plan.yearly;
            const isLoading = loadingPlan === plan.id;

            return (
              <Card
                key={plan.id}
                className={`relative flex flex-col ${
                  plan.highlight
                    ? "border-primary ring-2 ring-primary/20 shadow-lg"
                    : ""
                }`}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground text-xs font-semibold px-3 py-1 rounded-full">
                    Most popular
                  </div>
                )}
                <CardHeader className="pb-2">
                  <CardTitle className="text-lg">{plan.name}</CardTitle>
                  <div className="flex items-baseline gap-1 mt-2">
                    <span className="text-4xl font-bold">${price}</span>
                    {price > 0 && (
                      <span className="text-muted-foreground">/mo</span>
                    )}
                    {price === 0 && (
                      <span className="text-muted-foreground">forever</span>
                    )}
                  </div>
                  {interval === "yearly" && price > 0 && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Billed ${price * 12}/year
                    </p>
                  )}
                  <p className="text-sm font-medium text-muted-foreground mt-3">
                    {plan.limit}
                  </p>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col">
                  <ul className="space-y-2.5 flex-1 mb-6">
                    {plan.features.map((f) => (
                      <li
                        key={f}
                        className="text-sm text-muted-foreground flex items-start gap-2"
                      >
                        <svg
                          className="w-4 h-4 text-green-500 mt-0.5 shrink-0"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={2.5}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M5 13l4 4L19 7"
                          />
                        </svg>
                        {f}
                      </li>
                    ))}
                  </ul>
                  <Button
                    className="w-full"
                    variant={plan.highlight ? "default" : "outline"}
                    size="lg"
                    onClick={() => handlePlanClick(plan.id)}
                    disabled={isLoading}
                  >
                    {isLoading ? "Redirecting..." : plan.cta}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      {/* FAQ */}
      <section className="border-t border-border">
        <div className="max-w-3xl mx-auto px-6 py-16">
          <h2 className="text-2xl font-bold text-center mb-10">
            Frequently asked questions
          </h2>
          <div className="space-y-8">
            {FAQ.map((item) => (
              <div key={item.q}>
                <h3 className="font-semibold text-foreground mb-2">{item.q}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{item.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer CTA */}
      <section className="border-t border-border">
        <div className="max-w-3xl mx-auto text-center px-6 py-16">
          <h2 className="text-2xl font-bold mb-3">Ready to see who&apos;s visiting?</h2>
          <p className="text-muted-foreground mb-6">
            Start free. No credit card required. Upgrade anytime.
          </p>
          <Link href="/signup">
            <Button size="lg">Get started for free</Button>
          </Link>
        </div>
      </section>
    </div>
  );
}
