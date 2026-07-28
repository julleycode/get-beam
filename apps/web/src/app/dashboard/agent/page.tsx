"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  api,
  type AgentCapability,
  type AgentOffer,
  type AgentProfile,
} from "@/lib/api";
import { SiteSelector } from "@/components/site-selector";
import { PageHeader } from "@/components/page-header";
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

const CAPABILITIES: { value: AgentCapability; label: string; hint: string }[] = [
  { value: "request_demo", label: "Request a demo", hint: "Agent can ask for a demo on a user's behalf" },
  { value: "get_quote", label: "Get a quote", hint: "Agent can request pricing for a described need" },
  { value: "join_waitlist", label: "Join the waitlist", hint: "Agent can put a user on your waitlist" },
  { value: "start_checkout", label: "Start checkout", hint: "Agent can hand the user your checkout link" },
];

const EMPTY_OFFER: AgentOffer = {
  name: "",
  price: "",
  currency: "",
  billing_period: "",
  availability: "",
  url: "",
};

type FormState = {
  enabled: boolean;
  tagline: string;
  long_description: string;
  offers: AgentOffer[];
  capabilities: AgentCapability[];
  primary_cta: string;
  privacy_policy_url: string;
  tos_url: string;
  contact_email: string;
};

const EMPTY_FORM: FormState = {
  enabled: false,
  tagline: "",
  long_description: "",
  offers: [],
  capabilities: [],
  primary_cta: "",
  privacy_policy_url: "",
  tos_url: "",
  contact_email: "",
};

function toForm(profile: AgentProfile): FormState {
  return {
    enabled: profile.enabled,
    tagline: profile.tagline ?? "",
    long_description: profile.long_description ?? "",
    offers: profile.offers ?? [],
    capabilities: profile.capabilities ?? [],
    primary_cta: profile.primary_cta ?? "",
    privacy_policy_url: profile.privacy_policy_url ?? "",
    tos_url: profile.tos_url ?? "",
    contact_email: profile.contact_email ?? "",
  };
}

