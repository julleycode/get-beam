import { describe, it, expect } from "vitest";
import {
  LISTEN_DEADLINE_MS,
  MAX_CONSECUTIVE_ERRORS,
  POLL_BACKOFF_AFTER_MS,
  POLL_FAST_MS,
  POLL_SLOW_MS,
  pollIntervalFor,
  statusFor,
} from "@/lib/canary-listen-status";

describe("statusFor", () => {
  it("escalates through the four bands", () => {
    expect(statusFor(0)).toBe("listening…");
    expect(statusFor(7_999)).toBe("listening…");
    expect(statusFor(8_000)).toBe("open a page on getbeam.fyi…");
    expect(statusFor(24_999)).toBe("open a page on getbeam.fyi…");
    expect(statusFor(25_000)).toBe("still listening — did the tab actually load?");
    expect(statusFor(59_999)).toBe("still listening — did the tab actually load?");
    expect(statusFor(60_000)).toBe("one more moment…");
    expect(statusFor(LISTEN_DEADLINE_MS)).toBe("one more moment…");
  });

  it("never leaves the user staring at an unchanging line for the whole wait", () => {
    const seen = new Set(
      [0, 10_000, 30_000, 70_000].map((ms) => statusFor(ms)),
    );
    expect(seen.size).toBe(4);
  });
});

describe("pollIntervalFor", () => {
  it("backs off 2s -> 4s at the 20s mark", () => {
    expect(pollIntervalFor(0)).toBe(POLL_FAST_MS);
    expect(pollIntervalFor(POLL_BACKOFF_AFTER_MS - 1)).toBe(POLL_FAST_MS);
    expect(pollIntervalFor(POLL_BACKOFF_AFTER_MS)).toBe(POLL_SLOW_MS);
    expect(pollIntervalFor(89_000)).toBe(POLL_SLOW_MS);
  });

  /**
   * THE REGRESSION THIS FILE EXISTS FOR. A flat 2s across the 90s deadline is
   * 45 calls against a 30/minute limit and 429s in the middle of the reveal.
   */
  it("keeps the whole 90s window under the endpoint's 30/minute budget", () => {
    let elapsed = 0;
    let calls = 0;
    while (elapsed < LISTEN_DEADLINE_MS) {
      calls += 1;
      elapsed += pollIntervalFor(elapsed);
    }
    expect(calls).toBeLessThanOrEqual(30);
    // Sanity: the naive flat-2s version would have blown the budget.
    expect(Math.ceil(LISTEN_DEADLINE_MS / POLL_FAST_MS)).toBeGreaterThan(30);
  });
});

describe("constants", () => {
  it("gives a dormant endpoint a fast exit instead of the full deadline", () => {
    expect(MAX_CONSECUTIVE_ERRORS).toBeGreaterThan(1);
    expect(MAX_CONSECUTIVE_ERRORS * POLL_FAST_MS).toBeLessThan(LISTEN_DEADLINE_MS);
  });
});
