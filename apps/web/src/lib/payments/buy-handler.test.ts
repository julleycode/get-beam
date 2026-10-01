import { describe, it, expect } from "vitest";
import { encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { Challenge, Credential, Receipt } from "mppx";
import {
  createBuyApp,
  decimalToAtomic,
  atomicToDecimal,
  priceMppChallenge,
  priceX402Offer,
  BUY_MAX_BODY_BYTES,
  type BuyLogEvent,
} from "./buy-handler";
import { createBuyClients } from "./buy-clients";

// The REAL InFlow buyer SDKs (@inflowpayai/x402-buyer, @inflowpayai/mpp-buyer,
// mppx, @x402/core) run in every test. Only the network is faked:
//  - `inflowApi`: a fake InFlow API, wire shapes taken from the SDK sources
//    (x402-buyer dist/index.js:118-122,187-197,366-374; mpp dist/index.js:36-47,
//    333-357; mpp-buyer dist/index.js:91-205).
//  - `locus`: a fake reseller, using the real x402/MPP header encoders.
// No request ever leaves the process.

const FAKE_SECRET = "test-internal-secret-not-real";
const FAKE_INFLOW_KEY = "test-inflow-key-not-real";
const INFLOW_BASE = "https://sandbox.inflowpay.ai";
const X402_URL = "https://apollo.x402.paywithlocus.com/apollo/people-enrichment";
const MPP_URL = "https://apollo.mpp.paywithlocus.com/apollo/people-enrichment";
const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const TEMPO_CURRENCY = "0x20c000000000000000000000b9537d11c60e8b50";
const EMAIL = "jane.doe@acme-test.example";
const LOCUS_REQUEST_ID = "6f9c2b1e-3a4d-4f5e-9b8c-7d6e5f4a3b2c";

const ENV: Record<string, string> = {
  RESELLER_BUY_ENABLED: "true",
  INTERNAL_PAID_API_SECRET: FAKE_SECRET,
  INFLOW_API_KEY: FAKE_INFLOW_KEY,
  INFLOW_ENVIRONMENT: "sandbox",
};

const PERSON = { person: { name: "Jane Doe", title: "VP Sales", organization: { name: "Acme" } } };

// ─── Fake reseller (Locus) ───────────────────────────────────────────────

interface LocusOptions {
  x402Amount?: string;
  x402Network?: string;
  mppAmount?: string;
  mppMethod?: string;
  /** Status for a request WITHOUT payment headers (default 402). */
  unpaidStatus?: number;
  /** Status for the paid replay (default 200). */
  paidStatus?: number;
}

interface Recorded {
  url: string;
  headers: Headers;
  body: string;
}

const PAY_TO = "0x1111111111111111111111111111111111111111";

function x402Accepts(opts: LocusOptions) {
  return {
    scheme: "exact",
    network: opts.x402Network ?? "eip155:8453",
    asset: BASE_USDC,
    amount: opts.x402Amount ?? "38000",
    payTo: PAY_TO,
    maxTimeoutSeconds: 60,
    extra: { name: "USD Coin", version: "2" },
  };
}

function mppChallengeHeader(opts: LocusOptions): string {
  const method = opts.mppMethod ?? "tempo";
  const request =
    method === "inflow"
      ? { amount: opts.mppAmount ?? "0.038", currency: "USDC" }
      : { amount: opts.mppAmount ?? "38000", currency: TEMPO_CURRENCY, recipient: PAY_TO };
  return Challenge.serialize(
    Challenge.from({
      id: "locus-challenge-1",
      realm: "apollo.mpp.paywithlocus.com",
      method,
      intent: "charge",
      request,
      expires: new Date(Date.now() + 5 * 60_000).toISOString(),
    }),
  );
}

function fakeLocus(opts: LocusOptions = {}) {
  const calls: Recorded[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    calls.push({ url, headers, body: String(init?.body ?? "") });
    const paidX402 = headers.has("payment-signature") || headers.has("x-payment");
    const paidMpp = headers.has("authorization");
    if (!paidX402 && !paidMpp) {
      const status = opts.unpaidStatus ?? 402;
      if (status !== 402) return Response.json({ error: "no_records" }, { status });
      if (url === X402_URL) {
        const header = encodePaymentRequiredHeader({
          x402Version: 2,
          resource: { url: X402_URL, description: "Apollo person enrichment", mimeType: "application/json" },
          accepts: [x402Accepts(opts)],
        } as Parameters<typeof encodePaymentRequiredHeader>[0]);
        return new Response("{}", {
          status: 402,
          headers: { "payment-required": header, "content-type": "application/json" },
        });
      }
      return new Response("{}", {
        status: 402,
        headers: {
          "www-authenticate": mppChallengeHeader(opts),
          "x-locus-request-id": LOCUS_REQUEST_ID,
          "content-type": "application/json",
        },
      });
    }
    const status = opts.paidStatus ?? 200;
    const out = new Headers({ "content-type": "application/json", "set-cookie": "upstream=secret" });
    if (status < 400 && paidX402) {
      out.set(
        "payment-response",
        encodePaymentResponseHeader({ success: true, transaction: "0xsettledtx", network: "eip155:8453" }),
      );
    }
    if (status < 400 && paidMpp) {
      out.set(
        "payment-receipt",
        Receipt.serialize(
          Receipt.from({ method: "tempo", status: "success", reference: "0xmpptx", timestamp: new Date().toISOString() }),
        ),
      );
    }
    return new Response(JSON.stringify(status < 400 ? PERSON : { error: "boom" }), { status, headers: out });
  };
  return { fetchImpl, calls };
}

// ─── Fake InFlow API ─────────────────────────────────────────────────────

interface InflowOptions {
  x402Kinds?: { scheme: string; network: string }[];
  x402Pending?: boolean;
  mppPending?: boolean;
}

const ENCODED_X402_PAYLOAD = Buffer.from(JSON.stringify({ x402Version: 2, payload: { sig: "0xabc" } })).toString("base64");

function fakeInflow(opts: InflowOptions = {}) {
  const calls: { method: string; path: string; apiKey: string | null; body: unknown }[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    expect(url.origin).toBe(INFLOW_BASE); // environment: "sandbox" honored
    const headers = new Headers(init?.headers);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, apiKey: headers.get("x-api-key"), body });
    const json = (value: unknown) => Response.json(value);

    if (method === "GET" && url.pathname === "/v1/transactions/x402-supported") {
      return json({ kinds: (opts.x402Kinds ?? [{ scheme: "exact", network: "eip155:8453" }]).map((k) => ({ x402Version: 2, ...k })) });
    }
    if (method === "POST" && url.pathname === "/v1/transactions/x402") {
      return json({ transactionId: "inflow-tx-1", approvalId: "approval-1", approvalStatus: opts.x402Pending ? "INITIATED" : "APPROVED" });
    }
    if (method === "GET" && url.pathname === "/v1/transactions/inflow-tx-1/x402") {
      if (opts.x402Pending) return json({ status: "INITIATED" });
      return json({
        status: "APPROVED",
        encodedPayload: ENCODED_X402_PAYLOAD,
        paymentPayload: { x402Version: 2, accepted: {}, payload: { sig: "0xabc" } },
      });
    }
    if (method === "POST" && url.pathname === "/v1/transactions/mpp") {
      if (opts.mppPending) {
        return json({ state: "pending", transactionId: "inflow-mtx-1", approvalId: "approval-m1", retryAfterSeconds: 1 });
      }
      const challenge = (body as { challenge: Record<string, string> }).challenge;
      const credential = Buffer.from(
        JSON.stringify({ challenge, payload: { type: "hash", hash: "0xfeed", transactionId: "inflow-mtx-1" } }),
      ).toString("base64url");
      return json({ state: "ready", transactionId: "inflow-mtx-1", credential });
    }
    if (method === "GET" && url.pathname === "/v1/transactions/inflow-mtx-1/mpp") {
      return json({ state: "pending", transactionId: "inflow-mtx-1", approvalId: "approval-m1", retryAfterSeconds: 1 });
    }
    if (method === "POST" && url.pathname.startsWith("/v1/approvals/")) return json({});
    return Response.json({ error: "unexpected" }, { status: 500 });
  };
  return { fetchImpl, calls };
}

