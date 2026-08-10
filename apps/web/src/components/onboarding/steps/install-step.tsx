"use client";

import { PixelInstallGuide } from "@/components/pixel-install-guide";
import { ChatControls } from "@/components/onboarding/chat-controls";
import { CrossTenantDisclosure } from "@/components/onboarding/cross-tenant-disclosure";

/**
 * The pixel install, inside the chat.
 *
 * Uses the REAL `<PixelInstallGuide>` — the same component the classic form
 * renders — with the real snippet from `api.getPixelSnippet`. No copy of the
 * snippet markup exists on this path, so the legacy
 * `data-site="YOUR_SITE_ID"` bug cannot come back.
 *
 * The cross-tenant disclosure renders ABOVE the guide and outside the
 * `detecting` branch, so it is visible before and during install (AC-9).
 */
export function InstallStep({
  siteId,
  siteUrl,
  snippet,
  platform,
  hasGtm,
  gtmId,
  detecting,
  onVerified,
}: {
  siteId: string;
  siteUrl: string | null;
  snippet: string;
  platform: string;
  hasGtm: boolean;
  gtmId: string | null;
  detecting: boolean;
  onVerified: () => void;
}) {
  return (
    <ChatControls wide>
      <div className="ob-bubble plain wide">
        <CrossTenantDisclosure />
        {detecting ? (
          <div className="ob-listen">
            <div className="ob-radar">
              <span className="ring" />
              <span className="ring" />
              <span className="ring" />
              <span className="core" />
            </div>
            <p className="ob-hint">
              analyzing {siteUrl ?? "your site"}…
            </p>
          </div>
        ) : (
          <PixelInstallGuide
            platform={platform}
            hasGtm={hasGtm}
            gtmId={gtmId}
            snippet={snippet}
            siteId={siteId}
            onVerified={onVerified}
          />
        )}
      </div>
    </ChatControls>
  );
}
