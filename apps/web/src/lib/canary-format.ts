/**
 * Rendering decisions for the location reveal — pure, so the honesty rules are
 * unit-testable without a DOM.
 *
 * THE FABRICATION GUARD: a datacenter / CDN / privacy-relay org must NEVER be
 * attributed to the user as "your company" or "your ISP". It is a hosting
 * provider that happens to own the exit address. This mirrors the backend's
 * own guard at apps/api/services/identity_providers/ipinfo.py:78-84 — the same
 * class of claim, enforced on both sides of the wire.
 */

/**
 * How much of a claim the pin is allowed to make. Set server-side by
 * `build_geo` from a second-provider cross-check.
 *
 * - `high`        two independent geo providers agree on where this IP is.
 * - `unverified`  no second opinion was obtainable (provider down, flag off).
 *                 The single-provider behaviour that shipped first. NOT a
 *                 downgrade of `high` and NOT an upgrade of `low`.
 * - `low`         the providers disagree. THE SERVER ALREADY SENT `city` AND
 *                 `region` AS EMPTY STRINGS — there is no hidden name to
 *                 reveal, so no client can leak one by forgetting to check.
 */
export type GeoConfidence = "high" | "unverified" | "low";

/** Mirrors `build_geo` in apps/api/services/onboarding_canary.py. */
export interface CanaryGeo {
  lat: number;
  lng: number;
  accuracy_km: number;
  city: string;
  region: string;
  country_code: string;
  /** Absent on payloads written before the cross-check shipped. */
  confidence?: GeoConfidence;
  /** Km between the two providers' answers. Only present when `low`. */
  disagree_km?: number;
}

/**
 * Mirrors `build_network`. `kind` comes from `classify_org_kind` after the
 * relay/company narrowing, so the practical set is
 * company | isp | relay | datacenter, but unknown strings must degrade safely.
 */
export interface CanaryNetwork {
  label: string;
  kind: string;
}

export interface CanaryPage {
  path: string;
  title?: string | null;
  seconds?: number | null;
  at?: string | null;
}

export interface CanaryResponse {
  landed: boolean;
  pages: CanaryPage[];
  geo: CanaryGeo | null;
  network: CanaryNetwork | null;
  reason?: string | null;
}

/** Kinds we must never describe as belonging to the user. */
const NOT_THE_USER = new Set(["relay", "datacenter", "cdn", "hosting", "vpn"]);

export function isUserOwnedNetwork(kind: string): boolean {
  return !NOT_THE_USER.has((kind || "").toLowerCase());
}

/**
 * `"Hanoi, Hanoi · VN"`, degrading through every missing field.
 * Returns "" when there is nothing honest to print.
 */
export function formatPlace(geo: CanaryGeo | null | undefined): string {
  if (!geo) return "";
  const city = (geo.city || "").trim();
  const region = (geo.region || "").trim();
  const cc = (geo.country_code || "").trim().toUpperCase();

  const place: string[] = [];
  if (city) place.push(city);
  // Don't print "Hanoi, Hanoi" when the city IS the region.
  if (region && region.toLowerCase() !== city.toLowerCase()) place.push(region);

  const left = place.join(", ");
  if (left && cc) return `${left} · ${cc}`;
  return left || cc;
}

export interface FormattedNetwork {
  /** The org string, safe to print verbatim. */
  label: string;
  /** One human sentence. Never claims a hosting org is the user's. */
  description: string;
  /** False for relay/datacenter/cdn — the caller must not say "you work at". */
  attributableToUser: boolean;
}

/**
 * Turn the network payload into copy.
 *
 * Returns `null` when there is no label — omit the line entirely rather than
 * rendering "Unknown ISP" (same rule the backend applies at rung 5).
 */
export function formatNetwork(
  network: CanaryNetwork | null | undefined,
): FormattedNetwork | null {
  if (!network) return null;
  const label = (network.label || "").trim();
  if (!label) return null;
  const kind = (network.kind || "").toLowerCase();

  switch (kind) {
    case "relay":
    case "cdn":
      return {
        label,
        description:
          "you're behind a privacy relay — this pin is the relay's exit, not you.",
        attributableToUser: false,
      };
    case "datacenter":
    case "hosting":
    case "vpn":
      return {
        label,
        description: "you're on a VPN — here's where it thinks you are.",
        attributableToUser: false,
      };
    case "company":
      return {
        label,
        description: `looks like you're on ${label}'s network`,
        attributableToUser: true,
      };
    case "isp":
    case "eyeball":
      return {
        label,
        description: `${label} · your ISP`,
        attributableToUser: true,
      };
    default:
      // Unknown classification: print the label with no ownership claim.
      return { label, description: label, attributableToUser: false };
  }
}

/**
 * The one line that keeps a disagreed pin honest, or "" when none is needed.
 *
 * WHY IT IS NOT OPTIONAL COPY: with the city stripped, a bare pin plus a large
 * circle reads as "we didn't bother" rather than "we checked twice and the
 * sources conflict". The measured disagreement is the whole credibility of the
 * moment — a reveal that admits its own error bar survives being wrong; one
 * that states Hanoi to a reader sitting in Ho Chi Minh City does not.
 *
 * Deliberately does NOT name the rejected cities. Printing "Hanoi or Haiphong?"
 * invites the user to pick one and re-lands us on a coin flip.
 */
export function formatConfidenceNote(geo: CanaryGeo | null | undefined): string {
  if (!geo || geo.confidence !== "low") return "";
  const km = Math.round(geo.disagree_km ?? 0);
  if (km > 0) {
    return `two IP databases put you ${km}km apart, so this is a region, not a pin.`;
  }
  return "the IP databases disagree about your city, so this is a region, not a pin.";
}

/** `"/pricing · 42s"`. Seconds omitted when unknown or zero. */
export function formatPageLine(page: CanaryPage): string {
  const path = (page.path || "/").trim() || "/";
  const seconds = page.seconds ?? 0;
  return seconds > 0 ? `${path} · ${Math.round(seconds)}s` : path;
}
