import { describe, it, expect } from "vitest";
import {
  STEP_ORDER,
  CANARY_STEPS,
  CANARY_ENABLED,
  flowReducer,
  initialFlowState,
  nextStep,
  sanitizeResumeStep,
  isStepId,
  typingDelay,
  saveFlowState,
  loadFlowState,
  clearFlowState,
  FLOW_STORAGE_KEY,
  type FlowState,
  type StepId,
  type StorageLike,
} from "@/lib/onboarding-flow";

function memoryStorage(): StorageLike & { dump(): Record<string, string> } {
  const map = new Map<string, string>();
  return {
    getItem: (k) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    dump: () => Object.fromEntries(map),
  };
}

const base = (over: Partial<FlowState> = {}): FlowState => ({
  ...initialFlowState,
  ...over,
});

// ── STEP_ORDER integrity ───────────────────────────────────────────────────

describe("STEP_ORDER", () => {
  it("is exactly the 8 planned steps in order", () => {
    expect([...STEP_ORDER]).toEqual([
      "welcome",
      "canary_go",
      "canary_listen",
      "canary_reveal",
      "confirm",
      "site",
      "install",
      "done",
    ]);
  });

  it("has no duplicates", () => {
    expect(new Set(STEP_ORDER).size).toBe(STEP_ORDER.length);
  });

  it("declares the canary steps as a contiguous subset", () => {
    expect([...CANARY_STEPS]).toEqual([
      "canary_go",
      "canary_listen",
      "canary_reveal",
      "confirm",
    ]);
    for (const s of CANARY_STEPS) expect(STEP_ORDER).toContain(s);
  });

  // Phase 3 flipped this on. It is asserted rather than merely used so that
  // turning the canary off again is a deliberate, visible change.
  it("ships with the canary ON", () => {
    expect(CANARY_ENABLED).toBe(true);
  });

  it("isStepId accepts every declared step and rejects junk", () => {
    for (const s of STEP_ORDER) expect(isStepId(s)).toBe(true);
    for (const junk of ["", "detect", "paywall", "walk", null, 3, {}]) {
      expect(isStepId(junk)).toBe(false);
    }
  });
});

// ── transitions ────────────────────────────────────────────────────────────

describe("nextStep", () => {
  it("skips the whole canary block when the canary is off", () => {
    expect(nextStep("welcome", false)).toBe("site");
  });

  it("walks the canary block when the canary is on", () => {
    expect(nextStep("welcome", true)).toBe("canary_go");
    expect(nextStep("canary_go", true)).toBe("canary_listen");
    expect(nextStep("canary_listen", true)).toBe("canary_reveal");
    expect(nextStep("canary_reveal", true)).toBe("confirm");
    expect(nextStep("confirm", true)).toBe("site");
  });

  it("walks the shipping tail identically in both modes", () => {
    for (const enabled of [true, false]) {
      expect(nextStep("site", enabled)).toBe("install");
      expect(nextStep("install", enabled)).toBe("done");
      expect(nextStep("done", enabled)).toBe("done");
    }
  });

  it("falls back to welcome for an unknown step", () => {
    expect(nextStep("nope" as StepId, true)).toBe("welcome");
  });
});

