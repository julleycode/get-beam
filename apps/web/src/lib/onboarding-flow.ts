/**
 * Onboarding conversational flow — the pure, node-testable half.
 *
 * `apps/web/vitest.config.ts` runs `environment: "node"` over
 * `src/**\/*.test.ts` with no jsdom and no testing-library, so every decision
 * the chat makes lives here as a pure function and the React layer stays a
 * thin renderer. See the plan's "Logic lives in src/lib" constraint.
 */

import type { CanaryResponse } from "@/lib/canary-format";

export type StepId =
  | "welcome"
  | "canary_go"
  | "canary_listen"
  | "canary_reveal"
  | "confirm"
  | "site"
  | "install"
  | "done";

/**
 * The full 8-step order. The four `canary_*`/`confirm` steps are declared and
 * reducible NOW but are not reachable until the canary ships (Phase 3): with
 * `canaryEnabled === false`, `welcome` advances straight to `site`.
 */
export const STEP_ORDER: readonly StepId[] = [
  "welcome",
  "canary_go",
  "canary_listen",
  "canary_reveal",
  "confirm",
  "site",
  "install",
  "done",
] as const;

/** The steps gated behind the location-reveal feature. */
export const CANARY_STEPS: readonly StepId[] = [
  "canary_go",
  "canary_listen",
  "canary_reveal",
  "confirm",
] as const;

/**
 * Phase 3 flips this on: `welcome` now advances to `canary_go` and the four
 * canary steps become reachable. The client-side switch is intentionally
 * independent of the server flag — when `location_reveal_enabled` is off the
 * endpoint 404s, the listen step treats that as "nothing landed", and the flow
 * degrades to an honest line straight into `site`.
 */
export const CANARY_ENABLED = true;

export type CanaryOutcome = "landed" | "geo_only" | "nothing" | "skipped" | null;

export interface FlowState {
  step: StepId;
  /** Site created in the `site` step (also the resume key). */
  siteId: string | null;
  siteUrl: string | null;
  snippet: string;
  platform: string;
  hasGtm: boolean;
  gtmId: string | null;
  /** Platform detection in flight. */
  detecting: boolean;
  /** How many times platform detection has been retried (retry-once). */
  detectAttempts: number;
  /** Site creation in flight. */
  submitting: boolean;
  error: string | null;
  showUpgrade: boolean;
  canaryOutcome: CanaryOutcome;
  /**
   * fp2, computed on the `canary_go` CLICK — not lazily inside the poll. The
   * dashboard tab is backgrounded while the user reads the other tab, and a
   * backgrounded tab can perturb the canvas probe (throttled rAF, suspended
   * compositing), which would produce a different hash than the pixel stored.
   */
  fingerprint: string | null;
  /** The raw reveal payload, kept so `confirm` can report exactly what we showed. */
  canary: CanaryResponse | null;
}

export const initialFlowState: FlowState = {
  step: "welcome",
  siteId: null,
  siteUrl: null,
  snippet: "",
  platform: "unknown",
  hasGtm: false,
  gtmId: null,
  detecting: false,
  detectAttempts: 0,
  submitting: false,
  error: null,
  showUpgrade: false,
  canaryOutcome: null,
  fingerprint: null,
  canary: null,
};

export type FlowEvent =
  | { type: "ADVANCE" }
  | { type: "GOTO"; step: StepId }
  | { type: "SKIP_CANARY" }
  | { type: "CANARY_START"; fingerprint: string }
  | {
      type: "CANARY_RESULT";
      outcome: Exclude<CanaryOutcome, null>;
      response?: CanaryResponse | null;
    }
  | { type: "SITE_SUBMIT" }
  | {
      type: "SITE_CREATED";
      siteId: string;
      snippet: string;
      url: string;
    }
  | { type: "SITE_FAILED"; message: string; showUpgrade?: boolean }
  | {
      type: "PLATFORM_DETECTED";
      platform: string;
      hasGtm: boolean;
      gtmId: string | null;
    }
  | { type: "PLATFORM_FAILED" }
  | { type: "SNIPPET_UPDATED"; snippet: string }
  | { type: "VERIFIED" }
  | { type: "RESUME"; step: StepId; siteId?: string | null; snippet?: string }
  | { type: "CLEAR_ERROR" };

/** Index-safe successor in STEP_ORDER, honouring the canary gate. */
export function nextStep(step: StepId, canaryEnabled = CANARY_ENABLED): StepId {
  if (!canaryEnabled && step === "welcome") return "site";
  const i = STEP_ORDER.indexOf(step);
  if (i < 0) return "welcome";
  if (i >= STEP_ORDER.length - 1) return "done";
  const candidate = STEP_ORDER[i + 1];
  if (!canaryEnabled && CANARY_STEPS.includes(candidate)) return "site";
  return candidate;
}

export function isStepId(value: unknown): value is StepId {
  return typeof value === "string" && (STEP_ORDER as readonly string[]).includes(value);
}

/**
 * Where a persisted step is allowed to resume.
 *
 * - unknown / never-seen id → `welcome` (a legacy `beam_ob_step` value would
 *   otherwise resume into a dead step)
 * - `canary_listen` → `canary_go`: it carries a 90s deadline that cannot be
 *   resumed, so restart the catch instead of resuming a dead timer
 * - `canary_reveal` / `confirm` → `canary_go`: both render the reveal payload,
 *   which is deliberately never persisted (no coordinates are stored anywhere).
 *   Resuming into them would show an empty card.
 * - any canary step while the canary is off → `welcome`
 */
const UNRESUMABLE_CANARY_STEPS: readonly StepId[] = [
  "canary_listen",
  "canary_reveal",
  "confirm",
] as const;

