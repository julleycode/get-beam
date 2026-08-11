import { describe, it, expect } from "vitest";
import { chooseRevealMode } from "@/lib/canary-reveal-mode";
import type { CanaryResponse } from "@/lib/canary-format";

const res = (over: Partial<CanaryResponse> = {}): CanaryResponse => ({
  landed: true,
  pages: [{ path: "/pricing", seconds: 42 }],
  geo: {
    lat: 21.03,
    lng: 105.85,
    accuracy_km: 25,
    city: "Hanoi",
    region: "Hanoi",
    country_code: "VN",
  },
  network: { label: "Viettel Group", kind: "isp" },
  ...over,
});

describe("chooseRevealMode — the degraded-path matrix", () => {
  it("visit landed + geo present → map", () => {
    expect(chooseRevealMode(res())).toBe("map");
  });

  it("visit landed + geo missing → text (page list only)", () => {
    expect(chooseRevealMode(res({ geo: null }))).toBe("text");
  });

  it("visit never landed but geo present → still map (never gate the map on the visit)", () => {
    // This is the VPN / adblocker / DNT cohort. Gating the map on the visit
    // would give this entire group nothing.
    expect(chooseRevealMode(res({ landed: false, pages: [] }))).toBe("map");
  });

  it("nothing at all → skip", () => {
    expect(
      chooseRevealMode(res({ landed: false, pages: [], geo: null, network: null })),
    ).toBe("skip");
  });

  it("provider unavailable with no geo and no pages → skip", () => {
    expect(
      chooseRevealMode(
        res({
          landed: false,
          pages: [],
          geo: null,
          network: null,
          reason: "provider_unavailable",
        }),
      ),
    ).toBe("skip");
  });

  it("network only (no geo, no pages) → text, not skip", () => {
    expect(chooseRevealMode(res({ landed: false, pages: [], geo: null }))).toBe("text");
  });

  it("null response → skip", () => {
    expect(chooseRevealMode(null)).toBe("skip");
    expect(chooseRevealMode(undefined)).toBe("skip");
  });
});

describe("chooseRevealMode — Null Island guard", () => {
  it("never renders a map at 0,0", () => {
    const nullIsland = res({ geo: { ...res().geo!, lat: 0, lng: 0 } });
    expect(chooseRevealMode(nullIsland)).toBe("text");
  });

  it("0 on only one axis is a real coordinate", () => {
    const equator = res({ geo: { ...res().geo!, lat: 0, lng: 105.85 } });
    expect(chooseRevealMode(equator)).toBe("map");
  });

  it("rejects NaN / Infinity coordinates", () => {
    expect(chooseRevealMode(res({ geo: { ...res().geo!, lat: NaN } }))).toBe("text");
    expect(chooseRevealMode(res({ geo: { ...res().geo!, lng: Infinity } }))).toBe("text");
  });
});

describe("chooseRevealMode — tile failure downgrade", () => {
  it("falls back to text when tiles are blocked", () => {
    // A grey box with a floating pin is worse than no map. Corporate firewall
    // / uBlock is the most likely visible field failure.
    expect(chooseRevealMode(res(), "failed")).toBe("text");
  });

  it("keeps the map while tiles are pending or loaded", () => {
    expect(chooseRevealMode(res(), "pending")).toBe("map");
    expect(chooseRevealMode(res(), "ok")).toBe("map");
  });

  it("a tile failure with nothing else to show still skips", () => {
    expect(
      chooseRevealMode(res({ landed: false, pages: [], geo: null, network: null }), "failed"),
    ).toBe("skip");
  });
});
