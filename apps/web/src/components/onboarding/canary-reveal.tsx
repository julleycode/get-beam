"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import {
  formatNetwork,
  formatPageLine,
  formatPlace,
  type CanaryResponse,
} from "@/lib/canary-format";
import { chooseRevealMode, type TileState } from "@/lib/canary-reveal-mode";
import { ChatControls, ObButton } from "@/components/onboarding/chat-controls";

/**
 * SSR guard #1 (guard #2 is the `await import("leaflet")` inside the map's own
 * useEffect). Leaflet touches `window` at import time, so it must never be
 * evaluated during the server render.
 */
const CanaryMap = dynamic(() => import("@/components/onboarding/canary-map"), {
  ssr: false,
  loading: () => <div className="ob-map ob-skel" aria-hidden="true" />,
});

/**
 * THE HONESTY CAPTION — load-bearing, not polish.
 *
 * An IP pin is city-level at best and often lands on the ISP's registered
 * centroid (on mobile CGNAT, a different city entirely). Without this line a
 * 30km-off pin reads as "your product is broken", which is the #1 failure mode
 * of a location reveal. The accuracy circle is its visual half.
 */
export const HONESTY_CAPTION =
  "that's an IP-level estimate — usually the right city, sometimes the wrong suburb.";

export function CanaryReveal({
  response,
  onConfirm,
}: {
  response: CanaryResponse;
  onConfirm: () => void;
}) {
  const [tileState, setTileState] = useState<TileState>("pending");

  const mode = chooseRevealMode(response, tileState);
  const place = formatPlace(response.geo);
  const network = useMemo(() => formatNetwork(response.network), [response.network]);
  const pages = response.pages ?? [];

  return (
    <ChatControls wide>
      <div className="ob-card" data-testid="canary-reveal">
        {mode === "map" && response.geo && (
          <CanaryMap
            geo={response.geo}
            onTileOk={() => setTileState("ok")}
            onTileFailure={() => setTileState("failed")}
          />
        )}

        <div className="ob-meta">
          {place && (
            <div className="mrow" data-testid="canary-place">
              <span className="ic" aria-hidden="true">
                ◎
              </span>
              <span>{place}</span>
            </div>
          )}

          {/* Omitted entirely when every rung of the backend ladder was empty —
              a blank line beats "Unknown ISP" in a moment whose job is to look
              omniscient. `formatNetwork` also refuses to attribute a
              datacenter/relay org to the user. */}
          {network && (
            <div className="mrow" data-testid="canary-network">
              <span className="ic" aria-hidden="true">
                ⌁
              </span>
              <span>{network.description}</span>
            </div>
          )}

          {pages.length > 0 && (
            <div className="mrow" data-testid="canary-pages">
              <span className="ic" aria-hidden="true">
                ↗
              </span>
              <span className="ob-path">
                {pages.map((p, i) => (
                  <span key={`${p.path}-${i}`}>
                    {i > 0 && <span className="arr"> → </span>}
                    <code>{formatPageLine(p)}</code>
                  </span>
                ))}
              </span>
            </div>
          )}
        </div>

        {mode === "map" && <p className="ob-map-note">{HONESTY_CAPTION}</p>}
        {mode === "text" && response.geo && (
          <p className="ob-map-note">
            {HONESTY_CAPTION} (couldn&apos;t load the map here — something is
            blocking the tiles.)
          </p>
        )}
      </div>

      <ObButton variant="primary" onClick={onConfirm}>
        ok, what now? <span aria-hidden="true">→</span>
      </ObButton>
    </ChatControls>
  );
}
