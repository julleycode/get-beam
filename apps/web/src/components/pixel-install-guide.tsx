"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { getGuide } from "@/lib/platform-guides";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface PixelInstallGuideProps {
  platform: string;
  hasGtm: boolean;
  gtmId: string | null;
  snippet: string;
  siteId: string;
  onVerified: () => void;
}

const PLATFORM_COLORS: Record<string, string> = {
  shopify: "bg-green-900/30 text-green-400 border-green-800",
  wordpress: "bg-blue-900/30 text-blue-400 border-blue-800",
  wix: "bg-yellow-900/30 text-yellow-400 border-yellow-800",
  squarespace: "bg-gray-800/50 text-gray-300 border-gray-700",
  webflow: "bg-[#8F0F30]/30 text-[#FF7D9C] border-[#B31543]",
  unknown: "bg-gray-800/50 text-gray-400 border-gray-700",
};

export function PixelInstallGuide({
  platform,
  hasGtm,
  gtmId,
  snippet,
  siteId,
  onVerified,
}: PixelInstallGuideProps) {
  const guide = getGuide(platform);
  const [copied, setCopied] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{
    status: string;
    message: string;
  } | null>(null);
  const [shopifyShop, setShopifyShop] = useState("");
  const [connectingShopify, setConnectingShopify] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleVerify() {
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = await api.verifyPixel(siteId);
      setVerifyResult({ status: result.status, message: result.message });
      if (result.verified) {
        setTimeout(onVerified, 1500);
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

  async function handleShopifyConnect() {
    if (!shopifyShop.trim()) return;
    setConnectingShopify(true);
    try {
      const result = await api.shopifyConnect(siteId, shopifyShop.trim());
      window.location.href = result.install_url;
    } catch (err) {
      setVerifyResult({
        status: "error",
        message:
          err instanceof Error ? err.message : "Failed to connect Shopify",
      });
      setConnectingShopify(false);
    }
  }

  async function handleDownloadPlugin() {
    try {
      await api.downloadWordPressPlugin(siteId);
    } catch {
      setVerifyResult({
        status: "error",
        message: "Failed to download plugin. Please try again.",
      });
    }
  }

  const colorClass = PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown;

  return (
    <div className="space-y-6">
      {/* Platform badge */}
      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border ${colorClass}`}
        >
          {platform === "unknown" ? "Custom Website" : guide.name}
        </span>
        {hasGtm && gtmId && (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-900/30 text-blue-400 border border-blue-800">
            GTM: {gtmId}
          </span>
        )}
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {guide.steps.map((step, i) => (
          <Card key={i} className="border-muted">
            <CardContent className="py-4 px-5">
              <div className="flex gap-4">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold">
                  {i + 1}
                </div>
                <div>
                  <h4 className="font-medium text-sm">{step.title}</h4>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {step.description}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {guide.note && (
        <p className="text-xs text-muted-foreground italic">{guide.note}</p>
      )}

      {/* Platform-specific action */}
      {platform === "shopify" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Connect Shopify Store</CardTitle>
            <CardDescription>
              Enter your Shopify store URL to auto-install the pixel
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={shopifyShop}
                onChange={(e) => setShopifyShop(e.target.value)}
                placeholder="mystore.myshopify.com"
                className="flex-1 px-3 py-2 bg-muted rounded-md text-sm border border-border"
              />
              <Button
                onClick={handleShopifyConnect}
                disabled={!shopifyShop.trim() || connectingShopify}
              >
                {connectingShopify ? "Connecting..." : "Connect"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {platform === "wordpress" && (
        <Button onClick={handleDownloadPlugin} className="w-full" size="lg">
          Download WordPress Plugin
        </Button>
      )}

      {/* Snippet (always shown for manual platforms, collapsible for others) */}
      {(guide.installType === "manual" ||
        platform === "unknown" ||
        hasGtm) && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Code Snippet</CardTitle>
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
      )}

      {/* Verify button */}
      <div className="pt-2">
        <Button
          onClick={handleVerify}
          disabled={verifying}
          className="w-full"
          size="lg"
          variant={
            verifyResult?.status === "verified" ? "default" : "outline"
          }
        >
          {verifying
            ? "Checking your website..."
            : verifyResult?.status === "verified"
              ? "Verified! Redirecting..."
              : "Verify Installation"}
        </Button>

        {verifyResult && (
          <p
            className={`text-sm mt-2 text-center ${
              verifyResult.status === "verified"
                ? "text-green-500"
                : "text-yellow-500"
            }`}
          >
            {verifyResult.message}
          </p>
        )}
      </div>
    </div>
  );
}
