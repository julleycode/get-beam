// Agent-paid API configuration (server-only).
//
// External AI agents pay per call (MPP or x402 via InFlow) to reach four Beam
// operations; the web layer verifies payment and forwards to the internal Python
// endpoints at {BEAM_API_BASE}/internal/v1/paid/*. Everything here is read from
// env LAZILY (per call, never at import) so a missing variable can only ever
// produce a 503 on /api/paid — it can never break the build or other routes.
//
// `server-only` is not a declared dependency of apps/web (it exists only
// transitively) and its default entry throws under vitest, so a runtime guard
// stands in for it: this module must never be bundled into client code.
if (typeof window !== "undefined") {
  throw new Error("paid-config is server-only");
}

export const PAID_OPS = ["enrich-email", "ip-company", "deep-research", "outreach-draft"] as const;
export type PaidOp = (typeof PAID_OPS)[number];

export const PAID_BASE_PATH = "/api/paid";

export type InflowEnvironment = "sandbox" | "production";

export interface PaidRoute {
  op: PaidOp;
  /** Public path the agent calls, e.g. /api/paid/ip-company. */
  path: string;
  /** Internal Python path, e.g. /internal/v1/paid/ip-company. */
  pythonPath: string;
  /** USDC decimal string, e.g. "0.02". */
  price: string;
  /** Upstream (Python) timeout in milliseconds. */
  timeoutMs: number;
}

export interface PaidConfig {
  inflowApiKey: string;
  inflowEnvironment: InflowEnvironment;
  mppSecretKey: string;
  /** BEAM_API_BASE with any trailing slash removed. */
  beamApiBase: string;
  internalSecret: string;
  routes: Record<PaidOp, PaidRoute>;
}

export type PaidConfigResult =
  | { ok: true; config: PaidConfig }
  /** `problems` holds env VARIABLE NAMES only — never values. */
  | { ok: false; problems: string[] };

type Env = Readonly<Record<string, string | undefined>>;

const PRICE_ENV: Record<PaidOp, { name: string; fallback: string }> = {
  "enrich-email": { name: "PAID_PRICE_ENRICH_EMAIL", fallback: "0.05" },
  "ip-company": { name: "PAID_PRICE_IP_COMPANY", fallback: "0.02" },
  "deep-research": { name: "PAID_PRICE_DEEP_RESEARCH", fallback: "0.25" },
  "outreach-draft": { name: "PAID_PRICE_OUTREACH_DRAFT", fallback: "0.05" },
};

const TIMEOUT_MS: Record<PaidOp, number> = {
  "enrich-email": 30_000,
  "ip-company": 30_000,
  "deep-research": 60_000,
  "outreach-draft": 30_000,
};

/** mppx itself rejects secret keys shorter than 32 UTF-8 bytes (Mppx.create). */
export const MPP_SECRET_MIN_BYTES = 32;

// Up to 8 decimal places — the widest form InFlow's price grammar accepts.
const DECIMAL_RE = /^\d+(\.\d{1,8})?$/;

export function isPositiveDecimal(value: string): boolean {
  return DECIMAL_RE.test(value) && Number(value) > 0;
}

/** AGENT_PAID_ENABLED must be exactly "true"; anything else keeps /api/paid dark (404). */
export function isPaidEnabled(env: Env = process.env): boolean {
  return env.AGENT_PAID_ENABLED === "true";
}

function nonEmpty(env: Env, name: string, problems: string[]): string {
  const value = env[name]?.trim() ?? "";
  if (!value) problems.push(name);
  return value;
}

/**
 * Validate every variable and report ALL problems at once (names only), so an
 * operator fixes a misconfigured deploy in one pass.
 */
export function loadPaidConfig(env: Env = process.env): PaidConfigResult {
  const problems: string[] = [];

  const inflowApiKey = nonEmpty(env, "INFLOW_API_KEY", problems);
  const internalSecret = nonEmpty(env, "INTERNAL_PAID_API_SECRET", problems);

  // Required with NO default: the InFlow SDKs default to production, so an
  // unset value must fail closed rather than silently take real payments.
  const rawEnvironment = env.INFLOW_ENVIRONMENT?.trim();
  const inflowEnvironment: InflowEnvironment | undefined =
    rawEnvironment === "sandbox" || rawEnvironment === "production" ? rawEnvironment : undefined;
  if (!inflowEnvironment) problems.push("INFLOW_ENVIRONMENT");

  const mppSecretKey = env.MPP_SECRET_KEY ?? "";
  if (new TextEncoder().encode(mppSecretKey).byteLength < MPP_SECRET_MIN_BYTES) {
    problems.push("MPP_SECRET_KEY");
  }

  const beamApiBase = (env.BEAM_API_BASE?.trim() ?? "").replace(/\/+$/, "");
  if (!isHttpUrl(beamApiBase)) problems.push("BEAM_API_BASE");

  const routes = {} as Record<PaidOp, PaidRoute>;
  for (const op of PAID_OPS) {
    const { name, fallback } = PRICE_ENV[op];
    const raw = env[name]?.trim();
    const price = raw ? raw : fallback;
    if (!isPositiveDecimal(price)) problems.push(name);
    routes[op] = {
      op,
      path: `${PAID_BASE_PATH}/${op}`,
      pythonPath: `/internal/v1/paid/${op}`,
      price,
      timeoutMs: TIMEOUT_MS[op],
    };
  }

  if (problems.length > 0 || !inflowEnvironment) {
    return { ok: false, problems };
  }
  return {
    ok: true,
    config: { inflowApiKey, inflowEnvironment, mppSecretKey, beamApiBase, internalSecret, routes },
  };
}

function isHttpUrl(value: string): boolean {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function isPaidOp(value: string): value is PaidOp {
  return (PAID_OPS as readonly string[]).includes(value);
}
