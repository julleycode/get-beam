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
  /**
   * OPTIONAL BY DESIGN: `country` mode omits coordinates entirely rather than
   * sending them and trusting the client to hide them (D8). A required
   * declaration here would be a lie the compiler propagates.
   */
  lat?: number;
  lng?: number;
  accuracy_km?: number;
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

/**
 * What the server decided this reveal may claim. Authoritative — the client's
 * only permitted degrade is a tile failure.
 *
 * - `map`      city + pin. Only when the cross-check agrees, the network is
 *              user-owned, and it is not a phone connection.
 * - `country`  country card, no coordinates. The server already omitted them.
 * - `none`     no location claim at all.
 */
export type DisplayMode = "map" | "country" | "none";

export interface CanaryResponse {
  landed: boolean;
  pages: CanaryPage[];
  geo: CanaryGeo | null;
  network: CanaryNetwork | null;
  reason?: string | null;
  /** Absent when talking to a server older than the display policy. */
  display_mode?: DisplayMode;
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
 * COPY SYNC FENCE — every string below is mirrored VERBATIM in
 * apps/web/public/beam/onboarding-steps.js, which is plain JS served from
 * /public and cannot import from src/. Change one, change both. No automated
 * gate scans the funnel copy; this comment plus review at exit is the guard.
 */
export const COUNTRY_NOTE_UNCERTAIN =
  "your internet provider only tells me the country, not the city — so that's all i'll claim.";
export const COUNTRY_NOTE_MOBILE =
  "you're on a phone connection — those move around, so i'll only claim the country.";
export const COUNTRY_NOTE_VPN =
  "you're browsing through something that hides your location — this is where it says it is, probably not where you are.";
export const NO_CLAIM_NOTE =
  "i couldn't read anything from your connection this time. it happens.";

const REGION_NAMES =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null;

/**
 * `"🇻🇳 Vietnam"`. Falls back to the bare code rather than inventing a name.
 * No dependency: the flag is derived arithmetically from the two letters.
 */
export function formatCountryName(countryCode: string | null | undefined): string {
  const cc = (countryCode || "").trim().toUpperCase();
  if (cc.length !== 2 || !/^[A-Z]{2}$/.test(cc)) return "";
  const flag = String.fromCodePoint(
    0x1f1e6 + cc.charCodeAt(0) - 65,
    0x1f1e6 + cc.charCodeAt(1) - 65,
  );
  let name = cc;
  try {
    name = REGION_NAMES?.of(cc) || cc;
  } catch {
    name = cc;
  }
  return `${flag} ${name}`;
}

/**
 * The one line under the country card.
 *
 * SELECTION IS MODE-DERIVED, NOT MOBILE-DERIVED. `mobile` is never sent to the
 * client, so it must not appear in any condition here. The only connections
 * that reach a country card at `high` confidence are mobile downgrades and
 * relay/datacenter — and those two are separable by `network.kind`. A low- or
 * unverified-confidence mobile connection is indistinguishable from any other
 * uncertain one and correctly gets the uncertain line.
 */
export function formatCountryCardNote(response: CanaryResponse): string {
  const kind = (response.network?.kind || "").toLowerCase();
  if (kind === "relay" || kind === "datacenter" || kind === "cdn") {
    return COUNTRY_NOTE_VPN;
  }
  if (response.geo?.confidence === "high") return COUNTRY_NOTE_MOBILE;
  return COUNTRY_NOTE_UNCERTAIN;
}

/** `"/pricing · 42s"`. Seconds omitted when unknown or zero. */
export function formatPageLine(page: CanaryPage): string {
  const path = (page.path || "/").trim() || "/";
  const seconds = page.seconds ?? 0;
  return seconds > 0 ? `${path} · ${Math.round(seconds)}s` : path;
}
