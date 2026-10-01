// Reseller BUY handler: Beam pays Locus Apollo people-enrichment per call via
// InFlow (x402 or MPP), on behalf of apps/api. Server-to-server only.
//
// Fail-safe invariants (load-bearing):
//  - The price cap is enforced on the seller's offers BEFORE any payment object
//    is created. Unknown assets/decimals are never paid.
//  - Only InFlow-managed signing; an offer InFlow cannot sign → no_payable_offer.
//  - At most ONE paid replay per request, never a protocol fallback after a
//    payment attempt started (no double pay).
//  - Pending approval / timeout / decline → 402 payment_pending_or_declined
//    within a short budget; a request is never parked for minutes.
//  - Reveal flags are always forced false; only whitelisted fields go out.
//  - Upstream headers are never forwarded; logs carry ids/status only.
import { createHash, timingSafeEqual } from "node:crypto";
import { Hono } from "hono";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import type { PaymentRequired } from "@x402/core/types";
import { Challenge, Receipt } from "mppx";
import { BUY_BASE_PATH, isBuyEnabled, loadBuyConfig, type BuyConfig } from "./buy-config";
import type { BuyClients, InflowClient, MppCredentialMaker } from "./buy-clients";
import { isJsonContentType, jsonResponse, readCappedBody } from "./paid-handler";

export const BUY_MAX_BODY_BYTES = 4_096;
const UPSTREAM_MAX_BODY_BYTES = 262_144;

/** Whole-request budget, kept under apps/api's 30 s client timeout. */
export const DEFAULT_DEADLINE_MS = 27_000;
/** Max time from "start creating a payment" to "credential in hand". */
export const DEFAULT_PAYMENT_TIMEOUT_MS = 20_000;
const PROBE_TIMEOUT_MS = 5_000;
/** Minimum budget that must remain for the paid replay before we start paying. */
const REPLAY_RESERVE_MS = 5_000;
const MIN_PAYMENT_BUDGET_MS = 2_000;

export const APOLLO_INPUT_FIELDS = [
  "email",
  "first_name",
  "last_name",
  "domain",
  "linkedin_url",
  "organization_name",
] as const;
type ApolloInputField = (typeof APOLLO_INPUT_FIELDS)[number];
const MAX_FIELD_CHARS = 320;

export type BuyProtocol = "x402" | "mpp";

// ─── Logging (names/ids/status only) ─────────────────────────────────────

export type BuyLogEvent =
  | { event: "reseller_config_invalid"; problems: string[] }
  | { event: "reseller_payment_error"; protocol: BuyProtocol; stage: string; error: string }
  | { event: "reseller_upstream_error"; protocol: BuyProtocol | "probe"; kind: "timeout" | "network" | "body"; status?: number }
  | {
      event: "reseller_reconcile";
      op: "apollo-person";
      protocol: BuyProtocol;
      transaction: string | null;
      status: number | null;
      paid: boolean | null;
    };

export type BuyLogger = (entry: BuyLogEvent) => void;

export const defaultBuyLogger: BuyLogger = (entry) => {
  const line = JSON.stringify(entry);
  if (entry.event === "reseller_reconcile" || entry.event === "reseller_config_invalid") console.error(line);
  else console.warn(line);
};

function errorName(err: unknown): string {
  return err instanceof Error ? err.name : typeof err;
}

// ─── Pure helpers ────────────────────────────────────────────────────────

/** Constant-time secret check over fixed-length digests (length never leaks). */
export function secretMatches(provided: string | undefined, expected: string): boolean {
  if (!provided || !expected) return false;
  const a = createHash("sha256").update(provided).digest();
  const b = createHash("sha256").update(expected).digest();
  return timingSafeEqual(a, b);
}

/** Exact decimal → atomic units. `null` when not a plain decimal or too precise. */
export function decimalToAtomic(value: string, decimals: number): bigint | null {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return null;
  const fraction = match[2] ?? "";
  if (fraction.length > decimals && /[1-9]/.test(fraction.slice(decimals))) return null;
  const padded = `${fraction}${"0".repeat(decimals)}`.slice(0, decimals);
  return BigInt(`${match[1]}${padded}`);
}

