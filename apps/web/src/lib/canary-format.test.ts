import { describe, it, expect } from "vitest";
import {
  formatConfidenceNote,
  formatPlace,
  formatNetwork,
  formatPageLine,
  isUserOwnedNetwork,
  type CanaryGeo,
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

describe("formatConfidenceNote", () => {
  it("says nothing when the providers agreed", () => {
    expect(formatConfidenceNote(geo({ confidence: "high" }))).toBe("");
  });

  it("says nothing when there was no second opinion", () => {
    // `unverified` is today's single-provider behaviour, not a known failure —
    // captioning it would apologise on every request in an env without ipinfo.
    expect(formatConfidenceNote(geo({ confidence: "unverified" }))).toBe("");
  });

  it("says nothing for a payload written before the cross-check shipped", () => {
    expect(formatConfidenceNote(geo())).toBe("");
    expect(formatConfidenceNote(null)).toBe("");
    expect(formatConfidenceNote(undefined)).toBe("");
  });

  it("reports the measured disagreement on a low-confidence pin", () => {
    const note = formatConfidenceNote(
      geo({ confidence: "low", city: "", region: "", disagree_km: 93 }),
    );
    expect(note).toContain("93km");
    expect(note).toContain("region, not a pin");
  });

  it("still explains itself when the distance is missing", () => {
    const note = formatConfidenceNote(geo({ confidence: "low", city: "" }));
    expect(note).toContain("disagree");
    expect(note).not.toContain("0km");
  });

  it("never names the rejected cities", () => {
    // Offering "Hanoi or Haiphong?" invites the user to pick and re-lands us
    // on the coin flip the cross-check exists to remove.
    const note = formatConfidenceNote(
      geo({ confidence: "low", city: "", region: "", disagree_km: 1150 }),
    );
    expect(note).not.toMatch(/hanoi|haiphong/i);
  });
});

describe("formatPlace under a low-confidence cross-check", () => {
  it("degrades to the country when the server stripped city and region", () => {
    expect(
      formatPlace(geo({ confidence: "low", city: "", region: "" })),
    ).toBe("VN");
  });
});