export function sanitizeResumeStep(
  step: unknown,
  canaryEnabled = CANARY_ENABLED,
): StepId {
  if (!isStepId(step)) return "welcome";
  if (UNRESUMABLE_CANARY_STEPS.includes(step)) {
    return canaryEnabled ? "canary_go" : "welcome";
  }
  if (!canaryEnabled && CANARY_STEPS.includes(step)) return "welcome";
  return step;
}

export function flowReducer(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case "ADVANCE":
      return { ...state, step: nextStep(state.step), error: null };

    // Intra-session navigation, so it is LITERAL — unlike RESUME, which
    // sanitizes because a persisted step may no longer be rehydratable.
    // (`confirm` is reached this way and must not be rewritten to `canary_go`.)
    case "GOTO":
      return {
        ...state,
        step: isStepId(event.step) ? event.step : "welcome",
        error: null,
      };

    case "SKIP_CANARY":
      return { ...state, step: "site", canaryOutcome: "skipped", error: null };

    // The catch begins: stash the fingerprint computed on the click (see
    // FlowState.fingerprint) and move to the radar.
    case "CANARY_START":
      return {
        ...state,
        fingerprint: event.fingerprint || null,
        canary: null,
        canaryOutcome: null,
        step: "canary_listen",
        error: null,
      };

    case "CANARY_RESULT":
      return {
        ...state,
        canaryOutcome: event.outcome,
        canary: event.response ?? state.canary,
        step: event.outcome === "nothing" ? "site" : "canary_reveal",
      };

    case "SITE_SUBMIT":
      return { ...state, submitting: true, error: null, showUpgrade: false };

    case "SITE_CREATED":
      return {
        ...state,
        submitting: false,
        siteId: event.siteId,
        snippet: event.snippet,
        siteUrl: event.url,
        step: "install",
        detecting: true,
        detectAttempts: 0,
        error: null,
      };

    case "SITE_FAILED":
      return {
        ...state,
        submitting: false,
        error: event.message,
        showUpgrade: !!event.showUpgrade,
      };

    case "PLATFORM_DETECTED":
      return {
        ...state,
        detecting: false,
        platform: event.platform,
        hasGtm: event.hasGtm,
        gtmId: event.gtmId,
      };

    // Retry-once: the first detection failure keeps the spinner up and bumps
    // the attempt counter so the caller re-runs it; the second gives up and
    // falls back to the generic "unknown" install guide rather than looping.
    case "PLATFORM_FAILED":
      if (state.detectAttempts < 1) {
        return { ...state, detectAttempts: state.detectAttempts + 1, detecting: true };
      }
      return { ...state, detecting: false, platform: "unknown" };

    case "SNIPPET_UPDATED":
      return { ...state, snippet: event.snippet };

    case "VERIFIED":
      return { ...state, step: "done" };

    case "RESUME":
      return {
        ...state,
        step: sanitizeResumeStep(event.step),
        siteId: event.siteId ?? state.siteId,
        snippet: event.snippet ?? state.snippet,
      };

    case "CLEAR_ERROR":
      return { ...state, error: null, showUpgrade: false };

    default:
      return state;
  }
}

// ── typing cadence ─────────────────────────────────────────────────────────

/**
 * How long the typing dots show before a bot line reveals.
 * Clamped to 480–1300ms; 0 when the user asked for reduced motion.
 */
export function typingDelay(text: string, reduced = false): number {
  if (reduced) return 0;
  return Math.min(1300, Math.max(480, text.length * 22));
}

// ── persistence ────────────────────────────────────────────────────────────

/**
 * New key on purpose. `beam_ob_step` holds the legacy static funnel's step
 * vocabulary; reusing it would resume into ids that no longer exist.
 */
export const FLOW_STORAGE_KEY = "beam_onboarding_v2";
export const FLOW_STORAGE_VERSION = 2;

export interface PersistedFlow {
  v: number;
  step: StepId;
  siteId: string | null;
  canaryOutcome: CanaryOutcome;
}

/** Minimal shape we need — lets tests pass a plain in-memory stub. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // storage blocked (Safari private mode, strict cookie policy)
  }
}

export function saveFlowState(
  state: Pick<FlowState, "step" | "siteId" | "canaryOutcome">,
  storage: StorageLike | null = defaultStorage(),
): void {
  if (!storage) return;
  const payload: PersistedFlow = {
    v: FLOW_STORAGE_VERSION,
    step: state.step,
    siteId: state.siteId,
    canaryOutcome: state.canaryOutcome,
  };
  try {
    storage.setItem(FLOW_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* quota or blocked — resume is a nicety, never a hard dependency */
  }
}

export function loadFlowState(
  storage: StorageLike | null = defaultStorage(),
  canaryEnabled = CANARY_ENABLED,
): PersistedFlow | null {
  if (!storage) return null;
  let raw: string | null;
  try {
    raw = storage.getItem(FLOW_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const obj = parsed as Record<string, unknown>;
  if (obj.v !== FLOW_STORAGE_VERSION) return null;
  return {
    v: FLOW_STORAGE_VERSION,
    step: sanitizeResumeStep(obj.step, canaryEnabled),
    siteId: typeof obj.siteId === "string" ? obj.siteId : null,
    canaryOutcome:
      obj.canaryOutcome === "landed" ||
      obj.canaryOutcome === "geo_only" ||
      obj.canaryOutcome === "nothing" ||
      obj.canaryOutcome === "skipped"
        ? obj.canaryOutcome
        : null,
  };
}

export function clearFlowState(
  storage: StorageLike | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(FLOW_STORAGE_KEY);
  } catch {
    /* nothing to do */
  }
}