export function atomicToDecimal(atomic: bigint, decimals: number): string {
  const digits = atomic.toString().padStart(decimals + 1, "0");
  const whole = digits.slice(0, digits.length - decimals);
  const fraction = digits.slice(digits.length - decimals).replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole;
}

/**
 * x402 assets whose decimals we KNOW (all USD stablecoins). Key: `network|asset`
 * lower-cased. Anything else is treated as unpayable rather than guessed.
 *  - Base mainnet USDC (Locus Apollo offer)
 *  - Base Sepolia USDC (InFlow Sandbox exact offer)
 *  - InFlow ledger `balance` on inflow:1 names the currency, not a contract;
 *    the seller SDK prices it in the payment method's decimals (6 for USDC —
 *    Sandbox offered 20000 for $0.02, plan task 40).
 */
const X402_USD_ASSET_DECIMALS: Readonly<Record<string, number>> = {
  "eip155:8453|0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,
  "eip155:84532|0x036cbd53842c5426634e7929541ec2318f3dcf7e": 6,
  "inflow:1|usdc": 6,
};

/** Tempo TIP-20 currencies we know to be USD stablecoins with 6 decimals. */
const TEMPO_USD_CURRENCY_DECIMALS: Readonly<Record<string, number>> = {
  // Locus Apollo MPP challenge currency (amount 38000 == $0.038).
  "0x20c000000000000000000000b9537d11c60e8b50": 6,
};

/** InFlow `inflow` method charges carry a DECIMAL amount in these currencies. */
const INFLOW_USD_CURRENCIES = new Set(["USDC", "USDT", "PYUSD", "USD"]);

type OfferVerdict =
  | { kind: "ok"; atomic: bigint; decimals: number; amountUsd: string }
  | { kind: "over_cap" }
  | { kind: "unknown" };

function verdictFor(atomic: bigint | null, decimals: number | undefined, capUsd: string): OfferVerdict {
  if (atomic === null || decimals === undefined || atomic <= BigInt(0)) return { kind: "unknown" };
  const capAtomic = decimalToAtomic(capUsd, decimals);
  if (capAtomic === null) return { kind: "unknown" };
  if (atomic > capAtomic) return { kind: "over_cap" };
  return { kind: "ok", atomic, decimals, amountUsd: atomicToDecimal(atomic, decimals) };
}

/** Fields we price on; satisfied by both @x402/core and InFlow requirement types. */
export interface X402OfferLike {
  network: string;
  asset: string;
  amount: string;
}

export function priceX402Offer(offer: X402OfferLike, capUsd: string): OfferVerdict {
  const decimals = X402_USD_ASSET_DECIMALS[`${offer.network}|${offer.asset}`.toLowerCase()];
  const atomic = /^\d+$/.test(offer.amount) ? BigInt(offer.amount) : null;
  return verdictFor(atomic, decimals, capUsd);
}

interface MppChallengeLike {
  id: string;
  method: string;
  intent: string;
  request: Record<string, unknown>;
}

export function priceMppChallenge(challenge: MppChallengeLike, capUsd: string): OfferVerdict {
  if (challenge.intent !== "charge") return { kind: "unknown" };
  const amount = challenge.request.amount;
  const currency = challenge.request.currency;
  if (typeof amount !== "string" || typeof currency !== "string") return { kind: "unknown" };
  if (challenge.method === "inflow") {
    // Decimal amount (inflowChargeRequestSchema). Compare at 18 dp, report as given.
    if (!INFLOW_USD_CURRENCIES.has(currency.toUpperCase())) return { kind: "unknown" };
    return verdictFor(decimalToAtomic(amount, 18), 18, capUsd);
  }
  if (challenge.method === "tempo") {
    // Integer atomic amount (tempoChargeRequestSchema).
    const decimals = TEMPO_USD_CURRENCY_DECIMALS[currency.toLowerCase()];
    return verdictFor(/^\d+$/.test(amount) ? BigInt(amount) : null, decimals, capUsd);
  }
  return { kind: "unknown" };
}

export type ApolloInput = Partial<Record<ApolloInputField, string>>;

