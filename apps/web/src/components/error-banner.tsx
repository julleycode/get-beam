"use client";

import { Button } from "@/components/ui/button";

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
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
      <span>{message}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}
