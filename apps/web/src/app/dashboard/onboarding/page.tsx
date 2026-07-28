"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
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

type Step = "welcome" | "create" | "install";

function OnboardingFlow() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // First-run users arrive with ?welcome=1 (from the dashboard's zero-site
  // redirect) and see the welcome intro before add site. The "Add site" button
  // for existing users links here without the param, dropping them straight on
  // the create form.
  const [step, setStep] = useState<Step>(
    searchParams.get("welcome") === "1" ? "welcome" : "create",
  );
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [showUpgrade, setShowUpgrade] = useState(false);
  const [loading, setLoading] = useState(false);

  const [siteId, setSiteId] = useState("");
  const [snippet, setSnippet] = useState("");
  const [platform, setPlatform] = useState("unknown");
  const [hasGtm, setHasGtm] = useState(false);
  const [gtmId, setGtmId] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);

  // Resume an interrupted setup: ?site=<id>&step=install drops the user straight
  // back into the install/verify step for a site they already created, instead
  // of forcing them to create a brand-new site (the original soft-lock).
  const resumeSite = searchParams.get("site");
  const resumeStep = searchParams.get("step");

  useEffect(() => {
    if (!resumeSite || resumeStep !== "install") return;
    let cancelled = false;
    (async () => {
      try {
        const pixel = await api.getPixelSnippet(resumeSite);
        if (cancelled) return;
        setSiteId(resumeSite);
        setSnippet(pixel.snippet);
        setStep("install");
      } catch {
        // Bad/expired site id — leave the user on the create step to start over.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [resumeSite, resumeStep]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setShowUpgrade(false);
    setLoading(true);

    try {
      const site = await api.createSite(name, url, description || undefined);
      setSiteId(site.site_id);
      // Completing onboarding counts as onboarded: never force the welcome
      // → add-site funnel again, even if every site is later deleted.
      try {
        localStorage.setItem("beam_onboarded_v1", "1");
      } catch {
        /* storage blocked — worst case the funnel re-offers next visit */
      }

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
      const detail = (err as { detail?: { code?: string } } | null)?.detail;
      setShowUpgrade(detail?.code === "site_limit_reached");
      setError(err instanceof Error ? err.message : "Failed to create site");
    } finally {
      setLoading(false);
    }
  }

  function handleVerified() {
    router.push("/dashboard");
  }

  // ────────── Step indicator ──────────
  const steps = [
    { key: "create", label: "Add Site" },
    { key: "install", label: "Install Pixel" },
  ];

  const currentIndex = steps.findIndex((s) => s.key === step);

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress bar — hidden on the welcome intro */}
      {step !== "welcome" && (
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
      )}

      {/* Step 0: Welcome intro (first-run only) */}
      {step === "welcome" && (
        <Card>
          <CardHeader>
            <CardTitle>Welcome to Beam</CardTitle>
            <CardDescription>
              Beam turns your anonymous website traffic into people you can
              actually reach — then drafts the outreach for you.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-3 text-sm">
              <li className="flex items-start gap-3">
                <span className="mt-0.5 flex-shrink-0 flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary font-bold">
                  1
                </span>
                <span>
                  <span className="font-medium text-foreground">
                    Identify visitors
                  </span>{" "}
                  <span className="text-muted-foreground">
                    — see the real people and companies browsing your site.
                  </span>
                </span>
              </li>
              <li className="flex items-start gap-3">
                <span className="mt-0.5 flex-shrink-0 flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary font-bold">
                  2
                </span>
                <span>
                  <span className="font-medium text-foreground">
                    Enrich profiles
                  </span>{" "}
                  <span className="text-muted-foreground">
                    — LinkedIn, role, and company details, added automatically.
                  </span>
                </span>
              </li>
              <li className="flex items-start gap-3">
                <span className="mt-0.5 flex-shrink-0 flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary font-bold">
                  3
                </span>
                <span>
                  <span className="font-medium text-foreground">
                    Draft outreach
                  </span>{" "}
                  <span className="text-muted-foreground">
                    — AI writes the email and social follow-ups; you approve and
                    send.
                  </span>
                </span>
              </li>
            </ul>
            <Button
              type="button"
              className="w-full mt-6"
              size="lg"
              onClick={() => setStep("create")}
            >
              Get started
            </Button>
            <p className="mt-3 text-center text-xs text-muted-foreground">
              Takes about a minute — add your site, then drop in one snippet.
            </p>
          </CardContent>
        </Card>
      )}

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
              {error && (
                <p className="text-sm text-destructive">
                  {error}
                  {showUpgrade && (
                    <>
                      {" "}
                      <a href="/pricing" className="underline font-medium">
                        View plans
                      </a>
                    </>
                  )}
                </p>
              )}
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

    </div>
  );
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
      <OnboardingFlow />
    </Suspense>
  );
}
