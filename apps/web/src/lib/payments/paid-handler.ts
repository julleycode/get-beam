// Agent-paid request handling: dispatch, body/IP hygiene, Python forwarding,
// and the MPP / x402 payment flows.
//
// Charging invariant (load-bearing): ONLY a Python 200 may ever be settled.
//  - MPP: validate (non-mutating) → call Python → settle only if 200.
//  - x402: the foundation middleware verifies before our handler and settles
//    after it only when the handler's response status is < 400.
//  - Unpaid: one 402 carrying BOTH x402 PAYMENT-REQUIRED and MPP
//    WWW-Authenticate. Python is never called.
//
// SDK objects sit behind the small `PaidPayments` interface so tests inject
// fakes; the real InFlow wiring lives in ./paid-payments.ts.
import { isIP } from "node:net";
import { Hono, type Context, type MiddlewareHandler } from "hono";
import {
  PAID_BASE_PATH,
  isPaidEnabled,
  isPaidOp,
  loadPaidConfig,
  type PaidConfig,
  type PaidOp,
  type PaidRoute,
} from "./paid-config";

export const MAX_BODY_BYTES = 16_384;

// ─── SDK seams ────────────────────────────────────────────────────────────

export interface MppPrice {
  amount: string;
  currency: "USDC";
  /** Route path bound into the challenge, so a credential issued for one op
   *  cannot be redeemed on another op with the same price. */
  scope: string;
}

export type MppChargeResult =
  | { status: 402; challenge: Response }
  | { status: 200; withReceipt: (response: Response) => Response };

export interface MppGateway {
  /** Mint a challenge (402) or, when the request carries a valid credential, SETTLE it. */
  charge(price: MppPrice, request: Request): Promise<MppChargeResult>;
  /** Non-mutating pre-check. Throws when the credential is not acceptable. */
  validateCredential(credential: string, price: MppPrice): Promise<{ reference?: string }>;
}

export interface PaidPayments {
  mpp: MppGateway;
  /** Foundation x402 middleware (@x402/hono) covering every paid route. */
  x402: MiddlewareHandler;
}

// ─── Logging (names/ids only — never bodies, PII, or secrets) ─────────────

export type PaidLogEvent =
  | { event: "agent_paid_config_invalid"; problems: string[] }
  | { event: "agent_paid_init_failed"; error: string }
  | { event: "agent_paid_upstream_error"; op: PaidOp; kind: "timeout" | "network" | "status" | "body"; status?: number }
  | { event: "agent_paid_payment_error"; op: PaidOp; protocol: "mpp" | "x402"; stage: string; error: string }
  | {
      event: "agent_paid_reconcile";
      op: PaidOp;
      protocol: "mpp";
      status: "settle_unknown" | "settled_response_failed";
      reference: string | null;
    };

export type PaidLogger = (entry: PaidLogEvent) => void;

export const defaultPaidLogger: PaidLogger = (entry) => {
  const line = JSON.stringify(entry);
  if (entry.event === "agent_paid_reconcile" || entry.event === "agent_paid_config_invalid") {
    console.error(line);
  } else {
    console.warn(line);
  }
};

function errorName(err: unknown): string {
  return err instanceof Error ? err.name : typeof err;
}

// ─── Small pure helpers ───────────────────────────────────────────────────

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export function isJsonContentType(value: string | null | undefined): boolean {
  if (!value) return false;
  return value.split(";")[0].trim().toLowerCase() === "application/json";
}

/**
 * Agent IP for Python's rate-limit key. On Vercel `x-real-ip` is set by the
 * edge and not client-controllable; elsewhere fall back to the first
 * `x-forwarded-for` hop. Anything that is not a literal IP becomes "unknown".
 */
export function extractClientIp(headers: Headers, onVercel: boolean): string {
  const raw = onVercel
    ? headers.get("x-real-ip")
    : headers.get("x-forwarded-for")?.split(",")[0];
  const candidate = raw?.trim() ?? "";
  return candidate && isIP(candidate) !== 0 ? candidate : "unknown";
}