describe("flowReducer", () => {
  it("ADVANCE from welcome opens the canary", () => {
    expect(flowReducer(base(), { type: "ADVANCE" }).step).toBe("canary_go");
  });

  it("ADVANCE clears a stale error", () => {
    const next = flowReducer(base({ error: "boom" }), { type: "ADVANCE" });
    expect(next.error).toBeNull();
  });

  // GOTO is intra-session navigation and therefore LITERAL. `confirm` is
  // reached exactly this way from the reveal, so rewriting it (as the resume
  // sanitizer does) would bounce the user back to the start of the catch.
  it("GOTO lands literally on any declared step", () => {
    for (const s of CANARY_STEPS) {
      expect(flowReducer(base(), { type: "GOTO", step: s }).step).toBe(s);
    }
  });

  it("GOTO falls back to welcome for junk", () => {
    expect(flowReducer(base(), { type: "GOTO", step: "nope" as StepId }).step).toBe(
      "welcome",
    );
  });

  it("CANARY_START stashes the click-time fingerprint and opens the radar", () => {
    const next = flowReducer(base({ step: "canary_go" }), {
      type: "CANARY_START",
      fingerprint: "fp2_abc",
    });
    expect(next.step).toBe("canary_listen");
    expect(next.fingerprint).toBe("fp2_abc");
    expect(next.canary).toBeNull();
  });

  it("CANARY_RESULT keeps the payload for the reveal, and 'nothing' skips it", () => {
    const response = {
      landed: true,
      pages: [],
      geo: null,
      network: null,
    };
    const landed = flowReducer(base({ step: "canary_listen" }), {
      type: "CANARY_RESULT",
      outcome: "landed",
      response,
    });
    expect(landed.step).toBe("canary_reveal");
    expect(landed.canary).toBe(response);

    const nothing = flowReducer(base({ step: "canary_listen" }), {
      type: "CANARY_RESULT",
      outcome: "nothing",
      response: null,
    });
    expect(nothing.step).toBe("site");
  });

  it("SKIP_CANARY goes to site and records the outcome", () => {
    const next = flowReducer(base({ step: "canary_go" }), { type: "SKIP_CANARY" });
    expect(next.step).toBe("site");
    expect(next.canaryOutcome).toBe("skipped");
  });

  it("CANARY_RESULT routes to reveal, except when nothing landed", () => {
    expect(
      flowReducer(base({ step: "canary_listen" }), {
        type: "CANARY_RESULT",
        outcome: "landed",
      }).step,
    ).toBe("canary_reveal");
    expect(
      flowReducer(base({ step: "canary_listen" }), {
        type: "CANARY_RESULT",
        outcome: "geo_only",
      }).step,
    ).toBe("canary_reveal");
    expect(
      flowReducer(base({ step: "canary_listen" }), {
        type: "CANARY_RESULT",
        outcome: "nothing",
      }).step,
    ).toBe("site");
  });

  it("SITE_SUBMIT sets submitting and clears the upgrade prompt", () => {
    const next = flowReducer(base({ error: "x", showUpgrade: true }), {
      type: "SITE_SUBMIT",
    });
    expect(next).toMatchObject({ submitting: true, error: null, showUpgrade: false });
  });

  it("SITE_CREATED advances to install and starts detection", () => {
    const next = flowReducer(base({ step: "site", submitting: true }), {
      type: "SITE_CREATED",
      siteId: "site_abc",
      snippet: "<script>",
      url: "https://example.com",
    });
    expect(next).toMatchObject({
      step: "install",
      siteId: "site_abc",
      snippet: "<script>",
      siteUrl: "https://example.com",
      detecting: true,
      detectAttempts: 0,
      submitting: false,
    });
  });

  it("SITE_FAILED keeps the user on site with the error", () => {
    const next = flowReducer(base({ step: "site", submitting: true }), {
      type: "SITE_FAILED",
      message: "Site limit reached",
      showUpgrade: true,
    });
    expect(next).toMatchObject({
      step: "site",
      submitting: false,
      error: "Site limit reached",
      showUpgrade: true,
    });
  });

  it("PLATFORM_DETECTED stores the platform and stops the spinner", () => {
    const next = flowReducer(base({ detecting: true }), {
      type: "PLATFORM_DETECTED",
      platform: "shopify",
      hasGtm: true,
      gtmId: "GTM-1",
    });
    expect(next).toMatchObject({
      detecting: false,
      platform: "shopify",
      hasGtm: true,
      gtmId: "GTM-1",
    });
  });

  // retry-once
  it("PLATFORM_FAILED retries exactly once, then falls back to unknown", () => {
    const first = flowReducer(base({ detecting: true }), { type: "PLATFORM_FAILED" });
    expect(first).toMatchObject({ detecting: true, detectAttempts: 1 });

    const second = flowReducer(first, { type: "PLATFORM_FAILED" });
    expect(second).toMatchObject({ detecting: false, platform: "unknown" });

    // A third failure must not re-open the spinner.
    const third = flowReducer(second, { type: "PLATFORM_FAILED" });
    expect(third).toMatchObject({ detecting: false, platform: "unknown" });
  });

  it("SNIPPET_UPDATED swaps the snippet without moving the step", () => {
    const next = flowReducer(base({ step: "install", snippet: "old" }), {
      type: "SNIPPET_UPDATED",
      snippet: "new",
    });
    expect(next).toMatchObject({ step: "install", snippet: "new" });
  });

  it("VERIFIED ends on done", () => {
    expect(flowReducer(base({ step: "install" }), { type: "VERIFIED" }).step).toBe(
      "done",
    );
  });

  it("CLEAR_ERROR clears both error fields", () => {
    const next = flowReducer(base({ error: "x", showUpgrade: true }), {
      type: "CLEAR_ERROR",
    });
    expect(next).toMatchObject({ error: null, showUpgrade: false });
  });

  it("returns the same object for an unknown event", () => {
    const state = base();
    // @ts-expect-error — deliberately invalid event
    expect(flowReducer(state, { type: "NOPE" })).toBe(state);
  });

  it("never mutates the input state", () => {
    const state = base();
    const snapshot = JSON.stringify(state);
    flowReducer(state, { type: "ADVANCE" });
    expect(JSON.stringify(state)).toBe(snapshot);
  });
});

// ── resume safety ──────────────────────────────────────────────────────────

