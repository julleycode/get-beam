import { describe, expect, it } from "vitest";
import {
  computeWizardStepIndex,
  isChromeOrEdgeUserAgent,
  WIZARD_STEP_BROWSER,
  WIZARD_STEP_CONNECT,
  WIZARD_STEP_INSTALL,
  WIZARD_STEP_SIGNIN,
} from "./use-linkedin-extension-status";

// Pure step-derivation coverage for the LinkedIn onboarding wizard (plan D3).
// Kept pure precisely so it is provable here in the node-env lane instead of
// only through a 60s-wall-clock e2e run.

describe("computeWizardStepIndex", () => {
  it("dead-ends on the browser step when not Chrome/Edge", () => {
    expect(computeWizardStepIndex(false, null, false)).toBe(WIZARD_STEP_BROWSER);
    // Even with every other signal true, an unsupported browser has no path.
    expect(computeWizardStepIndex(true, true, false)).toBe(WIZARD_STEP_BROWSER);
  });

  it("no signals on Chrome/Edge → install step (Step 1 auto-passes, AC1)", () => {
    expect(computeWizardStepIndex(false, null, true)).toBe(WIZARD_STEP_INSTALL);
    expect(computeWizardStepIndex(false, false, true)).toBe(WIZARD_STEP_INSTALL);
  });

  it("extension detected but not signed in → sign-in step (AC2)", () => {
    expect(computeWizardStepIndex(true, false, true)).toBe(WIZARD_STEP_SIGNIN);
    // Not yet probed is treated as not-signed-in, never as signed-in.
    expect(computeWizardStepIndex(true, null, true)).toBe(WIZARD_STEP_SIGNIN);
  });

  it("extension + signed in → connect step (AC3 / AC10 short-circuit)", () => {
    expect(computeWizardStepIndex(true, true, true)).toBe(WIZARD_STEP_CONNECT);
  });
});

describe("isChromeOrEdgeUserAgent", () => {
  it("accepts Chrome and Edge", () => {
    expect(
      isChromeOrEdgeUserAgent(
        "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
      )
    ).toBe(true);
    expect(
      isChromeOrEdgeUserAgent(
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
      )
    ).toBe(true);
  });

  it("rejects Safari, Firefox, Opera and empty UAs (AC9)", () => {
    expect(
      isChromeOrEdgeUserAgent(
        "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
      )
    ).toBe(false);
    expect(
      isChromeOrEdgeUserAgent("Mozilla/5.0 (Macintosh; rv:130.0) Gecko/20100101 Firefox/130.0")
    ).toBe(false);
    expect(
      isChromeOrEdgeUserAgent(
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 OPR/115.0.0.0"
      )
    ).toBe(false);
    expect(isChromeOrEdgeUserAgent("")).toBe(false);
  });
});
