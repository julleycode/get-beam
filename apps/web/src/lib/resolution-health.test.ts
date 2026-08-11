import { describe, expect, it } from "vitest";

import {
  UNAVAILABLE_MIN_CALLS,
  providerIsUnhealthy,
  providerMessage,
  providerStatus,
  resolutionHealthSummary,
  type ProviderHealth,
} from "@/lib/resolution-health";

const mk = (
  provider: string,
  calls: number,
  unavailable: number
): ProviderHealth => ({
  provider,
  calls,
  attempts: calls - unavailable,
  successes: 0,
  unavailable,
  unavailable_rate: calls ? unavailable / calls : 0,
});

describe("providerStatus", () => {
  it("stays silent below the sample floor", () => {
    expect(providerStatus(1, 1)).toBe("insufficient_data");
    expect(providerIsUnhealthy(1, 1)).toBe(false);
  });

  it("a healthy provider renders nothing — no_match is not unavailable", () => {
    // ipinfo during the incident: 8/8 no_match, 0 unavailable. Real answers.
    expect(providerStatus(8, 0)).toBe("insufficient_data");
    expect(providerStatus(200, 0)).toBe("healthy");
    expect(providerIsUnhealthy(200, 0)).toBe(false);
    expect(resolutionHealthSummary([mk("ipinfo", 200, 0)])).toBeNull();
  });

  it("catches the measured incident on the FIRST day at or above the floor", () => {
    // 2026-08-10 was 8 calls at 100% unavailable — below the 10-call floor, so
    // that day alone stays quiet. The first tripping day is 2026-08-08 (16
    // calls) reading backwards, and 2026-08-09 (34 calls) trips too. Real
    // detection is therefore ~1 day, versus the 4 days of silence it replaces.
    expect(providerStatus(8, 1)).toBe("insufficient_data");
    expect(providerStatus(16, 1)).toBe("dead");
    expect(providerStatus(34, 1)).toBe("dead");
  });

  it("flags degraded between the two bands", () => {
    expect(providerStatus(20, 0.5)).toBe("degraded");
    expect(providerStatus(20, 0.99)).toBe("degraded");
    expect(providerStatus(20, 0.49)).toBe("healthy");
  });

  it("boundary: exactly at the sample floor is evaluated, not skipped", () => {
    expect(providerStatus(UNAVAILABLE_MIN_CALLS, 1)).toBe("dead");
    expect(providerStatus(UNAVAILABLE_MIN_CALLS - 1, 1)).toBe(
      "insufficient_data"
    );
  });

  it("zero calls never produces NaN", () => {
    expect(providerStatus(0, 0)).toBe("insufficient_data");
    expect(providerIsUnhealthy(0, 0)).toBe(false);
  });
});

describe("resolutionHealthSummary", () => {
  it("names both dead providers from the real incident", () => {
    const out = resolutionHealthSummary([
      mk("rb2b", 34, 34),
      mk("pdl_ip_enrich", 34, 34),
      mk("ipinfo", 34, 0),
    ]);
    expect(out).toContain("2 identity providers down");
    expect(out).toContain("rb2b");
    expect(out).toContain("pdl_ip_enrich");
    expect(out).not.toContain("ipinfo");
  });

  it("singular wording for one provider", () => {
    expect(resolutionHealthSummary([mk("rb2b", 34, 34)])).toBe(
      "Identity provider down: rb2b"
    );
  });

  it("returns null when there is nothing to report", () => {
    expect(resolutionHealthSummary([])).toBeNull();
  });
});

describe("providerMessage", () => {
  it("renders a whole-percent figure and never a raw float", () => {
    const m = providerMessage(mk("rb2b", 30, 20));
    expect(m).toContain("67%");
    expect(m).not.toContain("0.6666");
  });

  it("distinguishes total death from partial degradation", () => {
    expect(providerMessage(mk("rb2b", 34, 34))).toContain("none of its 34");
    expect(providerMessage(mk("rb2b", 34, 20))).toContain("59%");
  });
});
