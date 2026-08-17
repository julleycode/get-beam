import { describe, it, expect } from "vitest";
import * as canaryFormat from "@/lib/canary-format";
import {
  COUNTRY_NOTE_MOBILE,
  COUNTRY_NOTE_UNCERTAIN,
  COUNTRY_NOTE_VPN,
  formatCountryCardNote,
  formatCountryName,
  formatPlace,
  formatNetwork,
  formatPageLine,
  isUserOwnedNetwork,
  type CanaryGeo,
  type CanaryResponse,
} from "@/lib/canary-format";

const geo = (over: Partial<CanaryGeo> = {}): CanaryGeo => ({
  lat: 21.03,
  lng: 105.85,
  accuracy_km: 25,
  city: "Hanoi",
  region: "Hanoi",
  country_code: "VN",
  ...over,
});

describe("formatPlace", () => {
  it("collapses a duplicate city/region instead of printing 'Hanoi, Hanoi'", () => {
    expect(formatPlace(geo())).toBe("Hanoi · VN");
  });

  it("prints city, region · CC when they differ", () => {
    expect(formatPlace(geo({ city: "Oakland", region: "California", country_code: "us" })))
      .toBe("Oakland, California · US");
  });

  it("degrades through every missing field", () => {
    expect(formatPlace(geo({ city: "" }))).toBe("Hanoi · VN");
    expect(formatPlace(geo({ city: "", region: "" }))).toBe("VN");
    expect(formatPlace(geo({ city: "", region: "", country_code: "" }))).toBe("");
    expect(formatPlace(null)).toBe("");
    expect(formatPlace(undefined)).toBe("");
  });
});

/**
 * THE FABRICATION GUARD.
 *
 * A datacenter / CDN / privacy-relay org owns the exit address; it is not the
 * user's employer and not their ISP. Attributing it to them is the single most
 * damaging thing this reveal can do — it turns a wow into "your product is
 * lying to me". Same rule the backend enforces in
 * apps/api/services/identity_providers/ipinfo.py:78-84.
 */
describe("formatNetwork — never attributes a hosting org to the user", () => {
  const HOSTING = [
    { label: "DigitalOcean, LLC", kind: "datacenter" },
    { label: "Amazon Technologies Inc.", kind: "datacenter" },
    { label: "Cloudflare, Inc.", kind: "cdn" },
    { label: "iCloud Private Relay", kind: "relay" },
    { label: "NordVPN", kind: "vpn" },
    { label: "Hetzner Online GmbH", kind: "hosting" },
  ];

  it.each(HOSTING)("$kind ($label) is never called the user's company", (n) => {
    const out = formatNetwork(n);
    expect(out).not.toBeNull();
    const desc = out!.description.toLowerCase();
    expect(desc).not.toContain("your company");
    expect(desc).not.toContain("your isp");
    expect(desc).not.toContain("'s network");
    expect(out!.attributableToUser).toBe(false);
  });

  it.each(HOSTING)("$kind is flagged as not-user-owned", (n) => {
    expect(isUserOwnedNetwork(n.kind)).toBe(false);
  });

  it("a relay says the pin is the relay's exit, not the user", () => {
    expect(formatNetwork({ label: "iCloud Private Relay", kind: "relay" })!.description)
      .toBe("you're behind a privacy relay — this pin is the relay's exit, not you.");
  });

  it("a datacenter says the VPN line", () => {
    expect(formatNetwork({ label: "DigitalOcean, LLC", kind: "datacenter" })!.description)
      .toBe("you're on a VPN — here's where it thinks you are.");
  });

  it("an unknown kind prints the bare label with no ownership claim", () => {
    const out = formatNetwork({ label: "Some Org", kind: "wat" })!;
    expect(out.description).toBe("Some Org");
    expect(out.attributableToUser).toBe(false);
  });
});

describe("formatNetwork — the attributable cases", () => {
  it("company gets the strongest line", () => {
    const out = formatNetwork({ label: "Acme Corp", kind: "company" })!;
    expect(out.description).toBe("looks like you're on Acme Corp's network");
    expect(out.attributableToUser).toBe(true);
  });

  it("isp gets the carrier line", () => {
    const out = formatNetwork({ label: "Viettel Group", kind: "isp" })!;
    expect(out.description).toBe("Viettel Group · your ISP");
    expect(out.attributableToUser).toBe(true);
  });

  it("eyeball is treated as an isp", () => {
    expect(formatNetwork({ label: "Comcast", kind: "eyeball" })!.description)
      .toBe("Comcast · your ISP");
  });
});

describe("formatNetwork — omission beats 'Unknown ISP'", () => {
  it("returns null when there is no label", () => {
    expect(formatNetwork(null)).toBeNull();
    expect(formatNetwork(undefined)).toBeNull();
    expect(formatNetwork({ label: "", kind: "isp" })).toBeNull();
    expect(formatNetwork({ label: "   ", kind: "company" })).toBeNull();
  });
});