// ─── Harness ─────────────────────────────────────────────────────────────

interface Harness {
  locus?: LocusOptions;
  inflow?: InflowOptions;
  env?: Record<string, string>;
  paymentTimeoutMs?: number;
}

function harness(h: Harness = {}) {
  const locus = fakeLocus(h.locus);
  const inflow = fakeInflow(h.inflow);
  const logs: BuyLogEvent[] = [];
  const clients = createBuyClients(inflow.fetchImpl);
  const app = createBuyApp({
    getClients: () => clients,
    env: { ...ENV, ...h.env },
    fetchImpl: locus.fetchImpl,
    log: (e) => logs.push(e),
    paymentTimeoutMs: h.paymentTimeoutMs ?? 2_500,
  });
  return { app, locus, inflow, logs };
}

function post(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://beam.test/api/internal/buy/apollo-person", {
    method: "POST",
    headers: { "content-type": "application/json", "x-beam-internal-secret": FAKE_SECRET, ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const paymentPosts = <T extends { method: string; path: string }>(calls: T[]): T[] =>
  calls.filter((c) => c.method === "POST" && /^\/v1\/transactions\/(x402|mpp)$/.test(c.path));

// ─── Gates ───────────────────────────────────────────────────────────────

describe("buy route gates", () => {
  it("is 404 when the flag is off, without touching upstream", async () => {
    const h = harness({ env: { RESELLER_BUY_ENABLED: "false" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(404);
    expect(h.locus.calls).toHaveLength(0);
  });

  it.each([undefined, "wrong-secret"])("is 404 with secret %s", async (secret) => {
    const h = harness();
    const req = new Request("http://beam.test/api/internal/buy/apollo-person", {
      method: "POST",
      headers: { "content-type": "application/json", ...(secret ? { "x-beam-internal-secret": secret } : {}) },
      body: JSON.stringify({ email: EMAIL }),
    });
    expect((await h.app.request(req)).status).toBe(404);
    expect(h.locus.calls).toHaveLength(0);
  });

  it("is 404 for unknown paths and non-POST", async () => {
    const h = harness();
    const res = await h.app.request(
      new Request("http://beam.test/api/internal/buy/other", { method: "POST", headers: { "x-beam-internal-secret": FAKE_SECRET } }),
    );
    expect(res.status).toBe(404);
  });

  it("rejects non-JSON (415), oversized body (413) and unusable input (422)", async () => {
    const h = harness();
    expect((await h.app.request(post("x", { "content-type": "text/plain" }))).status).toBe(415);
    const big = JSON.stringify({ email: EMAIL, pad: "x".repeat(BUY_MAX_BODY_BYTES) });
    expect((await h.app.request(post(big))).status).toBe(413);
    expect((await h.app.request(post({ foo: "bar" }))).status).toBe(422);
    expect((await h.app.request(post({ first_name: "Jane" }))).status).toBe(422);
    expect(h.locus.calls).toHaveLength(0);
  });

  it("is 503 (names-only log) when INFLOW_ENVIRONMENT is missing", async () => {
    const h = harness({ env: { INFLOW_ENVIRONMENT: "" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(503);
    expect(h.logs).toEqual([{ event: "reseller_config_invalid", problems: ["INFLOW_ENVIRONMENT"] }]);
  });
});

// ─── Flows ───────────────────────────────────────────────────────────────

describe("buy route payment flows", () => {
  it("passes a non-402 upstream answer through without paying", async () => {
    const h = harness({ locus: { unpaidStatus: 404 } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "no_records" });
    expect(h.inflow.calls).toHaveLength(0);
  });

  it("whitelists fields and FORCES reveal flags false on every outbound request", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "x402" } });
    const res = await h.app.request(
      post({ email: EMAIL, domain: "acme-test.example", reveal_phone_number: true, reveal_personal_emails: true, id: "x", extra: 1 }),
    );
    expect(res.status).toBe(200);
    expect(h.locus.calls).toHaveLength(2);
    for (const call of h.locus.calls) {
      expect(JSON.parse(call.body)).toEqual({
        email: EMAIL,
        domain: "acme-test.example",
        reveal_personal_emails: false,
        reveal_phone_number: false,
      });
    }
  });

  it("refuses an offer above RESELLER_MAX_PRICE_USD before creating any payment", async () => {
    const h = harness({ locus: { x402Amount: "50001", mppAmount: "50001" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(402);
    expect(await res.json()).toEqual({ error: "price_above_cap" });
    // Not even the buyer client is initialized, let alone a transaction.
    expect(h.inflow.calls).toHaveLength(0);
    expect(h.locus.calls.every((c) => !c.headers.has("authorization") && !c.headers.has("payment-signature"))).toBe(true);
  });

  it("honors a lower configured cap", async () => {
    const h = harness({ env: { RESELLER_MAX_PRICE_USD: "0.01", RESELLER_PROTOCOL: "x402" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(await res.json()).toEqual({ error: "price_above_cap" });
    expect(paymentPosts(h.inflow.calls)).toHaveLength(0);
  });

  it("returns no_payable_offer when InFlow cannot sign the offered network", async () => {
    const h = harness({
      env: { RESELLER_PROTOCOL: "x402" },
      inflow: { x402Kinds: [{ scheme: "exact", network: "eip155:84532" }] },
    });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(402);
    expect(await res.json()).toEqual({ error: "no_payable_offer" });
    expect(paymentPosts(h.inflow.calls)).toHaveLength(0);
  });

  it("treats an unknown MPP method as unpayable", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "mpp" }, locus: { mppMethod: "stripe" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(await res.json()).toEqual({ error: "no_payable_offer" });
    expect(h.inflow.calls).toHaveLength(0);
  });

  it("x402 success: replays once with PAYMENT-SIGNATURE = InFlow's encodedPayload verbatim", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "x402" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      provider: "locus_apollo",
      protocol: "x402",
      amount_usd: "0.038",
      transaction: "0xsettledtx",
      data: PERSON,
    });
    // Upstream headers are never forwarded.
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("payment-response")).toBeNull();

    expect(h.locus.calls).toHaveLength(2);
    const replay = h.locus.calls[1];
    expect(replay.url).toBe(X402_URL);
    expect(replay.headers.get("payment-signature")).toBe(ENCODED_X402_PAYLOAD); // no scheme prefix, not re-encoded
    expect(replay.headers.get("authorization")).toBeNull();
    expect(replay.body).toBe(h.locus.calls[0].body);

    // InFlow: API key header, then exactly one transaction for the Locus offer.
    expect(h.inflow.calls.every((c) => c.apiKey === FAKE_INFLOW_KEY)).toBe(true);
    const tx = paymentPosts(h.inflow.calls);
    expect(tx).toHaveLength(1);
    const txBody = tx[0].body as { accept: { network: string; amount: string; asset: string }; x402Version: number };
    expect(txBody.accept).toMatchObject({ network: "eip155:8453", amount: "38000", asset: BASE_USDC });
    expect(txBody.x402Version).toBe(2);
  });

  it("x402 pending approval → 402 payment_pending_or_declined, approval cancelled, no paid replay", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "x402" }, inflow: { x402Pending: true } });
    const started = Date.now();
    const res = await h.app.request(post({ email: EMAIL }));
    expect(Date.now() - started).toBeLessThan(10_000);
    expect(res.status).toBe(402);
    expect(await res.json()).toEqual({ error: "payment_pending_or_declined" });
    expect(h.locus.calls).toHaveLength(1);
    await new Promise((r) => setTimeout(r, 10));
    expect(h.inflow.calls.some((c) => c.method === "POST" && c.path === "/v1/approvals/approval-1/cancel")).toBe(true);
  });

  it("MPP success: Authorization is the full 'Payment <b64url>' credential and the Locus request id is echoed", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "mpp" } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      provider: "locus_apollo",
      protocol: "mpp",
      amount_usd: "0.038",
      transaction: "0xmpptx",
      data: PERSON,
    });
    expect(h.locus.calls).toHaveLength(2);
    const replay = h.locus.calls[1];
    expect(replay.url).toBe(MPP_URL);
    const authorization = replay.headers.get("authorization") ?? "";
    expect(authorization).toMatch(/^Payment [A-Za-z0-9_-]+$/);
    const credential = Credential.deserialize(authorization); // throws MissingPaymentSchemeError if prefix lost
    expect(credential.challenge.id).toBe("locus-challenge-1");
    expect(credential.challenge.method).toBe("tempo");
    expect(replay.headers.get("x-locus-request-id")).toBe(LOCUS_REQUEST_ID);
    expect(replay.headers.get("payment-signature")).toBeNull();
    expect(paymentPosts(h.inflow.calls)).toHaveLength(1);
  });

  it("MPP pending approval → 402 payment_pending_or_declined, approval cancelled", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "mpp" }, inflow: { mppPending: true } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(402);
    expect(await res.json()).toEqual({ error: "payment_pending_or_declined" });
    expect(h.locus.calls).toHaveLength(1);
    await new Promise((r) => setTimeout(r, 10));
    expect(h.inflow.calls.some((c) => c.method === "POST" && c.path === "/v1/approvals/approval-m1/cancel")).toBe(true);
  });

  it("auto: x402 unpayable falls back to MPP (no payment was attempted on x402)", async () => {
    const h = harness({ inflow: { x402Kinds: [{ scheme: "balance", network: "inflow:1" }] } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(200);
    expect((await res.json()).protocol).toBe("mpp");
    expect(paymentPosts(h.inflow.calls).map((c) => c.path)).toEqual(["/v1/transactions/mpp"]);
  });

  it("upstream 5xx after payment → 502 + reconcile log without PII, never a second payment", async () => {
    const h = harness({ env: { RESELLER_PROTOCOL: "x402" }, locus: { paidStatus: 500 } });
    const res = await h.app.request(post({ email: EMAIL }));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "upstream_error", paid: null });
    expect(paymentPosts(h.inflow.calls)).toHaveLength(1);
    expect(h.locus.calls).toHaveLength(2);
    const reconcile = h.logs.filter((l) => l.event === "reseller_reconcile");
    expect(reconcile).toEqual([
      { event: "reseller_reconcile", op: "apollo-person", protocol: "x402", transaction: "inflow-tx-1", status: 500, paid: null },
    ]);
    const serialized = JSON.stringify(h.logs);
    expect(serialized).not.toContain(EMAIL);
    expect(serialized).not.toContain(FAKE_SECRET);
    expect(serialized).not.toContain(FAKE_INFLOW_KEY);
  });

  it("never patches globalThis.fetch", async () => {
    const before = globalThis.fetch;
    const clients = createBuyClients(fakeInflow().fetchImpl);
    const config = {
      inflowApiKey: FAKE_INFLOW_KEY,
      inflowEnvironment: "sandbox" as const,
      internalSecret: FAKE_SECRET,
      apolloUrlX402: X402_URL,
      apolloUrlMpp: MPP_URL,
      protocol: "auto" as const,
      maxPriceUsd: "0.05",
    };
    clients.createMppMaker(config, 1_000);
    await clients.getX402Client(config);
    const h = harness({ env: { RESELLER_PROTOCOL: "mpp" } });
    await h.app.request(post({ email: EMAIL }));
    expect(globalThis.fetch).toBe(before);
  });
});

