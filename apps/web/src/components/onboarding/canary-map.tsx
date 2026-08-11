"use client";

import { useEffect, useRef } from "react";
import type { Map as LeafletMap } from "leaflet";
import type { CanaryGeo } from "@/lib/canary-format";

// Leaflet's own stylesheet. Imported at module scope on purpose: this file is
// only ever reached through next/dynamic(..., { ssr: false }), so the CSS lands
// in the onboarding route chunk rather than the shared bundle.
import "leaflet/dist/leaflet.css";

/**
 * Single source of truth for the tile host, so swapping to a keyed provider is
 * a one-line change.
 *
 * ATTRIBUTION IS MANDATORY under the OSM Tile Usage Policy — do not CSS-hide
 * the control, and do not proxy these tiles through our own API (that would put
 * Beam in the tile-serving business and likely violates OSM's bulk/proxy rules).
 *
 * CSP NOTE: `apps/web` currently ships no Content-Security-Policy (verified:
 * next.config.mjs headers() only sets Cache-Control/Vary, there is no
 * middleware CSP, and public/beam/index.html has no CSP <meta>). If one is ever
 * added, this host must be allowed in `img-src` or the map goes grey.
 */
export const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
export const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/**
 * NEVER go past 13. An IP pin is city-level at best and frequently lands on the
 * ISP's registered centroid; zooming to street level makes a precision claim
 * the data cannot support and turns a "wow" into "your product is wrong".
 */
export const MAP_MIN_ZOOM = 9;
export const MAP_MAX_ZOOM = 13;
export const MAP_ZOOM = 11;

/** ≥4 tile errors this fast, or no successful tile at all, means blocked. */
const TILE_ERROR_THRESHOLD = 4;
const TILE_ERROR_WINDOW_MS = 2500;
const TILE_LOAD_DEADLINE_MS = 4000;

export interface CanaryMapProps {
  geo: CanaryGeo;
  /**
   * Fired when the tile host is unreachable (corporate firewall, uBlock — the
   * most likely visible field failure). The parent swaps to the text reveal: a
   * grey box with a floating pin is worse than no map at all.
   */
  onTileFailure?: () => void;
  onTileOk?: () => void;
}

export default function CanaryMap({ geo, onTileFailure, onTileOk }: CanaryMapProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  // Callbacks in refs so a re-rendered parent never re-initialises the map.
  const failRef = useRef(onTileFailure);
  const okRef = useRef(onTileOk);
  failRef.current = onTileFailure;
  okRef.current = onTileOk;

  useEffect(() => {
    let cancelled = false;
    let deadline: ReturnType<typeof setTimeout> | undefined;

    (async () => {
      // SSR guard #2. The parent's next/dynamic({ ssr: false }) is guard #1;
      // this one keeps `leaflet` (which touches `window` at import time) out of
      // any server or module-scope evaluation even if the dynamic wrapper is
      // ever removed.
      const L = (await import("leaflet")).default;
      if (cancelled || !hostRef.current || mapRef.current) return;

      const map = L.map(hostRef.current, {
        center: [geo.lat, geo.lng],
        zoom: MAP_ZOOM,
        minZoom: MAP_MIN_ZOOM,
        maxZoom: MAP_MAX_ZOOM,
        // Panning is welcome; wheel-zoom is not — the map sits inside a
        // scrolling chat transcript and would hijack the scroll.
        scrollWheelZoom: false,
        dragging: true,
        zoomControl: false,
        attributionControl: true,
        keyboard: false,
      });
      mapRef.current = map;

      const startedAt = Date.now();
      let errors = 0;
      let loadedAny = false;

      const fail = () => {
        if (cancelled || loadedAny) return;
        // Destroy rather than leave a grey canvas behind the pin.
        try {
          map.remove();
        } catch {
          /* already gone */
        }
        mapRef.current = null;
        failRef.current?.();
      };

      const tiles = L.tileLayer(TILE_URL, {
        attribution: TILE_ATTRIBUTION,
        maxZoom: MAP_MAX_ZOOM,
        minZoom: MAP_MIN_ZOOM,
      });

      tiles.on("tileerror", () => {
        errors += 1;
        if (
          errors >= TILE_ERROR_THRESHOLD &&
          Date.now() - startedAt <= TILE_ERROR_WINDOW_MS
        ) {
          fail();
        }
      });
      tiles.on("load", () => {
        if (loadedAny) return;
        loadedAny = true;
        okRef.current?.();
      });
      tiles.addTo(map);

      // Belt and braces: a host that black-holes the request (DNS sinkhole)
      // never fires `tileerror` at all, so a plain deadline is required.
      deadline = setTimeout(() => {
        if (!loadedAny) fail();
      }, TILE_LOAD_DEADLINE_MS);

      // The honest radius. IP geo is city-level, so the circle is doing real
      // work here — it is the visual half of the honesty caption.
      L.circle([geo.lat, geo.lng], {
        radius: Math.max(1, geo.accuracy_km || 25) * 1000,
        color: "#FF3366",
        weight: 1,
        opacity: 0.45,
        fillColor: "#FF3366",
        fillOpacity: 0.1,
        interactive: false,
      }).addTo(map);

      // L.divIcon, NOT L.marker's default icon: Leaflet resolves that PNG
      // relative to the stylesheet and it 404s under bundlers (the classic
      // broken-marker bug). A CSS dot is both the fix and the intended look —
      // it reuses the radar's obRing pulse.
      L.marker([geo.lat, geo.lng], {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({
          className: "ob-map-pin-wrap",
          html: '<span class="ob-map-pin"></span>',
          iconSize: [12, 12],
          iconAnchor: [6, 6],
        }),
      }).addTo(map);
    })().catch(() => {
      // Leaflet chunk failed to load at all — same UX as blocked tiles.
      if (!cancelled) failRef.current?.();
    });

    return () => {
      cancelled = true;
      if (deadline) clearTimeout(deadline);
      if (mapRef.current) {
        try {
          mapRef.current.remove();
        } catch {
          /* already removed by fail() */
        }
        mapRef.current = null;
      }
    };
    // Re-init only when the coordinates actually change.
  }, [geo.lat, geo.lng, geo.accuracy_km]);

  return (
    <div
      className="ob-map"
      ref={hostRef}
      data-testid="canary-map"
      role="img"
      aria-label="Approximate location on a map"
    />
  );
}