/** Blank strings are sent as null so a cleared field actually clears. */
function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export default function AgentProfilePage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setMessage(null);
    setError(null);
    try {
      const profile = await api.getAgentProfile(id);
      setForm(toForm(profile));
    } catch {
      // A 404 here is the normal first-visit case — no profile saved yet.
      // Nothing is created by a read, so just present an empty form.
      setForm(EMPTY_FORM);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!siteId) return;
    load(siteId);
  }, [siteId, load]);

  function patch(changes: Partial<FormState>) {
    setForm((prev) => ({ ...prev, ...changes }));
    setMessage(null);
  }

  function toggleCapability(cap: AgentCapability) {
    patch({
      capabilities: form.capabilities.includes(cap)
        ? form.capabilities.filter((c) => c !== cap)
        : [...form.capabilities, cap],
    });
  }

  function updateOffer(index: number, changes: Partial<AgentOffer>) {
    patch({
      offers: form.offers.map((offer, i) =>
        i === index ? { ...offer, ...changes } : offer
      ),
    });
  }

  async function save() {
    if (!siteId) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await api.saveAgentProfile(siteId, {
        enabled: form.enabled,
        tagline: blankToNull(form.tagline),
        long_description: blankToNull(form.long_description),
        // Drop half-filled rows: an offer with no name has nothing to publish.
        offers: form.offers.filter((o) => o.name.trim() !== ""),
        capabilities: form.capabilities,
        primary_cta: blankToNull(form.primary_cta),
        privacy_policy_url: blankToNull(form.privacy_policy_url),
        tos_url: blankToNull(form.tos_url),
        contact_email: blankToNull(form.contact_email),
      });
      setForm(toForm(saved));
      setMessage(
        // E6: the public agent surface shares the llms.txt / ai-plugin.json cache
        // header (s-maxage=3600, stale-while-revalidate=86400). Say so plainly
        // rather than letting a customer think a save didn't take.
        "Saved. Your dashboard updates immediately. Public agent-facing content is cached, so changes can take up to ~24 hours to propagate everywhere."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save. Try again.");
    } finally {
      setSaving(false);
    }
  }

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "https://api.getbeam.fyi";
  const snippet = siteId
    ? `<!-- Beam agent gateway: point AI agents at what you sell -->
<link rel="alternate" type="application/json"
      href="${apiBase}/api/v1/agent/${siteId}/manifest.json" />
<link rel="alternate" type="text/plain"
      href="${apiBase}/api/v1/agent/${siteId}/llms.txt" />
<script type="application/ld+json">
${JSON.stringify(
  {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: form.tagline || undefined,
    description: form.long_description || undefined,
    url: `${apiBase}/api/v1/agent/${siteId}/manifest.json`,
  },
  null,
  2
)}
</script>`
    : "";

  return (
    <div>
      <PageHeader
        title="Agent profile"
        actions={<SiteSelector value={siteId} onChange={setSiteId} />}
      />

      {!siteId ? (
        <p className="text-sm text-muted-foreground">
          Pick a site to describe what it sells.
        </p>
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>What this business sells</CardTitle>
              <CardDescription>
                AI assistants read this when someone asks them about you. Plain
                language beats marketing copy here.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="tagline">One-line summary</Label>
                <Input
                  id="tagline"
                  value={form.tagline}
                  maxLength={300}
                  placeholder="Widgets that ship the same day"
                  onChange={(e) => patch({ tagline: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="long_description">Full description</Label>
                <Textarea
                  id="long_description"
                  rows={5}
                  value={form.long_description}
                  placeholder="Who you serve, what you do for them, what makes you different."
                  onChange={(e) => patch({ long_description: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="primary_cta">What should someone do next?</Label>
                <Input
                  id="primary_cta"
                  value={form.primary_cta}
                  maxLength={500}
                  placeholder="Book a 20-minute demo"
                  onChange={(e) => patch({ primary_cta: e.target.value })}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Offers</CardTitle>
              <CardDescription>
                Products or plans, with prices if you publish them.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {form.offers.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No offers yet.
                </p>
              ) : (
                form.offers.map((offer, index) => (
                  <div
                    key={index}
                    className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2"
                  >
                    <div className="space-y-2">
                      <Label htmlFor={`offer-name-${index}`}>Name</Label>
                      <Input
                        id={`offer-name-${index}`}
                        value={offer.name}
                        onChange={(e) =>
                          updateOffer(index, { name: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`offer-price-${index}`}>Price</Label>
                      <Input
                        id={`offer-price-${index}`}
                        value={offer.price ?? ""}
                        placeholder="49"
                        onChange={(e) =>
                          updateOffer(index, { price: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`offer-currency-${index}`}>Currency</Label>
                      <Input
                        id={`offer-currency-${index}`}
                        value={offer.currency ?? ""}
                        placeholder="USD"
                        onChange={(e) =>
                          updateOffer(index, { currency: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`offer-period-${index}`}>
                        Billing period
                      </Label>
                      <Input
                        id={`offer-period-${index}`}
                        value={offer.billing_period ?? ""}
                        placeholder="month"
                        onChange={(e) =>
                          updateOffer(index, { billing_period: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`offer-availability-${index}`}>
                        Availability
                      </Label>
                      <Input
                        id={`offer-availability-${index}`}
                        value={offer.availability ?? ""}
                        placeholder="in_stock"
                        onChange={(e) =>
                          updateOffer(index, { availability: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`offer-url-${index}`}>Link</Label>
                      <Input
                        id={`offer-url-${index}`}
                        value={offer.url ?? ""}
                        placeholder="https://…"
                        onChange={(e) =>
                          updateOffer(index, { url: e.target.value })
                        }
                      />
                    </div>
                    <div className="sm:col-span-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          patch({
                            offers: form.offers.filter((_, i) => i !== index),
                          })
                        }
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                ))
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  patch({ offers: [...form.offers, { ...EMPTY_OFFER }] })
                }
              >
                Add an offer
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>What agents may ask for</CardTitle>
              <CardDescription>
                These are published as declarations only for now. An agent is
                told what you support, and nothing is actioned automatically.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {CAPABILITIES.map((cap) => (
                <label
                  key={cap.value}
                  className="flex items-start gap-3 text-sm"
                  htmlFor={`cap-${cap.value}`}
                >
                  <input
                    id={`cap-${cap.value}`}
                    type="checkbox"
                    className="mt-1"
                    checked={form.capabilities.includes(cap.value)}
                    onChange={() => toggleCapability(cap.value)}
                  />
                  <span>
                    <span className="font-medium">{cap.label}</span>
                    <span className="block text-muted-foreground">
                      {cap.hint}
                    </span>
                  </span>
                </label>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Contact and policies</CardTitle>
              <CardDescription>
                Optional. Everything here becomes publicly readable once you
                publish, so use a contact address you are happy to share.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="contact_email">Contact email</Label>
                <Input
                  id="contact_email"
                  value={form.contact_email}
                  placeholder="sales@example.com"
                  onChange={(e) => patch({ contact_email: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="privacy_policy_url">Privacy policy URL</Label>
                <Input
                  id="privacy_policy_url"
                  value={form.privacy_policy_url}
                  placeholder="https://example.com/privacy"
                  onChange={(e) =>
                    patch({ privacy_policy_url: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tos_url">Terms of service URL</Label>
                <Input
                  id="tos_url"
                  value={form.tos_url}
                  placeholder="https://example.com/terms"
                  onChange={(e) => patch({ tos_url: e.target.value })}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Publish</CardTitle>
              <CardDescription>
                Off by default. While this is off, every public agent endpoint
                for this site returns &ldquo;not found&rdquo; and nothing you
                wrote above is readable by anyone else.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label
                className="flex items-start gap-3 text-sm"
                htmlFor="enabled"
              >
                <input
                  id="enabled"
                  type="checkbox"
                  className="mt-1"
                  checked={form.enabled}
                  onChange={(e) => patch({ enabled: e.target.checked })}
                />
                <span>
                  <span className="font-medium">
                    Make this readable by AI agents
                  </span>
                  <span className="block text-muted-foreground">
                    Publishes the manifest, offers feed, llms.txt and MCP
                    endpoints for this site.
                  </span>
                </span>
              </label>

              <div className="flex items-center gap-3">
                <Button onClick={save} disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </Button>
                {message ? (
                  <span className="text-sm text-muted-foreground">
                    {message}
                  </span>
                ) : null}
                {error ? (
                  <span className="text-sm text-destructive">{error}</span>
                ) : null}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Add this to your site</CardTitle>
              <CardDescription>
                Paste into your <code>&lt;head&gt;</code>, same as the Beam
                pixel. It tells agents where to find the machine-readable
                version of everything above.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <pre className="overflow-x-auto rounded-lg border bg-muted p-4 text-xs">
                <code>{snippet}</code>
              </pre>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigator.clipboard?.writeText(snippet)}
              >
                Copy snippet
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
