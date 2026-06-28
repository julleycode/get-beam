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
        title: "Mở Shopify Admin",
        description: "Vào cửa hàng Shopify của bạn, mở mục Apps.",
      },
      {
        title: "Gỡ app Beam",
        description:
          "Mở Shopify Admin → Apps → gỡ app Beam. ScriptTag sẽ tự biến mất.",
      },
    ],
    note: "Không cần sửa code — gỡ app là pixel tự bị xoá khỏi mọi trang.",
  },
  wordpress: {
    name: "WordPress",
    showSnippet: false,
    steps: [
      {
        title: "Mở danh sách Plugins",
        description: "Vào WordPress admin → Plugins.",
      },
      {
        title: "Tắt và xoá plugin",
        description: "Vào Plugins → Deactivate rồi Delete plugin Beam Pixel.",
      },
    ],
    note: "Sau khi xoá plugin, pixel sẽ không còn chạy trên web nữa.",
  },
  unknown: {
    name: "Website của bạn",
    showSnippet: true,
    steps: [
      {
        title: "Mở HTML của trang",
        description:
          "Vào nơi bạn đã dán đoạn code trước đây (thường là phần Custom Code / Header Scripts trong settings).",
      },
      {
        title: "Xoá đoạn script Beam",
        description:
          "Xoá đoạn <script ...tracker.js...> ngay trước </head>. Dùng đoạn code bên dưới để tìm đúng vị trí.",
      },
    ],
    note: "Sau khi xoá, lưu lại và publish trang để thay đổi có hiệu lực.",
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
          message: "✓ Đã gỡ pixel khỏi web.",
        });
        if (onRemoved) {
          setTimeout(onRemoved, 1500);
        }
      } else {
        setCheckResult({
          status: "still-present",
          message: "Vẫn thấy pixel — thử lại sau khi xoá khỏi web.",
        });
      }
    } catch {
      setCheckResult({
        status: "error",
        message: "Không kiểm tra được. Vui lòng thử lại.",
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
        Bạn có thể gỡ pixel bất cứ lúc nào. Làm theo các bước dưới đây, sau đó
        bấm “Kiểm tra đã gỡ” để chắc chắn pixel đã được xoá khỏi web.
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
            <CardTitle className="text-sm">Đoạn code cần xoá</CardTitle>
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
                {copied ? "Đã copy!" : "Copy"}
              </Button>
            </div>
            <div className="mt-3 flex flex-col gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                className="w-full sm:w-auto"
                onClick={handleCopyPrompt}
              >
                {promptCopied ? "Đã copy prompt ✓" : "Copy prompt to Claude"}
              </Button>
              <p className="text-xs text-muted-foreground">
                Dán vào Cursor, Claude Code, hoặc bất kỳ AI coding agent nào — nó
                sẽ tự tìm và xoá đoạn script Beam khỏi web của bạn.
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
            ? "Đang kiểm tra web..."
            : checkResult?.status === "removed"
              ? "Đã gỡ pixel ✓"
              : "Kiểm tra đã gỡ"}
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
