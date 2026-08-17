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

describe("chooseRevealMode honours the server's display_mode", () => {
  const withMode = (
    display_mode: "map" | "country" | "none",
    over: Partial<CanaryResponse> = {},
  ): CanaryResponse => ({
    landed: true,
    pages: [{ path: "/pricing" }],
    geo: { city: "Hanoi", region: "Hanoi", country_code: "VN", confidence: "high" },
    network: { label: "FPT", kind: "isp" },
    display_mode,
    ...over,
  });

  it("map mode renders the map", () => {
    expect(chooseRevealMode(withMode("map"), "ok")).toBe("map");
    expect(chooseRevealMode(withMode("map"), "pending")).toBe("map");
  });

  it("map mode degrades to text when the tiles are blocked", () => {
    expect(chooseRevealMode(withMode("map"), "failed")).toBe("text");
  });

  it("country mode ignores tile state entirely — no tiles are used", () => {
    expect(chooseRevealMode(withMode("country"), "failed")).toBe("country");
    expect(chooseRevealMode(withMode("country"), "ok")).toBe("country");
    expect(chooseRevealMode(withMode("country"), "pending")).toBe("country");
  });

  it("country mode holds even though the server sent no coordinates", () => {
    const r = withMode("country", {
      geo: { city: "", region: "", country_code: "VN", confidence: "high" },
    });
    expect(chooseRevealMode(r, "ok")).toBe("country");
  });

  it("none mode still shows the journey when there is one", () => {
    expect(chooseRevealMode(withMode("none", { geo: null }), "ok")).toBe("text");
  });

  it("none mode shows a network-only reveal", () => {
    const r = withMode("none", { geo: null, pages: [] });
    expect(chooseRevealMode(r, "ok")).toBe("text");
  });

  it("none mode with nothing at all skips", () => {
    const r = withMode("none", { geo: null, pages: [], network: null });
    expect(chooseRevealMode(r, "ok")).toBe("skip");
  });

  it("an absent display_mode falls back to the legacy geo-presence logic", () => {
    const legacy: CanaryResponse = {
      landed: true,
      pages: [{ path: "/pricing" }],
      geo: {
        lat: 21.03,
        lng: 105.85,
        accuracy_km: 25,
        city: "Hanoi",
        region: "Hanoi",
        country_code: "VN",
      },
      network: { label: "FPT", kind: "isp" },
    };
    expect(chooseRevealMode(legacy, "ok")).toBe("map");
    expect(chooseRevealMode(legacy, "failed")).toBe("text");
    expect(chooseRevealMode({ ...legacy, geo: null }, "ok")).toBe("text");
    expect(
      chooseRevealMode({ ...legacy, geo: null, pages: [], network: null }, "ok"),
    ).toBe("skip");
  });

  it("never returns country without the server asking for it", () => {
    const legacy: CanaryResponse = {
      landed: true,
      pages: [],
      geo: null,
      network: { label: "FPT", kind: "isp" },
    };
    expect(chooseRevealMode(legacy, "ok")).not.toBe("country");
  });
});