/** Whitelist + validate the body apps/api sent. `null` = nothing usable. */
export function buildApolloInput(raw: unknown): ApolloInput | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const out: ApolloInput = {};
  for (const field of APOLLO_INPUT_FIELDS) {
    const value = record[field];
    if (value === undefined || value === null) continue;
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) continue;
    if (trimmed.length > MAX_FIELD_CHARS) return null;
    out[field] = trimmed;
  }
  const hasName = Boolean(out.first_name && out.last_name);
  const usable = out.email || out.linkedin_url || out.organization_name || out.domain || hasName;
  return usable ? out : null;
}

/** Outbound body: whitelisted fields + reveal flags FORCED false (privacy + cost). */
export function outboundBody(input: ApolloInput): string {
  return JSON.stringify({ ...input, reveal_personal_emails: false, reveal_phone_number: false });
}

// ─── Upstream I/O ─────────────────────────────────────────────────────────

interface UpstreamResult {
  status: number;
  headers: Headers;
  /** Parsed JSON body, or `undefined` when absent / not JSON / too large. */
  json: unknown;
}

async function readStreamCapped(stream: ReadableStream<Uint8Array> | null, cap: number): Promise<Uint8Array | null> {
  if (!stream) return new Uint8Array(0);
  const reader = stream.getReader();
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

async function callUpstream(
  fetchImpl: typeof fetch,
  url: string,
  body: string,
  extraHeaders: Record<string, string>,
  timeoutMs: number,
): Promise<UpstreamResult> {
  const res = await fetchImpl(url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json", ...extraHeaders },
    body,
    redirect: "manual",
    cache: "no-store",
    signal: AbortSignal.timeout(Math.max(1, timeoutMs)),
  });
  let json: unknown;
  const bytes = await readStreamCapped(res.body, UPSTREAM_MAX_BODY_BYTES);
  if (bytes && bytes.byteLength > 0) {
    try {
      json = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      json = undefined;
    }
  }
  return { status: res.status, headers: res.headers, json };
}

// ─── Flow ─────────────────────────────────────────────────────────────────

type Attempt =
  | { kind: "skip"; reason: "no_payable_offer" | "price_above_cap" }
  | { kind: "done"; response: Response };

interface FlowCtx {
  config: BuyConfig;
  clients: BuyClients;
  body: string;
  fetchImpl: typeof fetch;
  log: BuyLogger;
  deadline: number;
  paymentTimeoutMs: number;
}

const remaining = (ctx: FlowCtx): number => ctx.deadline - Date.now();

/** Payment budget: capped at paymentTimeoutMs and leaves time for the replay. */
function paymentBudget(ctx: FlowCtx): number {
  return Math.min(ctx.paymentTimeoutMs, remaining(ctx) - REPLAY_RESERVE_MS);
}

function skipFromVerdicts(verdicts: OfferVerdict[]): Attempt {
  return {
    kind: "skip",
    reason: verdicts.some((v) => v.kind === "over_cap") ? "price_above_cap" : "no_payable_offer",
  };
}

const PENDING = (): Response => jsonResponse(402, { error: "payment_pending_or_declined" });

async function probe(ctx: FlowCtx, url: string): Promise<UpstreamResult | Response> {
  try {
    return await callUpstream(ctx.fetchImpl, url, ctx.body, {}, Math.min(PROBE_TIMEOUT_MS, remaining(ctx)));
  } catch (err) {
    const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    ctx.log({ event: "reseller_upstream_error", protocol: "probe", kind: timedOut ? "timeout" : "network" });
    return jsonResponse(502, { error: "upstream_error", paid: false });
  }
}

/** Non-402 unpaid answer: pass status + JSON through, nothing was paid. */
function passthrough(result: UpstreamResult, ctx: FlowCtx): Response {
  if (result.json === undefined) {
    ctx.log({ event: "reseller_upstream_error", protocol: "probe", kind: "body", status: result.status });
    return jsonResponse(502, { error: "upstream_error", paid: false });
  }
  return jsonResponse(result.status, result.json);
}

function success(protocol: BuyProtocol, amountUsd: string, transaction: string | null, data: unknown): Response {
  return jsonResponse(200, { provider: "locus_apollo", protocol, amount_usd: amountUsd, transaction, data });
}

