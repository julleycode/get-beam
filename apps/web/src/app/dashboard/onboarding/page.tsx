"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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

type Step = "create" | "install" | "done";

export default function OnboardingPage() {
  const router = useRouter();

  // Step 1: Create site
  const [step, setStep] = useState<Step>("create");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Step 2: Install pixel
  const [siteId, setSiteId] = useState("");
  const [snippet, setSnippet] = useState("");
  const [platform, setPlatform] = useState("unknown");
  const [hasGtm, setHasGtm] = useState(false);
  const [gtmId, setGtmId] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // 1. Create the site
      const site = await api.createSite(name, url, description || undefined);
      setSiteId(site.site_id);

      // 2. Get pixel snippet
      const pixel = await api.getPixelSnippet(site.site_id);
      setSnippet(pixel.snippet);

      // 3. Auto-detect platform
      setDetecting(true);
      setStep("install");

      try {
        const detected = await api.detectPlatform(url);
        setPlatform(detected.platform);
        setHasGtm(detected.has_gtm);
        setGtmId(detected.gtm_id);
      } catch {
        // Detection failed — fall back to "unknown" (manual install)
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
    setTimeout(() => router.push("/dashboard"), 2000);
  }

  // ────────── Step indicator ──────────
  const steps = [
    { key: "create", label: "Add Site" },
    { key: "install", label: "Install Pixel" },
    { key: "done", label: "Verified" },
  ];

  const currentIndex = steps.findIndex((s) => s.key === step);

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

      {/* Step 3: Done */}
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
              Your tracking pixel is live. Visitor data will start appearing on
              your dashboard within minutes.
            </p>
            <p className="text-sm text-muted-foreground animate-pulse">
              Redirecting to dashboard...
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
