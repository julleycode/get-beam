/**
 * Which reveal to render: the Leaflet map, the text-only card, or nothing.
 *
 * Pure so the degraded matrix in the plan is a unit test rather than something
 * you can only observe by breaking a firewall.
 */

import type { CanaryResponse } from "@/lib/canary-format";

export type RevealMode = "map" | "text" | "skip";

/**
 * Tile loading state, owned by the map component.
 * - `pending` — map not mounted yet / still loading, assume it will work
 * - `ok`      — at least one tile loaded
 * - `failed`  — >=4 `tileerror`s within 2.5s, or no `load` within 4s
 *               (corporate firewall / uBlock). A grey box with a floating pin
 *               is worse than no map, so this downgrades to text.
 */
export type TileState = "pending" | "ok" | "failed";

/** Null Island: lat==lng==0 is the classic "provider returned nothing" pin. */
function hasUsableGeo(response: CanaryResponse): boolean {
  const geo = response.geo;
  if (!geo) return false;
  if (typeof geo.lat !== "number" || typeof geo.lng !== "number") return false;
  if (!Number.isFinite(geo.lat) || !Number.isFinite(geo.lng)) return false;
  if (geo.lat === 0 && geo.lng === 0) return false;
  return true;
}

export function chooseRevealMode(
  response: CanaryResponse | null | undefined,
  tileState: TileState = "pending",
): RevealMode {
  if (!response) return "skip";

  const geoOk = hasUsableGeo(response);
  const hasPages = Array.isArray(response.pages) && response.pages.length > 0;
  const hasNetwork = !!(response.network && response.network.label);

  // Nothing to show at all — one honest line and straight on to site setup.
  if (!geoOk && !hasPages && !hasNetwork) return "skip";

  if (geoOk && tileState !== "failed") return "map";

  // Geo present but tiles are blocked, or no coordinates but we still have the
  // journey / network. A partial reveal is still decent.
  return "text";
}