function afterPaymentFailure(
  ctx: FlowCtx,
  protocol: BuyProtocol,
  transaction: string | null,
  status: number | null,
  paid: boolean | null,
): Response {
  ctx.log({ event: "reseller_reconcile", op: "apollo-person", protocol, transaction, status, paid });
  return jsonResponse(502, { error: "upstream_error", paid });
}

async function replay(
  ctx: FlowCtx,
  protocol: BuyProtocol,
  url: string,
  headers: Record<string, string>,
): Promise<UpstreamResult | null> {
  try {
    return await callUpstream(ctx.fetchImpl, url, ctx.body, headers, remaining(ctx));
  } catch (err) {
    const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    ctx.log({ event: "reseller_upstream_error", protocol, kind: timedOut ? "timeout" : "network" });
    return null;
  }
}

export async function runX402(ctx: FlowCtx): Promise<Attempt> {
  const url = ctx.config.apolloUrlX402;
  const first = await probe(ctx, url);
  if (first instanceof Response) return { kind: "done", response: first };
  if (first.status !== 402) return { kind: "done", response: passthrough(first, ctx) };

  // Decode + price with NO InFlow call: the cap is enforced before the buyer
  // client is even initialized. x402HTTPClient.getPaymentRequiredResponse
  // reads the same base64-JSON PAYMENT-REQUIRED header (v1 falls back to body).
  let paymentRequired: PaymentRequired;
  try {
    paymentRequired = new x402HTTPClient(new x402Client()).getPaymentRequiredResponse(
      (name) => first.headers.get(name),
      first.json,
    );
  } catch {
    return { kind: "skip", reason: "no_payable_offer" };
  }
  const accepts = Array.isArray(paymentRequired.accepts) ? paymentRequired.accepts : [];

  // Price cap BEFORE any payment object exists.
  const verdicts = accepts.map((offer) => priceX402Offer(offer, ctx.config.maxPriceUsd));
  const affordable = accepts.filter((_, i) => verdicts[i].kind === "ok");
  if (affordable.length === 0) return skipFromVerdicts(verdicts);

  let core: InflowClient;
  try {
    core = await ctx.clients.getX402Client(ctx.config);
  } catch (err) {
    ctx.log({ event: "reseller_payment_error", protocol: "x402", stage: "init", error: errorName(err) });
    return { kind: "done", response: jsonResponse(503, { error: "unavailable" }) };
  }
  const http = new x402HTTPClient(core);

  let selected: Awaited<ReturnType<InflowClient["selectInflowRequirement"]>>;
  try {
    selected = await core.selectInflowRequirement({ ...paymentRequired, accepts: affordable });
  } catch (err) {
    ctx.log({ event: "reseller_payment_error", protocol: "x402", stage: "select", error: errorName(err) });
    selected = null;
  }
  if (!selected) return { kind: "skip", reason: "no_payable_offer" };
  const price = priceX402Offer(selected, ctx.config.maxPriceUsd);
  if (price.kind !== "ok") return { kind: "skip", reason: price.kind === "over_cap" ? "price_above_cap" : "no_payable_offer" };

  const budget = paymentBudget(ctx);
  if (budget < MIN_PAYMENT_BUDGET_MS) return { kind: "done", response: PENDING() };
  const signal = AbortSignal.timeout(budget);

  let prepared: Awaited<ReturnType<InflowClient["prepareInflowPayment"]>>;
  try {
    prepared = await core.prepareInflowPayment(
      selected,
      { resource: paymentRequired.resource, x402Version: paymentRequired.x402Version },
      { signal },
    );
  } catch (err) {
    ctx.log({ event: "reseller_payment_error", protocol: "x402", stage: "prepare", error: errorName(err) });
    if (err instanceof Error && err.name === "X402AdapterRoutingError") return { kind: "skip", reason: "no_payable_offer" };
    return { kind: "done", response: PENDING() };
  }

  let payment: Awaited<ReturnType<typeof prepared.awaitPayload>>;
  try {
    payment = await prepared.awaitPayload({ timeoutMs: budget, signal });
  } catch (err) {
    // Pending approval / declined / timeout: release the approval, never wait longer.
    void prepared.cancel();
    ctx.log({ event: "reseller_payment_error", protocol: "x402", stage: "await", error: errorName(err) });
    return { kind: "done", response: PENDING() };
  }

  // The SDK documents encodedPayload as the exact PAYMENT-SIGNATURE value
  // (server-produced base64, never re-encoded). v1 sellers use X-PAYMENT.
  const headerName = payment.paymentPayload.x402Version === 1 ? "X-PAYMENT" : "PAYMENT-SIGNATURE";
  const paid = await replay(ctx, "x402", url, { [headerName]: payment.encodedPayload });
  const fallbackTx = payment.transactionId ?? prepared.transactionId ?? null;
  if (!paid) return { kind: "done", response: afterPaymentFailure(ctx, "x402", fallbackTx, null, null) };

  let settled: { success: boolean; transaction?: string } | undefined;
  try {
    settled = http.getPaymentSettleResponse((name) => paid.headers.get(name));
  } catch {
    settled = undefined;
  }
  const transaction = settled?.transaction || fallbackTx;
  if (paid.status >= 200 && paid.status < 300 && paid.json !== undefined) {
    return { kind: "done", response: success("x402", price.amountUsd, transaction, paid.json) };
  }
  const paidFlag = settled ? settled.success : paid.status === 402 ? false : null;
  return { kind: "done", response: afterPaymentFailure(ctx, "x402", transaction, paid.status, paidFlag) };
}

