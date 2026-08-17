import { describe, expect, it } from "vitest";

import {
  NO_DATA_LABEL,
  OPEN_RATE_CAVEAT,
  WHATS_WORKING_SUBTITLE,
  WHATS_WORKING_TITLE,
  benchmarkComparisonLabel,
  openRateLabel,
} from "./open-rate-copy";

// AC-8b (copy correctness). Visual PLACEMENT of the caveat on the rendered page
// is a named Agent-Probe residual: apps/web has no @testing-library/react,
// jsdom or happy-dom, and Playwright is blocked by the Clerk auth-harness gap.
// This suite proves the copy itself, in the existing pure vitest lane.

describe("open-rate caveat", () => {
  it("names both failure directions and the reliable signal", () => {
    const lowered = OPEN_RATE_CAVEAT.toLowerCase();
    expect(lowered).toContain("apple mail privacy protection");
    expect(lowered).toContain("overcounting");
    expect(lowered).toContain("undercounting");
    expect(lowered).toContain("clicks are the reliable signal");
  });

  it("is a single constant so it cannot drift per surface", () => {
    expect(OPEN_RATE_CAVEAT).toBe(
      "Open rates are unreliable: Apple Mail Privacy Protection prefetches " +
        "tracking pixels (overcounting) and blocked images suppress them " +
        "(undercounting). Clicks are the reliable signal.",
    );
  });
});

describe("openRateLabel", () => {
  it("renders no-data (never 0%) when nothing was sent", () => {
    for (const value of [null, undefined, NaN]) {
      expect(openRateLabel(value as number | null)).toBe(NO_DATA_LABEL);
      expect(openRateLabel(value as number | null)).not.toContain("0.0%");
    }
  });

  it("renders a MEASURED zero as 0.0%", () => {
    expect(openRateLabel(0)).toBe("0.0%");
    expect(openRateLabel(0)).not.toBe(NO_DATA_LABEL);
  });

  it("formats a rate as a one-decimal percentage", () => {
    expect(openRateLabel(0.4237)).toBe("42.4%");
    expect(openRateLabel(1)).toBe("100.0%");
  });
});

describe("benchmarkComparisonLabel", () => {
  it("says category average and never median", () => {
    const label = benchmarkComparisonLabel("saas", 0.42, 0.31);
    expect(label).toContain("category average");
    expect(label.toLowerCase()).not.toContain("median");
  });

  it("humanizes the closed-vocabulary token", () => {
    expect(benchmarkComparisonLabel("real_estate", 0.1, 0.2)).toContain(
      "real estate",
    );
  });

  it("renders no-data for a site that sent nothing, keeping the average", () => {
    const label = benchmarkComparisonLabel("saas", null, 0.31);
    expect(label).toContain(NO_DATA_LABEL);
    expect(label).toContain("31.0%");
  });

  it("publishes no period-over-period delta", () => {
    const label = benchmarkComparisonLabel("saas", 0.42, 0.31).toLowerCase();
    for (const token of ["last week", "vs last", "previous period", "change"]) {
      expect(label).not.toContain(token);
    }
  });

  it("exposes no site_count anonymity parameter", () => {
    const label = benchmarkComparisonLabel("saas", 0.42, 0.31);
    expect(label).not.toContain("site_count");
    expect(label.toLowerCase()).not.toContain("sites contributed");
  });
});

describe("what's-working panel copy", () => {
  it("says campaign and segment, never subject", () => {
    const copy = `${WHATS_WORKING_TITLE} ${WHATS_WORKING_SUBTITLE}`.toLowerCase();
    expect(copy).toContain("campaign");
    expect(copy).toContain("segment");
    // Subject-line ranking is deferred; claiming it would be false.
    expect(copy).not.toContain("subject");
  });
});
