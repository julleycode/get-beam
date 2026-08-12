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
 * The IP-level-estimate caption was removed by product decision.
 *
 * An IP pin is still city-level at best and often lands on the ISP's registered
 * centroid, so the honesty work now rests entirely on the accuracy circle drawn
 * around the pin and on MAP_MAX_ZOOM keeping the view off street level. Keep
 * both — they are what stops a 30km-off pin reading as "your product is broken".
 */
export const TILE_FAILURE_NOTE =
  "couldn't load the map here — something is blocking the tiles.";

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

        {mode === "text" && response.geo && (
          <p className="ob-map-note">{TILE_FAILURE_NOTE}</p>
        )}
      </div>

      <ObButton variant="primary" onClick={onConfirm}>
        ok, what now? <span aria-hidden="true">→</span>
      </ObButton>
    </ChatControls>
  );
}