const LOCUS_REQUEST_ID_RE = /^[A-Za-z0-9-]{8,128}$/;

export async function runMpp(ctx: FlowCtx): Promise<Attempt> {
  const url = ctx.config.apolloUrlMpp;
  const first = await probe(ctx, url);
  if (first instanceof Response) return { kind: "done", response: first };
  if (first.status !== 402) return { kind: "done", response: passthrough(first, ctx) };

  const wwwAuthenticate = first.headers.get("www-authenticate");
  if (!wwwAuthenticate) return { kind: "skip", reason: "no_payable_offer" };
  // Only the WWW-Authenticate header goes to mppx: its HTTP transport also
  // parses x402 PAYMENT-REQUIRED, which we never want to pay through MPP.
  const challengeResponse = new Response(null, { status: 402, headers: { "www-authenticate": wwwAuthenticate } });

  let challenges: MppChallengeLike[];
  try {
    challenges = Challenge.fromResponseList(challengeResponse) as MppChallengeLike[];
  } catch {
    return { kind: "skip", reason: "no_payable_offer" };
  }
  const verdicts = challenges.map((c) => priceMppChallenge(c, ctx.config.maxPriceUsd));
  // Prefer InFlow's native method, then tempo.
  const order = (method: string) => (method === "inflow" ? 0 : 1);
  const candidates = challenges
    .map((challenge, i) => ({ challenge, verdict: verdicts[i] }))
    .filter((c) => c.verdict.kind === "ok")
    .sort((a, b) => order(a.challenge.method) - order(b.challenge.method));
  const chosen = candidates[0];
  if (!chosen || chosen.verdict.kind !== "ok") return skipFromVerdicts(verdicts);
  const amountUsd = chosen.verdict.amountUsd;

  const budget = paymentBudget(ctx);
  if (budget < MIN_PAYMENT_BUDGET_MS) return { kind: "done", response: PENDING() };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), budget);

  let credential: string;
  try {
    const maker: MppCredentialMaker = ctx.clients.createMppMaker(ctx.config, budget);
    credential = await maker.createCredential(challengeResponse, chosen.challenge.id, controller.signal);
  } catch (err) {
    ctx.log({ event: "reseller_payment_error", protocol: "mpp", stage: "credential", error: errorName(err) });
    if (err instanceof Error && err.message.startsWith("No method found for challenges")) {
      return { kind: "skip", reason: "no_payable_offer" };
    }
    return { kind: "done", response: PENDING() };
  } finally {
    clearTimeout(timer);
  }

  // mppx's Credential.serialize returns the FULL header value "Payment <b64url>";
  // send it verbatim (stripping the scheme broke the Seller side once).
  const headers: Record<string, string> = { authorization: credential };
  const requestId = first.headers.get("x-locus-request-id")?.trim();
  if (requestId && LOCUS_REQUEST_ID_RE.test(requestId)) headers["x-locus-request-id"] = requestId;

  const paid = await replay(ctx, "mpp", url, headers);
  if (!paid) return { kind: "done", response: afterPaymentFailure(ctx, "mpp", null, null, null) };

  let transaction: string | null = null;
  const receiptHeader = paid.headers.get("payment-receipt");
  if (receiptHeader) {
    try {
      transaction = Receipt.deserialize(receiptHeader).reference ?? null;
    } catch {
      transaction = null;
    }
  }
  if (paid.status >= 200 && paid.status < 300 && paid.json !== undefined) {
    return { kind: "done", response: success("mpp", amountUsd, transaction, paid.json) };
  }
  const paidFlag = receiptHeader ? true : paid.status === 402 ? false : null;
  return { kind: "done", response: afterPaymentFailure(ctx, "mpp", transaction, paid.status, paidFlag) };
}

