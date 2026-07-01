"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { api, ApiKeyInfo } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { ErrorBanner } from "@/components/error-banner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const PROVIDERS = [
  {
    id: "openrouter",
    name: "OpenRouter",
    description: "AI replies — 100+ models (Grok, Llama, GPT-4o-mini, etc.)",
    docsUrl: "https://openrouter.ai/keys",
    color: "text-primary",
  },
  {
    id: "proxycurl",
    name: "Proxycurl",
    description: "LinkedIn profile enrichment",
    docsUrl: "https://nubela.co/proxycurl",
    color: "text-info",
  },
  {
    id: "twitter",
    name: "Twitter / X",
    description: "Twitter bio & followers",
    docsUrl: "https://developer.twitter.com",
    color: "text-info",
  },
];

/**
 * Account-level BYOK API keys. Lives on the Billing page (moved off the removed
 * Settings tab). Gates its own fetch on Clerk auth so it doesn't 401-race the
 * token sync (same pattern as the Billing status fetch).
 */
export function ApiKeysCard() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([]);
  const [showAddKey, setShowAddKey] = useState(false);
  const [addProvider, setAddProvider] = useState("proxycurl");
  const [addKeyValue, setAddKeyValue] = useState("");
  const [addingKey, setAddingKey] = useState(false);
  const [keyError, setKeyError] = useState("");
  const [keysLoadError, setKeysLoadError] = useState<string | null>(null);

  function loadApiKeys() {
    setKeysLoadError(null);
    api
      .listApiKeys()
      .then(setApiKeys)
      .catch((e: Error) => setKeysLoadError(e.message));
  }

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    let cancelled = false;
    (async () => {
      try {
        const t = await getToken();
        if (t) api.setClerkToken(t);
        const keys = await api.listApiKeys();
        if (!cancelled) setApiKeys(keys);
      } catch (e) {
        if (!cancelled) setKeysLoadError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken]);

  async function handleAddKey() {
    if (!addKeyValue.trim()) return;
    setAddingKey(true);
    setKeyError("");
    try {
      const saved = await api.saveApiKey(addProvider, addKeyValue.trim());
      setApiKeys((prev) => [...prev.filter((k) => k.provider !== addProvider), saved]);
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
    } catch (err) {
      setKeyError(err instanceof Error ? err.message : "Failed to delete key");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">API Keys (BYOK)</CardTitle>
        <CardDescription>
          Add your API keys to power AI replies (OpenRouter) and deep enrichment
          (LinkedIn, Twitter). Keys are encrypted at rest.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
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
                    <span className={`font-medium text-sm ${provider?.color || ""}`}>
                      {provider?.name || key.provider}
                    </span>
                    <code className="text-xs text-muted-foreground">{key.key_hint}</code>
                    <StatusBadge status={key.is_valid ? "valid" : "invalid"} />
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

        {showAddKey ? (
          <div className="space-y-3 p-4 rounded-md border border-border">
            <div className="space-y-2">
              <label className="text-sm font-medium">Provider</label>
              <select
                value={addProvider}
                onChange={(e) => setAddProvider(e.target.value)}
                className="w-full px-3 py-2 bg-muted rounded-md text-sm border border-border"
              >
                {PROVIDERS.filter((p) => !apiKeys.find((k) => k.provider === p.id)).map(
                  (p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — {p.description}
                    </option>
                  )
                )}
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
            {keyError && <p className="text-sm text-destructive">{keyError}</p>}
            <div className="flex gap-2">
              <Button onClick={handleAddKey} disabled={!addKeyValue.trim() || addingKey} size="sm">
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
  );
}