/** Read the body once, enforcing the byte cap on the ACTUAL bytes. `null` = too large. */
export async function readCappedBody(request: Request, cap: number): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!request.body) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > cap) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

// ─── Python forwarding ────────────────────────────────────────────────────

export interface ForwardResult {
  status: number;
  body: unknown;
}

const UPSTREAM_ERROR: ForwardResult = { status: 502, body: { error: "upstream_error" } };
const UNAVAILABLE: ForwardResult = { status: 503, body: { error: "unavailable" } };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export interface ForwardArgs {
  config: PaidConfig;
  route: PaidRoute;
  body: Uint8Array<ArrayBuffer>;
  clientIp: string;
  fetchImpl: typeof fetch;
  log: PaidLogger;
}

/**
 * POST the raw body to the internal Python endpoint. Only status + JSON body
 * come back — Python's headers are never forwarded. Redirects are never
 * followed. The result is normalized to the documented contract so the caller
 * can treat `status === 200` as the one and only chargeable outcome.
 */
export async function forwardToPython(args: ForwardArgs): Promise<ForwardResult> {
  const { config, route, body, clientIp, fetchImpl, log } = args;
  let res: Response;
  try {
    res = await fetchImpl(`${config.beamApiBase}${route.pythonPath}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-beam-internal-secret": config.internalSecret,
        "x-beam-client-ip": clientIp,
      },
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(route.timeoutMs),
    });
  } catch (err) {
    const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    log({ event: "agent_paid_upstream_error", op: route.op, kind: timedOut ? "timeout" : "network" });
    return UPSTREAM_ERROR;
  }

  let parsed: unknown;
  try {
    parsed = await res.json();
  } catch {
    log({ event: "agent_paid_upstream_error", op: route.op, kind: "body", status: res.status });
    return UPSTREAM_ERROR;
  }

  switch (res.status) {
    case 200:
      return { status: 200, body: parsed };
    case 404:
      if (isRecord(parsed) && parsed.error === "no_match") {
        return { status: 404, body: { error: "no_match" } };
      }
      // Python's dormant gate (flag off / secret mismatch) is a plain 404 —
      // that is a deploy misconfiguration, not a "no match" for the agent.
      log({ event: "agent_paid_upstream_error", op: route.op, kind: "status", status: 404 });
      return UNAVAILABLE;
    case 413:
    case 422:
    case 429:
      return { status: res.status, body: parsed };
    case 502:
      return UPSTREAM_ERROR;
    case 503:
      return UNAVAILABLE;
    default:
      // 3xx (redirect: "manual"), 400, 5xx, anything off-contract.
      log({ event: "agent_paid_upstream_error", op: route.op, kind: "status", status: res.status });
      return UPSTREAM_ERROR;
  }
}

// ─── App ──────────────────────────────────────────────────────────────────

export interface PaidAppDeps {
  getPayments: (config: PaidConfig) => Promise<PaidPayments>;
  env?: Readonly<Record<string, string | undefined>>;
  fetchImpl?: typeof fetch;
  log?: PaidLogger;
}

const NOT_FOUND = { error: "not_found" };

export function createPaidApp(deps: PaidAppDeps): Hono {
  const app = new Hono().basePath(PAID_BASE_PATH);
  const log = deps.log ?? defaultPaidLogger;
  const env = (): Readonly<Record<string, string | undefined>> => deps.env ?? process.env;

  // Flag gate first: while dormant, every /api/paid path is indistinguishable
  // from an unknown route.
  app.use("*", async (c, next) => {
    if (!isPaidEnabled(env())) return jsonResponse(404, NOT_FOUND);
    await next();
  });

  app.post("/:op", async (c) => {
    const op = c.req.param("op");
    if (!isPaidOp(op)) return jsonResponse(404, NOT_FOUND);
    return handlePaidRequest(c, op, {
      env: env(),
      getPayments: deps.getPayments,
      fetchImpl: deps.fetchImpl ?? fetch,
      log,
    });
  });

  app.all("*", () => jsonResponse(404, NOT_FOUND));
  app.notFound(() => jsonResponse(404, NOT_FOUND));
  app.onError(() => jsonResponse(503, { error: "unavailable" }));
  return app;
}

interface RequestDeps {
  env: Readonly<Record<string, string | undefined>>;
  getPayments: (config: PaidConfig) => Promise<PaidPayments>;
  fetchImpl: typeof fetch;
  log: PaidLogger;
}

export async function handlePaidRequest(c: Context, op: PaidOp, deps: RequestDeps): Promise<Response> {
  const { log } = deps;
  const loaded = loadPaidConfig(deps.env);
  if (!loaded.ok) {
    log({ event: "agent_paid_config_invalid", problems: loaded.problems });
    return jsonResponse(503, { error: "unavailable" });
  }
  const config = loaded.config;
  const route = config.routes[op];

  // Cheap rejections before ANY payment work.
  if (!isJsonContentType(c.req.header("content-type"))) {
    return jsonResponse(415, { error: "unsupported_media_type" });
  }
  const declared = c.req.header("content-length");
  if (declared !== undefined) {
    if (!/^\d+$/.test(declared.trim())) return jsonResponse(400, { error: "invalid_content_length" });
    if (Number(declared) > MAX_BODY_BYTES) return jsonResponse(413, { error: "payload_too_large" });
  }
  const body = await readCappedBody(c.req.raw, MAX_BODY_BYTES);
  if (body === null) return jsonResponse(413, { error: "payload_too_large" });

  let payments: PaidPayments;
  try {
    payments = await deps.getPayments(config);
  } catch (err) {
    log({ event: "agent_paid_init_failed", error: errorName(err) });
    return jsonResponse(503, { error: "unavailable" });
  }

  const original = c.req.raw;
  // The raw body was consumed above; SDKs get fresh copies built from the bytes.
  const rebuild = (keepAuthorization: boolean): Request => {
    const headers = new Headers(original.headers);
    if (!keepAuthorization) headers.delete("authorization");
    return new Request(original.url, { method: original.method, headers, body });
  };
  const clientIp = extractClientIp(original.headers, deps.env.VERCEL === "1");
  const forward = () =>
    forwardToPython({ config, route, body, clientIp, fetchImpl: deps.fetchImpl, log });
  const price: MppPrice = { amount: route.price, currency: "USDC", scope: route.path };

  const authorization = c.req.header("authorization");
  if (authorization && /^payment\s+/i.test(authorization)) {
    // mppx's Credential.deserialize requires the full "Payment <base64>" header
    // value; passing only the base64 part throws MissingPaymentSchemeError.
    const credential = authorization.trim();
    return runMppFlow({ credential, price, route, mpp: payments.mpp, rebuild, forward, log });
  }

  const hasX402Payment =
    c.req.header("payment-signature") !== undefined || c.req.header("x-payment") !== undefined;
  if (hasX402Payment) {
    return runX402Flow(c, payments.x402, forward);
  }
  return runUnpaidFlow(c, { price, route, payments, rebuild, log });
}

// ─── MPP ──────────────────────────────────────────────────────────────────

interface MppFlowArgs {
  credential: string;
  price: MppPrice;
  route: PaidRoute;
  mpp: MppGateway;
  rebuild: (keepAuthorization: boolean) => Request;
  forward: () => Promise<ForwardResult>;
  log: PaidLogger;
}

export async function runMppFlow(args: MppFlowArgs): Promise<Response> {
  const { credential, price, route, mpp, rebuild, forward, log } = args;

  let reference: string | null = null;
  try {
    const validation = await mpp.validateCredential(credential, price);
    reference = validation.reference ?? null;
  } catch (err) {
    log({ event: "agent_paid_payment_error", op: route.op, protocol: "mpp", stage: "validate", error: errorName(err) });
    return freshMppChallenge(mpp, price, rebuild, route, log);
  }

  const upstream = await forward();
  if (upstream.status !== 200) {
    // Not chargeable — the credential is never broadcast.
    return jsonResponse(upstream.status, upstream.body);
  }

  let settled: MppChargeResult;
  try {
    settled = await mpp.charge(price, rebuild(true));
  } catch (err) {
    // Broadcast outcome unknown: the agent may or may not have been charged.
    log({ event: "agent_paid_reconcile", op: route.op, protocol: "mpp", status: "settle_unknown", reference });
    log({ event: "agent_paid_payment_error", op: route.op, protocol: "mpp", stage: "settle", error: errorName(err) });
    return jsonResponse(502, { error: "payment_settlement_failed" });
  }
  if (settled.status === 402) {
    // Settlement refused → the result is NOT released.
    return settled.challenge;
  }
  try {
    return settled.withReceipt(jsonResponse(200, upstream.body));
  } catch {
    // Paid but the receipt could not be attached: still deliver what was paid for.
    log({ event: "agent_paid_reconcile", op: route.op, protocol: "mpp", status: "settled_response_failed", reference });
    return jsonResponse(200, upstream.body);
  }
}

/** A challenge minted from a request WITHOUT the credential, so it can never settle. */
async function freshMppChallenge(
  mpp: MppGateway,
  price: MppPrice,
  rebuild: (keepAuthorization: boolean) => Request,
  route: PaidRoute,
  log: PaidLogger,
): Promise<Response> {
  try {
    const result = await mpp.charge(price, rebuild(false));
    if (result.status === 402) return result.challenge;
  } catch (err) {
    log({ event: "agent_paid_payment_error", op: route.op, protocol: "mpp", stage: "challenge", error: errorName(err) });
  }
  return jsonResponse(402, { error: "invalid_payment" });
}

// ─── x402 ─────────────────────────────────────────────────────────────────

async function runX402Flow(
  c: Context,
  x402: MiddlewareHandler,
  forward: () => Promise<ForwardResult>,
): Promise<Response> {
  // The middleware RETURNS its own 402/502 responses; on the verified path it
  // runs `next`, then settles only when our status is < 400.
  const returned = await x402(c, async () => {
    const upstream = await forward();
    c.res = jsonResponse(upstream.status, upstream.body);
  });
  return returned instanceof Response ? returned : c.res;
}

// ─── Unpaid ───────────────────────────────────────────────────────────────

interface UnpaidArgs {
  price: MppPrice;
  route: PaidRoute;
  payments: PaidPayments;
  rebuild: (keepAuthorization: boolean) => Request;
  log: PaidLogger;
}

async function runUnpaidFlow(c: Context, args: UnpaidArgs): Promise<Response> {
  const { price, route, payments, rebuild, log } = args;

  // `next` must never run for an unpaid request: if it does, the x402 route
  // table does not cover this path and we refuse rather than serve for free.
  let nextCalled = false;
  const returned = await payments.x402(c, async () => {
    nextCalled = true;
  });
  if (nextCalled) {
    log({ event: "agent_paid_payment_error", op: route.op, protocol: "x402", stage: "unprotected_route", error: "next_called" });
    return jsonResponse(503, { error: "unavailable" });
  }
  const x402Res = returned instanceof Response ? returned : c.res;
  if (x402Res.status !== 402) return x402Res;

  let mppChallenge: string | null = null;
  try {
    const result = await payments.mpp.charge(price, rebuild(false));
    if (result.status === 402) mppChallenge = result.challenge.headers.get("www-authenticate");
  } catch (err) {
    log({ event: "agent_paid_payment_error", op: route.op, protocol: "mpp", stage: "challenge", error: errorName(err) });
  }
  if (!mppChallenge) return x402Res;

  const merged = new Response(x402Res.body, x402Res);
  merged.headers.append("www-authenticate", mppChallenge);
  return merged;
}
