import { describe, it, expect } from "vitest";
import { hash128, fpParts } from "@/lib/beam-fingerprint";

/**
 * These are GOLDEN values, not arbitrary fixtures.
 *
 * CHANGING THEM BREAKS THE PIXEL JOIN. `hash128` and the `|`-joined component
 * string must stay byte-identical to apps/pixel/src/tracker.js fp2
 * (tracker.js:86 `hash128`, :203-231 `fpParts`). If this test starts failing
 * after a "cleanup" of beam-fingerprint.ts, the cleanup is the bug: the
 * dashboard would compute one fingerprint while the pixel stores another, the
 * canary lookup would match nothing, and the reveal would silently degrade
 * with no error logged anywhere.
 */
describe("hash128 — golden vectors", () => {
  it("hashes the empty string to the frozen value", () => {
    expect(hash128("")).toBe("ztntfp1j46w0ju2m0q6r4qa87");
  });

  it("hashes a short ascii string to the frozen value", () => {
    expect(hash128("abc")).toBe("7aigaz1yocenp1xcercu164ne71");
  });

  it("is deterministic across calls", () => {
    expect(hash128("beam")).toBe(hash128("beam"));
  });

  it("is sensitive to a single-character change", () => {
    expect(hash128("beam")).not.toBe(hash128("beao"));
  });
});

describe("fpParts — fixed component array produces the exact fp2 hash", () => {
  // A realistic component array in the EXACT order tracker.js pushes them.
  const COMPONENTS: unknown[] = [
    "1512x982", // screen.width x screen.height
    "1512x982", // availWidth x availHeight
    30, // colorDepth
    2, // devicePixelRatio
    "en-US", // language
    "MacIntel", // platform
    10, // hardwareConcurrency
    8, // deviceMemory
    0, // maxTouchPoints
    1, // cookieEnabled
    "", // doNotTrack
    1, // pdfViewerEnabled
    "Asia/Ho_Chi_Minh", // Intl timezone
    "4g", // connection.effectiveType
    "AAAASUVORK5CYII=", // canvasFp()
    "Apple Inc.~Apple M2~16384", // webglFp()
    Math.tan(-1e300), // the constant tail
  ];

  const JOINED =
    "1512x982|1512x982|30|2|en-US|MacIntel|10|8|0|1||1|Asia/Ho_Chi_Minh|4g|" +
    "AAAASUVORK5CYII=|Apple Inc.~Apple M2~16384|-1.4214488238747245";

  it("joins components with '|' exactly as tracker.js does", () => {
    expect(fpParts(COMPONENTS)).toBe(JOINED);
  });

  it("Math.tan(-1e300) still coerces to the frozen string", () => {
    // A JS engine change here would silently re-fingerprint every browser.
    expect(String(Math.tan(-1e300))).toBe("-1.4214488238747245");
  });

  it("produces the exact fp2 hash string", () => {
    expect(hash128(fpParts(COMPONENTS))).toBe("1rkiwjbivbqup1t1dwcwnky7ad");
    expect("fp2_" + hash128(fpParts(COMPONENTS))).toBe(
      "fp2_1rkiwjbivbqup1t1dwcwnky7ad",
    );
  });

  it("reordering two components changes the hash (order is contract)", () => {
    const swapped = [...COMPONENTS];
    [swapped[4], swapped[5]] = [swapped[5], swapped[4]];
    expect(hash128(fpParts(swapped))).not.toBe("1rkiwjbivbqup1t1dwcwnky7ad");
  });
});