describe("sanitizeResumeStep", () => {
  it("NEVER resumes into canary_listen — its 90s deadline cannot be resumed", () => {
    expect(sanitizeResumeStep("canary_listen", true)).toBe("canary_go");
    expect(sanitizeResumeStep("canary_listen", false)).toBe("welcome");
    expect(sanitizeResumeStep("canary_listen")).not.toBe("canary_listen");
  });

  it("maps an unknown stored step to welcome", () => {
    for (const junk of ["detect", "paywall", "account", "", null, undefined, 7]) {
      expect(sanitizeResumeStep(junk)).toBe("welcome");
    }
  });

  it("sends every canary step to welcome while the canary is off", () => {
    for (const s of CANARY_STEPS) expect(sanitizeResumeStep(s, false)).toBe("welcome");
  });

  it("passes the shipping steps through untouched", () => {
    for (const s of ["welcome", "site", "install", "done"] as StepId[]) {
      expect(sanitizeResumeStep(s, false)).toBe(s);
    }
  });
});

// ── persistence ────────────────────────────────────────────────────────────

describe("flow state persistence", () => {
  it("round-trips step, siteId and canaryOutcome", () => {
    const store = memoryStorage();
    saveFlowState({ step: "install", siteId: "site_x", canaryOutcome: "landed" }, store);
    expect(loadFlowState(store)).toEqual({
      v: 2,
      step: "install",
      siteId: "site_x",
      canaryOutcome: "landed",
    });
  });

  it("writes under the v2 key, not the legacy beam_ob_step", () => {
    const store = memoryStorage();
    saveFlowState({ step: "site", siteId: null, canaryOutcome: null }, store);
    expect(Object.keys(store.dump())).toEqual([FLOW_STORAGE_KEY]);
    expect(FLOW_STORAGE_KEY).toBe("beam_onboarding_v2");
  });

  it("sanitizes the step on the way out, not just on the way in", () => {
    const store = memoryStorage();
    store.setItem(
      FLOW_STORAGE_KEY,
      JSON.stringify({ v: 2, step: "canary_listen", siteId: null, canaryOutcome: null }),
    );
    expect(loadFlowState(store, true)?.step).toBe("canary_go");
    expect(loadFlowState(store, false)?.step).toBe("welcome");
  });

  it("returns null for absent, corrupt, or wrong-version payloads", () => {
    const store = memoryStorage();
    expect(loadFlowState(store)).toBeNull();

    store.setItem(FLOW_STORAGE_KEY, "{not json");
    expect(loadFlowState(store)).toBeNull();

    store.setItem(FLOW_STORAGE_KEY, JSON.stringify({ v: 1, step: "install" }));
    expect(loadFlowState(store)).toBeNull();

    store.setItem(FLOW_STORAGE_KEY, JSON.stringify("a string"));
    expect(loadFlowState(store)).toBeNull();
  });

  it("drops an unrecognised canaryOutcome instead of trusting it", () => {
    const store = memoryStorage();
    store.setItem(
      FLOW_STORAGE_KEY,
      JSON.stringify({ v: 2, step: "site", siteId: 42, canaryOutcome: "hacked" }),
    );
    expect(loadFlowState(store)).toEqual({
      v: 2,
      step: "site",
      siteId: null,
      canaryOutcome: null,
    });
  });

  it("clearFlowState removes the key", () => {
    const store = memoryStorage();
    saveFlowState({ step: "site", siteId: "s", canaryOutcome: null }, store);
    clearFlowState(store);
    expect(loadFlowState(store)).toBeNull();
  });

  it("is a no-op when storage is unavailable", () => {
    expect(() => saveFlowState({ step: "site", siteId: null, canaryOutcome: null }, null)).not.toThrow();
    expect(loadFlowState(null)).toBeNull();
    expect(() => clearFlowState(null)).not.toThrow();
  });
});

// ── typing cadence ─────────────────────────────────────────────────────────

describe("typingDelay", () => {
  it("clamps short lines up to the 480ms floor", () => {
    expect(typingDelay("")).toBe(480);
    expect(typingDelay("hi")).toBe(480);
    // 21 chars * 22 = 462, still under the floor
    expect(typingDelay("x".repeat(21))).toBe(480);
  });

  it("clamps long lines down to the 1300ms ceiling", () => {
    // 60 chars * 22 = 1320 > 1300
    expect(typingDelay("x".repeat(60))).toBe(1300);
    expect(typingDelay("x".repeat(1000))).toBe(1300);
  });

  it("scales linearly between the bounds", () => {
    // 40 chars * 22 = 880
    expect(typingDelay("x".repeat(40))).toBe(880);
  });

  it("returns 0 when reduced motion is requested", () => {
    expect(typingDelay("x".repeat(40), true)).toBe(0);
    expect(typingDelay("", true)).toBe(0);
    expect(typingDelay("x".repeat(1000), true)).toBe(0);
  });
});
