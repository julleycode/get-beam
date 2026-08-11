import { describe, expect, it } from "vitest";

import {
  OPTOUT_MIN_SAMPLE,
  optoutIsAbnormal,
  optoutMessage,
  optoutStatus,
} from "@/lib/privacy-optout";

describe("optoutStatus", () => {
  it("stays silent below the minimum sample — 1-of-3 is not a 33% rate", () => {
    expect(optoutStatus(3, 0.3333)).toBe("insufficient_data");
    expect(optoutIsAbnormal(3, 0.3333)).toBe(false);
  });

  it("treats the measured ~5.9% production baseline as healthy", () => {
    expect(optoutStatus(500, 0.059)).toBe("ok");
    // A healthy site renders NO warning indicator — the card's philosophy.
    expect(optoutIsAbnormal(500, 0.059)).toBe(false);
  });

  it("flags elevated and high rates", () => {
    expect(optoutStatus(500, 0.1)).toBe("elevated");
    expect(optoutStatus(500, 0.217)).toBe("elevated"); // worst observed site
    expect(optoutStatus(500, 0.25)).toBe("high");
    expect(optoutStatus(500, 0.8226)).toBe("high"); // Firefox, event-level
    expect(optoutIsAbnormal(500, 0.1)).toBe(true);
    expect(optoutIsAbnormal(500, 0.8226)).toBe(true);
  });

  it("boundary: exactly at the minimum sample is evaluated, not skipped", () => {
    expect(optoutStatus(OPTOUT_MIN_SAMPLE, 0.3)).toBe("high");
    expect(optoutStatus(OPTOUT_MIN_SAMPLE - 1, 0.3)).toBe("insufficient_data");
  });

  it("zero visitors and zero rate are healthy-silent, never NaN", () => {
    expect(optoutStatus(0, 0)).toBe("insufficient_data");
    expect(optoutIsAbnormal(0, 0)).toBe(false);
  });
});

describe("optoutMessage", () => {
  it("renders a whole-percent figure for each status", () => {
    expect(optoutMessage(500, 0.8226)).toContain("82%");
    expect(optoutMessage(500, 0.12)).toContain("12%");
    expect(optoutMessage(500, 0.05)).toContain("5%");
    expect(optoutMessage(3, 0.33)).toContain(String(OPTOUT_MIN_SAMPLE));
  });

  it("never leaks a raw float into user-facing copy", () => {
    expect(optoutMessage(500, 0.8226)).not.toContain("0.8226");
  });
});
