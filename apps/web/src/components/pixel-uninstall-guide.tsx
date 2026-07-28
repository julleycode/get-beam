"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface PixelUninstallGuideProps {
  platform: string;
  snippet: string;
  siteId: string;
  /** Optional callback fired once the pixel is confirmed removed. */
  onRemoved?: () => void;
}

interface RemovalStep {
  title: string;
  description: string;
}

interface RemovalGuide {
  name: string;
  /** Whether the user's actual snippet is shown so they can find-and-delete it. */
  showSnippet: boolean;
  steps: RemovalStep[];
  note?: string;
}

// Platform-specific REMOVAL instructions. Mirrors the shape of platform-guides
// but for taking the pixel OUT. Manual/custom platforms get the snippet rendered
// so the user can find the exact <script> to delete; managed platforms (Shopify,
// WordPress) just get app/plugin-removal steps — no auto-uninstall.
const REMOVAL_GUIDES: Record<string, RemovalGuide> = {
  shopify: {
    name: "Shopify",
    showSnippet: false,
    steps: [
      {
        title: "Open Shopify Admin",
        description: "Go to your Shopify store and open the Apps section.",
      },
      {
        title: "Remove the Beam app",
        description:
          "Shopify Admin → Apps → remove the Beam app. The ScriptTag is removed automatically.",
      },
    ],
    note: "No code changes needed. Removing the app deletes the pixel from every page.",
  },
  wordpress: {
    name: "WordPress",
    showSnippet: false,
    steps: [
      {
        title: "Open the Plugins list",
        description: "Go to your WordPress admin → Plugins.",
      },
      {
        title: "Deactivate and delete",
        description: "Plugins → Deactivate, then Delete the Beam Pixel plugin.",
      },
    ],
    note: "Once the plugin is deleted, the pixel no longer runs on your site.",
  },
  unknown: {
    name: "Your website",
    showSnippet: true,
    steps: [
      {
        title: "Open your page HTML",
        description:
          "Go to wherever you pasted the snippet before (usually Custom Code / Header Scripts in your settings).",
      },
      {
        title: "Delete the Beam script",
        description:
          "Remove the <script ...tracker.js...> tag just before </head>. Use the code below to find the exact spot.",
      },
    ],
    note: "After removing it, save and publish your page for the change to take effect.",
  },
};

function getRemovalGuide(platform: string): RemovalGuide {
  return REMOVAL_GUIDES[platform] || REMOVAL_GUIDES.unknown;
}

export function PixelUninstallGuide({
  platform,
  snippet,
  siteId,
  onRemoved,
}: PixelUninstallGuideProps) {
  const guide = getRemovalGuide(platform);
  const [copied, setCopied] = useState(false);
  const [promptCopied, setPromptCopied] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<{
    status: "removed" | "still-present" | "error";
    message: string;
  } | null>(null);

  function handleCopy() {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Hand the removal to an AI coding agent — same one-shot pattern as the install
  // guide, but the prompt asks the agent to FIND and DELETE the Beam script tag.
  function handleCopyPrompt() {
    const platformLabel =
      platform === "unknown" ? "website" : guide.name;
    const prompt = [
      `Remove the Beam tracking pixel from my ${platformLabel} (site_id: ${siteId}).`,
      ``,
      `Find this snippet in the site's <head> (just before the closing </head> tag) and delete it completely:`,
      snippet,
      ``,
      `The script loads tracker.js and references site_id "${siteId}". Remove the entire <script> tag — do not leave any leftover script or data attributes.`,
    ]
      .join("\n")
      .trim();
    navigator.clipboard.writeText(prompt);
    setPromptCopied(true);
    setTimeout(() => setPromptCopied(false), 2000);
  }

  async function handleCheck() {
    setChecking(true);
    setCheckResult(null);
    try {
      const result = await api.verifyPixel(siteId);
      // Inverted meaning vs. install: success is when the pixel is GONE.
      if (result.verified === false) {
        setCheckResult({
          status: "removed",
          message: "✓ Pixel removed from your site.",
        });
        if (onRemoved) {
          setTimeout(onRemoved, 1500);
        }
      } else {
        setCheckResult({
          status: "still-present",
          message: "Pixel still detected. Try again after removing it from your site.",
        });
      }
    } catch {
      setCheckResult({
        status: "error",
        message: "Couldn't check. Please try again.",
      });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Platform badge */}
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border bg-muted text-muted-foreground border-border">
          {guide.name}
        </span>
      </div>

      <p className="text-sm text-muted-foreground">
        You can remove the pixel any time. Follow the steps below, then click
        “Check if removed” to confirm the pixel is gone from your site.
      </p>

      {/* Removal steps */}
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

      {/* Snippet to find-and-delete (manual/custom platforms only) */}
      {guide.showSnippet && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Code to remove</CardTitle>
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
            <div className="mt-3 flex flex-col gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                className="w-full sm:w-auto"
                onClick={handleCopyPrompt}
              >
                {promptCopied ? "Prompt copied ✓" : "Copy prompt to Claude"}
              </Button>
              <p className="text-xs text-muted-foreground">
                Paste it into Cursor, Claude Code, or any AI coding agent. It
                will find and delete the Beam script from your site.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Check-removed button */}
      <div className="pt-2">
        <Button
          onClick={handleCheck}
          disabled={checking}
          className="w-full"
          size="lg"
          variant={checkResult?.status === "removed" ? "default" : "outline"}
        >
          {checking
            ? "Checking your site..."
            : checkResult?.status === "removed"
              ? "Pixel removed ✓"
              : "Check if removed"}
        </Button>

        {checkResult && (
          <p
            className={`text-sm mt-2 text-center ${
              checkResult.status === "removed"
                ? "text-success"
                : "text-warning"
            }`}
          >
            {checkResult.message}
          </p>
        )}
      </div>
    </div>
  );
}