describe("formatPageLine", () => {
  it("prints path and seconds", () => {
    expect(formatPageLine({ path: "/pricing", seconds: 42 })).toBe("/pricing · 42s");
  });

  it("rounds fractional seconds", () => {
    expect(formatPageLine({ path: "/", seconds: 3.6 })).toBe("/ · 4s");
  });

  it("omits seconds when unknown or zero", () => {
    expect(formatPageLine({ path: "/blog", seconds: 0 })).toBe("/blog");
    expect(formatPageLine({ path: "/blog" })).toBe("/blog");
    expect(formatPageLine({ path: "/blog", seconds: null })).toBe("/blog");
  });

  it("falls back to / for an empty path", () => {
    expect(formatPageLine({ path: "" })).toBe("/");
  });
});

describe("formatPlace under a low-confidence cross-check", () => {
  it("degrades to the country when the server stripped city and region", () => {
    expect(
      formatPlace(geo({ confidence: "low", city: "", region: "" })),
    ).toBe("VN");
  });
});

describe("formatCountryName", () => {
  it("renders a flag and a country name", () => {
    const out = formatCountryName("VN");
    expect(out).toContain("🇻🇳");
    expect(out.toLowerCase()).toContain("viet");
  });

  it("is case and whitespace tolerant", () => {
    expect(formatCountryName(" vn ")).toBe(formatCountryName("VN"));
  });

  it("returns nothing rather than inventing a name", () => {
    expect(formatCountryName("")).toBe("");
    expect(formatCountryName(null)).toBe("");
    expect(formatCountryName("XYZ")).toBe("");
    expect(formatCountryName("1A")).toBe("");
  });
});

describe("formatCountryCardNote — selection is mode-derived, not mobile-derived", () => {
  const resp = (
    kind: string | null,
    confidence: CanaryGeo["confidence"],
  ): CanaryResponse => ({
    landed: true,
    pages: [],
    geo: { city: "", region: "", country_code: "VN", confidence },
    network: kind ? { label: "Some Net", kind } : null,
    display_mode: "country",
  });

  it.each(["relay", "datacenter", "cdn"])("uses the vpn line for %s", (kind) => {
    expect(formatCountryCardNote(resp(kind, "high"))).toBe(COUNTRY_NOTE_VPN);
  });

  it("vpn line wins even at low confidence", () => {
    expect(formatCountryCardNote(resp("relay", "low"))).toBe(COUNTRY_NOTE_VPN);
  });

  it("high confidence on a user-owned network can only be a mobile downgrade", () => {
    expect(formatCountryCardNote(resp("isp", "high"))).toBe(COUNTRY_NOTE_MOBILE);
  });

  it.each(["low", "unverified"] as const)(
    "%s confidence gets the uncertain line, mobile or not",
    (confidence) => {
      expect(formatCountryCardNote(resp("isp", confidence))).toBe(
        COUNTRY_NOTE_UNCERTAIN,
      );
    },
  );

  it("an absent network label falls through to the confidence test", () => {
    expect(formatCountryCardNote(resp(null, "high"))).toBe(COUNTRY_NOTE_MOBILE);
    expect(formatCountryCardNote(resp(null, "low"))).toBe(COUNTRY_NOTE_UNCERTAIN);
  });
});

describe("D6 copy register — no tech jargon in any user-facing string", () => {
  /**
   * Scan semantics are normative, not inferred:
   *  - `IP` / `ASN`  — case-SENSITIVE whole-token. A case-insensitive scan
   *    false-positives on ordinary words ("equipment", "description").
   *  - the rest      — case-INSENSITIVE substring.
   */
  const WHOLE_TOKEN_BANNED = ["IP", "ASN"];
  const SUBSTRING_BANNED = ["geolocation", "database", "crosscheck"];

  const copyStrings = (): string[] => {
    const out: string[] = [];
    for (const value of Object.values(canaryFormat)) {
      if (typeof value === "string") out.push(value);
    }
    // Every string these functions can emit, not just the exported constants.
    for (const kind of ["relay", "cdn", "datacenter", "hosting", "vpn", "company", "isp", "eyeball", "weird"]) {
      const net = formatNetwork({ label: "Acme", kind });
      if (net) out.push(net.description);
    }
    for (const kind of ["relay", "datacenter", "isp"]) {
      for (const confidence of ["high", "low", "unverified"] as const) {
        out.push(
          formatCountryCardNote({
            landed: true,
            pages: [],
            geo: { city: "", region: "", country_code: "VN", confidence },
            network: { label: "Acme", kind },
          }),
        );
      }
    }
    return out;
  };

  it("scans a non-empty set of strings", () => {
    expect(copyStrings().length).toBeGreaterThan(5);
  });

  it.each(WHOLE_TOKEN_BANNED)("contains no bare %s token", (token) => {
    const re = new RegExp(`\\b${token.replace("&", "\\&")}\\b`);
    for (const s of copyStrings()) expect(s).not.toMatch(re);
  });

  it.each(SUBSTRING_BANNED)("contains no %s", (token) => {
    for (const s of copyStrings()) expect(s.toLowerCase()).not.toContain(token);
  });
});
