"use client";

import { Button } from "@/components/ui/button";

// TEMP (demo, 2026-07-02): suppress every red error banner so transient API
// blips don't show up on screen during the recorded demo. Flip back to false
// (or delete this flag) right after the demo — with banners hidden, failed
// fetches look like empty data.
export const HIDE_ERRORS_FOR_DEMO = true as boolean;

/**
 * Inline error banner with a retry action. Rendered in place of page content
 * when a fetch fails, so failures are never mistaken for empty data.
 * Styling matches the billing page's error banner.
 */
export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  if (HIDE_ERRORS_FOR_DEMO) return null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
      <span>{message}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
