"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, Site, ApiKeyInfo } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";
import { SiteSelector } from "@/components/site-selector";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const PROVIDERS = [
  {
    id: "openrouter",
    name: "OpenRouter",
    description: "AI replies — 100+ models (Grok, Llama, GPT-4o-mini, etc.)",
    docsUrl: "https://openrouter.ai/keys",
    color: "text-[#FF3366]",
  },
  {
    id: "proxycurl",
    name: "Proxycurl",
    description: "LinkedIn profile enrichment",
    docsUrl: "https://nubela.co/proxycurl",
    color: "text-blue-600",
  },
  {
    id: "twitter",
    name: "Twitter / X",
    description: "Twitter bio & followers",
    docsUrl: "https://developer.twitter.com",
    color: "text-sky-600",
  },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [siteId, setSiteId] = useState(searchParams.get("site") || "");
  const [site, setSite] = useState<Site | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [siteRetryKey, setSiteRetryKey] = useState(0);
  const [snippet, setSnippet] = useState("");
  const [copied, setCopied] = useState(false);

  // Verify state
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{
    status: string;
    message: string;
  } | null>(null);

  // API Keys state
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([]);
  const [showAddKey, setShowAddKey] = useState(false);
  const [addProvider, setAddProvider] = useState("proxycurl");
  const [addKeyValue, setAddKeyValue] = useState("");
  const [addingKey, setAddingKey] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [keysLoadError, setKeysLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId) return;
    setSiteError(null);
    api
      .getSite(siteId)
      .then(setSite)
      .catch((e: Error) => setSiteError(e.message));
    api
      .getPixelSnippet(siteId)
      .then((r) => setSnippet(r.snippet))
      .catch(() => {});
    setVerifyResult(null);
  }, [siteId, siteRetryKey]);

  // Load API keys (not site-specific)
  function loadApiKeys() {
    setKeysLoadError(null);
    api
      .listApiKeys()
      .then(setApiKeys)
      .catch((e: Error) => setKeysLoadError(e.message));
  }

  useEffect(loadApiKeys, []);

  function handleCopy() {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleVerify() {
    if (!siteId) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = await api.verifyPixel(siteId);
      setVerifyResult({ status: result.status, message: result.message });
      if (result.verified && site) {
        setSite({ ...site, pixel_verified: true });
      }
    } catch {
      setVerifyResult({
        status: "error",
        message: "Could not verify. Please try again.",
      });
    } finally {
      setVerifying(false);
    }
  }

  async function handleAddKey() {
    if (!addKeyValue.trim()) return;
    setAddingKey(true);
    setKeyError("");
    try {
      const saved = await api.saveApiKey(addProvider, addKeyValue.trim());
      setApiKeys((prev) => [
        ...prev.filter((k) => k.provider !== addProvider),
        saved,
      ]);
      setShowAddKey(false);
      setAddKeyValue("");
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setAddingKey(false);
    }
  }

  async function handleDeleteKey(provider: string) {
    try {
      await api.deleteApiKey(provider);
      setApiKeys((prev) => prev.filter((k) => k.provider !== provider));
    } catch {
      // ignore
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-serif font-semibold tracking-tight">Settings</h2>
        <SiteSelector value={siteId} onChange={setSiteId} />
      </div>

      {/* ── API Keys (BYOK) ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">API Keys (BYOK)</CardTitle>
          <CardDescription>
            Add your API keys to power AI replies (OpenRouter) and deep
            enrichment (LinkedIn, Twitter). Keys are encrypted at rest.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Existing keys */}
          {keysLoadError ? (
            <ErrorBanner
              message={`Couldn't load API keys — ${keysLoadError}`}
              onRetry={loadApiKeys}
            />
          ) : apiKeys.length > 0 ? (
            <div className="space-y-2">
              {apiKeys.map((key) => {
                const provider = PROVIDERS.find((p) => p.id === key.provider);
                return (
                  <div
                    key={key.provider}
                    className="flex items-center justify-between p-3 rounded-md bg-muted"
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`font-medium text-sm ${provider?.color || ""}`}
                      >
                        {provider?.name || key.provider}
                      </span>
                      <code className="text-xs text-muted-foreground">
                        {key.key_hint}
                      </code>
                      {key.is_valid ? (
                        <span className="text-xs text-green-500 font-medium">
                          Valid
                        </span>
                      ) : (
                        <span className="text-xs text-red-500 font-medium">
                          Invalid
                        </span>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => handleDeleteKey(key.provider)}
                    >
                      Remove
                    </Button>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No API keys configured. Add a key to unlock Tier 2 enrichment.
            </p>
          )}

          {/* Add key form */}
          {showAddKey ? (
            <div className="space-y-3 p-4 rounded-md border border-border">
              <div className="space-y-2">
                <label className="text-sm font-medium">Provider</label>
                <select
                  value={addProvider}
                  onChange={(e) => setAddProvider(e.target.value)}
                  className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border"
                >
                  {PROVIDERS.filter(
                    (p) => !apiKeys.find((k) => k.provider === p.id)
                  ).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — {p.description}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">API Key</label>
                <input
                  type="password"
                  value={addKeyValue}
                  onChange={(e) => setAddKeyValue(e.target.value)}
                  placeholder="Paste your API key here"
                  className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border font-mono"
                />
              </div>
              {keyError && (
                <p className="text-sm text-destructive">{keyError}</p>
              )}
              <div className="flex gap-2">
                <Button
                  onClick={handleAddKey}
                  disabled={!addKeyValue.trim() || addingKey}
                  size="sm"
                >
                  {addingKey ? "Validating..." : "Test & Save"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowAddKey(false);
                    setAddKeyValue("");
                    setKeyError("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddKey(true)}
              disabled={apiKeys.length >= PROVIDERS.length}
            >
              + Add API Key
            </Button>
          )}
        </CardContent>
      </Card>

      {!siteId ? (
        <p className="text-muted-foreground">Select a site to view settings.</p>
      ) : siteError ? (
        <ErrorBanner
          message={`Couldn't load site settings — ${siteError}`}
          onRetry={() => setSiteRetryKey((k) => k + 1)}
        />
      ) : !site ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Site Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name</span>
                <span>{site.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">URL</span>
                <span>{site.url}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Site ID</span>
                <span className="font-mono text-xs">{site.site_id}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Pixel verified</span>
                <div className="flex items-center gap-2">
                  {site.pixel_verified ? (
                    <span className="inline-flex items-center gap-1 text-green-500 font-medium">
                      <svg
                        className="w-4 h-4"
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
                      Verified
                    </span>
                  ) : (
                    <>
                      <span className="text-yellow-500">Not yet</span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleVerify}
                        disabled={verifying}
                      >
                        {verifying ? "Checking..." : "Verify Now"}
                      </Button>
                    </>
                  )}
                </div>
              </div>
              {verifyResult && (
                <p
                  className={`text-xs text-right ${
                    verifyResult.status === "verified"
                      ? "text-green-500"
                      : "text-yellow-500"
                  }`}
                >
                  {verifyResult.message}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Pixel Snippet</CardTitle>
              <CardDescription>
                Paste this before the closing &lt;/head&gt; tag
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="relative">
                <pre className="rounded-md bg-muted p-4 text-xs overflow-x-auto whitespace-pre-wrap break-all">
                  {snippet}
                </pre>
                <Button
                  variant="outline"
                  size="sm"
                  className="absolute top-2 right-2"
                  onClick={handleCopy}
                >
                  {copied ? "Copied!" : "Copy"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Budget Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">
                  Daily resolution budget
                </span>
                <span>{site.daily_resolution_budget} lookups/day</span>
              </div>
              <Separator />
              <p className="text-xs text-muted-foreground">
                Contact support to adjust budget limits. Billing dashboard
                coming soon.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