// ─── Pure pricing ────────────────────────────────────────────────────────

describe("pricing helpers", () => {
  it("converts decimals exactly", () => {
    expect(decimalToAtomic("0.05", 6)).toBe(BigInt(50000));
    expect(decimalToAtomic("0.0500", 6)).toBe(BigInt(50000));
    expect(decimalToAtomic("0.0000001", 6)).toBeNull();
    expect(decimalToAtomic("-1", 6)).toBeNull();
    expect(atomicToDecimal(BigInt(38000), 6)).toBe("0.038");
    expect(atomicToDecimal(BigInt(1_000_000), 6)).toBe("1");
  });

  it("prices only assets with known decimals", () => {
    const base = { network: "eip155:8453", asset: BASE_USDC, amount: "38000" };
    expect(priceX402Offer(base, "0.05")).toMatchObject({ kind: "ok", amountUsd: "0.038" });
    expect(priceX402Offer({ ...base, amount: "50001" }, "0.05")).toEqual({ kind: "over_cap" });
    expect(priceX402Offer({ ...base, asset: "0xdeadbeef" }, "0.05")).toEqual({ kind: "unknown" });
    expect(priceX402Offer({ network: "inflow:1", asset: "USDC", amount: "50000" }, "0.05")).toMatchObject({ kind: "ok" });
  });

  it("prices MPP inflow (decimal) and tempo (atomic) charges", () => {
    const inflowCh = { id: "a", method: "inflow", intent: "charge", request: { amount: "0.05", currency: "USDC" } };
    expect(priceMppChallenge(inflowCh, "0.05")).toMatchObject({ kind: "ok", amountUsd: "0.05" });
    expect(priceMppChallenge({ ...inflowCh, request: { amount: "0.06", currency: "USDC" } }, "0.05")).toEqual({ kind: "over_cap" });
    expect(priceMppChallenge({ ...inflowCh, request: { amount: "0.01", currency: "EUR" } }, "0.05")).toEqual({ kind: "unknown" });
    const tempoCh = { id: "b", method: "tempo", intent: "charge", request: { amount: "318000", currency: TEMPO_CURRENCY } };
    expect(priceMppChallenge(tempoCh, "0.05")).toEqual({ kind: "over_cap" }); // phone-reveal price is refused
    expect(priceMppChallenge({ ...tempoCh, intent: "subscription" }, "0.05")).toEqual({ kind: "unknown" });
  });
});
