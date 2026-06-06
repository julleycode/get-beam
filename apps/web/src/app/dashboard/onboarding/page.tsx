"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, BillingInterval } from "@/lib/api";
import { PixelInstallGuide } from "@/components/pixel-install-guide";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Step = "create" | "install" | "done" | "plan";

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
    cta: "Continue with Free",
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

export default function OnboardingPage() {
  const router = useRouter();

  const [step, setStep] = useState<Step>("create");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [siteId, setSiteId] = useState("");
  const [snippet, setSnippet] = useState("");
  const [platform, setPlatform] = useState("unknown");
  const [hasGtm, setHasGtm] = useState(false);
  const [gtmId, setGtmId] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);

  const [interval, setInterval] = useState<BillingInterval>("monthly");
  const [actionPlan, setActionPlan] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const site = await api.createSite(name, url, description || undefined);
      setSiteId(site.site_id);

      const pixel = await api.getPixelSnippet(site.site_id);
      setSnippet(pixel.snippet);

      setDetecting(true);
      setStep("install");

      try {
        const detected = await api.detectPlatform(url);
        setPlatform(detected.platform);
        setHasGtm(detected.has_gtm);
        setGtmId(detected.gtm_id);
      } catch {
        setPlatform("unknown");
      } finally {
        setDetecting(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create site");
    } finally {
      setLoading(false);
    }
  }

  function handleVerified() {
    setStep("done");
    setTimeout(() => setStep("plan"), 1500);
  }

  async function handlePlanClick(planId: string) {
    if (planId === "free") {
      router.push("/dashboard");
      return;
    }

    setActionPlan(planId);
    setError("");
    try {
      const { checkout_url } = await api.createCheckout(
        planId as "pro" | "max",
        interval
      );
      window.location.href = checkout_url;
    } catch {
      router.push(`/dashboard/billing?plan=${planId}&interval=${interval}`);
    } finally {
      setActionPlan(null);
    }
  }

  // ────────── Step indicator ──────────
  const steps = [
    { key: "create", label: "Add Site" },
    { key: "install", label: "Install Pixel" },
    { key: "done", label: "Verified" },
    { key: "plan", label: "Choose Plan" },
  ];

  const currentIndex = steps.findIndex(
    (s) => s.key === step || (step === "done" && s.key === "done")
  );

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress bar */}
      <div className="flex items-center gap-2 mb-8">
        {steps.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2 flex-1">
            <div className="flex items-center gap-2 flex-1">
              <div
                className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                  i <= currentIndex
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {i < currentIndex ? (
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`text-sm font-medium hidden sm:inline ${
                  i <= currentIndex
                    ? "text-foreground"
                    : "text-muted-foreground"
                }`}
              >
                {s.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div
                className={`flex-1 h-0.5 rounded ${
                  i < currentIndex ? "bg-primary" : "bg-muted"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step 1: Create site */}
      {step === "create" && (
        <Card>
          <CardHeader>
            <CardTitle>Add your website</CardTitle>
            <CardDescription>
              Enter your website URL and we&apos;ll auto-detect the best way to
              install tracking
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              {error && <p className="text-sm text-destructive">{error}</p>}
              <div className="space-y-2">
                <Label htmlFor="name">Site name</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="My Store"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="url">Site URL</Label>
                <Input
                  id="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://mystore.com"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="desc">
                  Description{" "}
                  <span className="text-muted-foreground font-normal">
                    (helps AI generate better campaigns)
                  </span>
                </Label>
                <Textarea
                  id="desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="We sell handmade candles for wellness enthusiasts..."
                  rows={2}
                />
              </div>
              <Button type="submit" className="w-full" size="lg" disabled={loading}>
                {loading ? "Creating..." : "Continue"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Install pixel */}
      {step === "install" && (
        <Card>
          <CardHeader>
            <CardTitle>Install tracking pixel</CardTitle>
            <CardDescription>
              {detecting
                ? "Detecting your platform..."
                : "Follow the steps below to connect your website"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {detecting ? (
              <div className="flex flex-col items-center justify-center py-12 gap-3">
                <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                <p className="text-sm text-muted-foreground">
                  Analyzing {url}...
                </p>
              </div>
            ) : (
              <PixelInstallGuide
                platform={platform}
                hasGtm={hasGtm}
                gtmId={gtmId}
                snippet={snippet}
                siteId={siteId}
                onVerified={handleVerified}
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 3: Done (brief success) */}
      {step === "done" && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
            <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-green-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </div>
            <h3 className="text-xl font-bold">Pixel verified!</h3>
            <p className="text-muted-foreground text-center max-w-md">
              Your tracking pixel is live. Now let&apos;s pick a plan.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Choose plan */}
      {step === "plan" && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Choose your plan</CardTitle>
              <CardDescription>
                Start free or unlock more identified visitors with Pro or Max.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}

              {/* Interval toggle */}
              <div className="flex justify-center">
                <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
                  {(["monthly", "yearly"] as BillingInterval[]).map((iv) => (
                    <button
                      key={iv}
                      onClick={() => setInterval(iv)}
                      className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                        interval === iv
                          ? "bg-background shadow text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {iv === "monthly" ? "Monthly" : "Yearly"}
                      {iv === "yearly" && (
                        <span className="ml-1 text-xs text-green-500 font-semibold">
                          -20%
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* Plan cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {PLANS.map((plan) => {
                  const price =
                    interval === "monthly" ? plan.monthly : plan.yearly;
                  const isLoading = actionPlan === plan.id;

                  return (
                    <div
                      key={plan.id}
                      className={`relative rounded-lg border p-4 flex flex-col ${
                        plan.highlight
                          ? "border-primary ring-1 ring-primary"
                          : "border-border"
                      }`}
                    >
                      {plan.highlight && (
                        <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground text-[10px] font-semibold px-2 py-0.5 rounded-full">
                          Popular
                        </div>
                      )}
                      <p className="font-semibold text-sm">{plan.name}</p>
                      <div className="flex items-baseline gap-1 mt-1">
                        <span className="text-2xl font-bold">${price}</span>
                        {price > 0 && (
                          <span className="text-xs text-muted-foreground">
                            /mo
                          </span>
                        )}
                        {price === 0 && (
                          <span className="text-xs text-muted-foreground">
                            forever
                          </span>
                        )}
                      </div>
                      {interval === "yearly" && price > 0 && (
                        <p className="text-[10px] text-muted-foreground">
                          Billed ${price * 12}/yr
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground mt-2 mb-3">
                        {plan.limit}
                      </p>
                      <ul className="space-y-1.5 flex-1 mb-4">
                        {plan.features.map((f) => (
                          <li
                            key={f}
                            className="text-xs text-muted-foreground flex items-start gap-1.5"
                          >
                            <svg
                              className="w-3 h-3 text-green-500 mt-0.5 shrink-0"
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={3}
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
                        size="sm"
                        onClick={() => handlePlanClick(plan.id)}
                        disabled={isLoading}
                      >
                        {isLoading ? "Redirecting..." : plan.cta}
                      </Button>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <button
            onClick={() => router.push("/dashboard")}
            className="block mx-auto text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Skip for now
          </button>
        </div>
      )}
    </div>
  );
}
