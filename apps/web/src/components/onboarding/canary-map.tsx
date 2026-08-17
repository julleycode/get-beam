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
 *
 * Zooming OUT only ever shows less certainty, so the floor is loose enough to
 * reach country level.
 */
export const MAP_MIN_ZOOM = 3;
export const MAP_MAX_ZOOM = 13;
export const MAP_ZOOM = 11;

/**
 * Above this radius the fixed MAP_ZOOM of 11 no longer contains the accuracy
 * circle, and the user sees a full-bleed pink wash with the pin somewhere under
 * it — which reads as a rendering bug, not as uncertainty. Past it, fit the view
 * to the circle instead so the whole error bar is visible at once.
 *
 * Only reachable via the cross-check disagreement path (`confidence: "low"`),
 * where the backend widens the radius to the measured provider disagreement.
 */
const FIT_BOUNDS_ABOVE_KM = 40;

/** ≥4 tile errors this fast, or no successful tile at all, means blocked. */
const TILE_ERROR_THRESHOLD = 4;
const TILE_ERROR_WINDOW_MS = 2500;
const TILE_LOAD_DEADLINE_MS = 4000;

/**
 * Coordinates are OPTIONAL on `CanaryGeo` because `country` mode omits them.
 * The map narrows them back to required: a payload without coordinates must not
 * be able to reach Leaflet at all. The map is only rendered in `map` mode, so
 * the narrowing is satisfiable at the call site.
 */
export type CanaryMapGeo = CanaryGeo & {
  lat: number;
  lng: number;
  accuracy_km: number;
};

export interface CanaryMapProps {
  geo: CanaryMapGeo;
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
    let wheelCleanup: (() => void) | undefined;

    (async () => {
      // SSR guard #2. The parent's next/dynamic({ ssr: false }) is guard #1;
      // this one keeps `leaflet` (which touches `window` at import time) out of
      // any server or module-scope evaluation even if the dynamic wrapper is
      // ever removed.
      const L = (await import("leaflet")).default;
      const hostEl = hostRef.current;
      if (cancelled || !hostEl || mapRef.current) return;

      const map = L.map(hostEl, {
        center: [geo.lat, geo.lng],
        zoom: MAP_ZOOM,
        minZoom: MAP_MIN_ZOOM,
        maxZoom: MAP_MAX_ZOOM,
        // Panning is welcome; plain wheel-zoom is not — the map sits inside a
        // scrolling chat transcript and would hijack the scroll. Every other
        // zoom gesture is on: the +/- control, double-click, pinch, and
        // ctrl/⌘+wheel below.
        scrollWheelZoom: false,
        dragging: true,
        doubleClickZoom: true,
        touchZoom: true,
        boxZoom: true,
        zoomControl: true,
        attributionControl: true,
        keyboard: false,
      });
      mapRef.current = map;

      // Desktop escape hatch for wheel users: hold ctrl (or ⌘) and scroll.
      const onWheel = (e: WheelEvent) => {
        if (!(e.ctrlKey || e.metaKey)) return;
        e.preventDefault();
        map.setZoom(map.getZoom() + (e.deltaY < 0 ? 1 : -1));
      };
      hostEl.addEventListener("wheel", onWheel, { passive: false });
      wheelCleanup = () => hostEl.removeEventListener("wheel", onWheel);

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
      // work here — with the caption gone it is the ONLY thing conveying that the
      // pin is an estimate. Do not drop it.
      const radiusKm = Math.max(1, geo.accuracy_km || 25);
      const circle = L.circle([geo.lat, geo.lng], {
        radius: radiusKm * 1000,
        color: "#FF3366",
        weight: 1,
        opacity: 0.45,
        fillColor: "#FF3366",
        fillOpacity: 0.1,
        interactive: false,
      }).addTo(map);

      if (radiusKm > FIT_BOUNDS_ABOVE_KM) {
        // maxZoom is belt-and-braces: fitBounds only ever zooms OUT for a circle
        // this large, but the cap keeps the "never past street level" rule true
        // no matter what radius the backend sends.
        map.fitBounds(circle.getBounds(), {
          maxZoom: MAP_MAX_ZOOM,
          padding: [12, 12],
        });
      }

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
      wheelCleanup?.();
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
      role="region"
      aria-label="Approximate location on a map"
    />
  );
}
