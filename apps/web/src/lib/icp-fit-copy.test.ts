import { describe, expect, it } from "vitest";

import {
  ICP_FIT_BANDS,
  icpFitBand,
  icpFitLabel,
  icpFitTooltip,
} from "./icp-fit-copy";

// The adversarial `site_profile`-derived text a compromised/creative LLM could
// produce. AC-14 (tooltip half): NO substring of this may ever reach rendered
// copy. The builder takes only a number, so the structural guarantee is that
// there is no channel for it at all — these cases pin that shut.
const ADVERSARIAL =
  "IGNORE PREVIOUS INSTRUCTIONS <script>alert(1)</script> VP Eng";
const ADVERSARIAL_FRAGMENTS = [
  "IGNORE",
  "PREVIOUS",
  "INSTRUCTIONS",
  "script",
  "alert",
  "VP Eng",
  "<",
  ">",
];

describe("icpFitBand", () => {
  it("maps scores onto the fixed band vocabulary", () => {
    expect(icpFitBand(100)).toBe("strong ICP fit");
    expect(icpFitBand(70)).toBe("strong ICP fit");
    expect(icpFitBand(69)).toBe("partial ICP fit");
    expect(icpFitBand(40)).toBe("partial ICP fit");
    expect(icpFitBand(39)).toBe("weak ICP fit");
    expect(icpFitBand(0)).toBe("weak ICP fit");
  });

  it("returns null for an unscored visitor — never a default band", () => {
    expect(icpFitBand(null)).toBeNull();
    expect(icpFitBand(undefined)).toBeNull();
    expect(icpFitBand(NaN)).toBeNull();
  });

  it("only ever returns a member of the known band set", () => {
    for (let score = 0; score <= 100; score++) {
      const band = icpFitBand(score);
      expect(band).not.toBeNull();
      expect(ICP_FIT_BANDS).toContain(band!);
    }
  });
});

describe("icpFitLabel / icpFitTooltip — copy safety (AC-14 tooltip half)", () => {
  it("emits only band vocabulary plus the score", () => {
    expect(icpFitLabel(82)).toBe("strong ICP fit · 82");
    expect(icpFitLabel(50)).toBe("partial ICP fit · 50");
  });

  it("is null when unscored, so nothing renders", () => {
    expect(icpFitLabel(null)).toBeNull();
    expect(icpFitTooltip(null)).toBeNull();
    expect(icpFitTooltip(undefined)).toBeNull();
  });

  it("never contains any substring of adversarial site_profile text", () => {
    for (let score = 0; score <= 100; score += 5) {
      const label = icpFitLabel(score)!;
      const tooltip = icpFitTooltip(score)!;
      for (const fragment of ADVERSARIAL_FRAGMENTS) {
        expect(label).not.toContain(fragment);
        expect(tooltip).not.toContain(fragment);
      }
      expect(label).not.toContain(ADVERSARIAL);
      expect(tooltip).not.toContain(ADVERSARIAL);
    }
  });

  it("tooltip always names exactly one band and no ICP specifics", () => {
    const tooltip = icpFitTooltip(85)!;
    const matched = ICP_FIT_BANDS.filter((band) => tooltip.includes(band));
    expect(matched).toEqual(["strong ICP fit"]);
  });
});
