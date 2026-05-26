import clsx from "clsx";
import type { Platform } from "@/lib/api";

const PLATFORM_COLORS: Record<Platform, string> = {
  twitter: "bg-sky-100 text-sky-700",
  facebook: "bg-blue-100 text-blue-700",
  instagram: "bg-pink-100 text-pink-700",
  linkedin: "bg-blue-100 text-blue-800",
  tiktok: "bg-gray-900 text-white",
};

const PLATFORM_LABELS: Record<Platform, string> = {
  twitter: "X",
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
};

export function PlatformBadge({ platform }: { platform: Platform }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        PLATFORM_COLORS[platform]
      )}
    >
      {PLATFORM_LABELS[platform]}
    </span>
  );
}