// ─── App ──────────────────────────────────────────────────────────────────

export interface BuyAppDeps {
  getClients: () => BuyClients;
  env?: Readonly<Record<string, string | undefined>>;
  /** Upstream (reseller) fetch. Defaults to the platform fetch, never patched. */
  fetchImpl?: typeof fetch;
  log?: BuyLogger;
  deadlineMs?: number;
  paymentTimeoutMs?: number;
}

const NOT_FOUND = { error: "not_found" };

export function createBuyApp(deps: BuyAppDeps): Hono {
  const app = new Hono().basePath(BUY_BASE_PATH);
  const log = deps.log ?? defaultBuyLogger;
  const env = (): Readonly<Record<string, string | undefined>> => deps.env ?? process.env;

  app.use("*", async (c, next) => {
    const current = env();
    if (!isBuyEnabled(current)) return jsonResponse(404, NOT_FOUND);
    // Wrong/missing secret is indistinguishable from an unknown route.
    const expected = current.INTERNAL_PAID_API_SECRET?.trim() ?? "";
    if (!secretMatches(c.req.header("x-beam-internal-secret"), expected)) return jsonResponse(404, NOT_FOUND);
    await next();
  });

  app.post("/apollo-person", async (c) => {
    const started = Date.now();
    if (!isJsonContentType(c.req.header("content-type"))) {
      return jsonResponse(415, { error: "unsupported_media_type" });
    }
    const declared = c.req.header("content-length");
    if (declared !== undefined && /^\d+$/.test(declared.trim()) && Number(declared) > BUY_MAX_BODY_BYTES) {
      return jsonResponse(413, { error: "payload_too_large" });
    }
    const bytes = await readCappedBody(c.req.raw, BUY_MAX_BODY_BYTES);
    if (bytes === null) return jsonResponse(413, { error: "payload_too_large" });
    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return jsonResponse(400, { error: "invalid_json" });
    }
    const input = buildApolloInput(parsed);
    if (!input) return jsonResponse(422, { error: "invalid_input" });

    const loaded = loadBuyConfig(env());
    if (!loaded.ok) {
      log({ event: "reseller_config_invalid", problems: loaded.problems });
      return jsonResponse(503, { error: "unavailable" });
    }

    const ctx: FlowCtx = {
      config: loaded.config,
      clients: deps.getClients(),
      body: outboundBody(input),
      fetchImpl: deps.fetchImpl ?? fetch,
      log,
      deadline: started + (deps.deadlineMs ?? DEFAULT_DEADLINE_MS),
      paymentTimeoutMs: deps.paymentTimeoutMs ?? DEFAULT_PAYMENT_TIMEOUT_MS,
    };

    const order: BuyProtocol[] =
      ctx.config.protocol === "auto" ? ["x402", "mpp"] : [ctx.config.protocol];
    let sawOverCap = false;
    for (const protocol of order) {
      const attempt = protocol === "x402" ? await runX402(ctx) : await runMpp(ctx);
      if (attempt.kind === "done") return attempt.response;
      if (attempt.reason === "price_above_cap") sawOverCap = true;
    }
    return jsonResponse(402, { error: sawOverCap ? "price_above_cap" : "no_payable_offer" });
  });

  app.all("*", () => jsonResponse(404, NOT_FOUND));
  app.notFound(() => jsonResponse(404, NOT_FOUND));
  app.onError(() => jsonResponse(503, { error: "unavailable" }));
  return app;
}
