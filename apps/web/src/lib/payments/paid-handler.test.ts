import { describe, it, expect, vi } from "vitest";
import type { MiddlewareHandler } from "hono";
import {
  createPaidApp,
  extractClientIp,
  readCappedBody,
  MAX_BODY_BYTES,
  type MppGateway,
  type MppChargeResult,
  type MppPrice,
  type PaidLogEvent,
  type PaidPayments,
} from "./paid-handler";

// Charging invariant under test: ONLY a Python 200 is ever settled; an unpaid
// request never reaches Python. All SDKs and Python are fakes — no network.

const FAKE_INFLOW_KEY = "test-inflow-key-not-real";
const FAKE_INTERNAL_SECRET = "test-internal-secret-not-real";
const FAKE_MPP_SECRET = "m".repeat(32);

const ENV: Record<string, string> = {
  AGENT_PAID_ENABLED: "true",
  INFLOW_API_KEY: FAKE_INFLOW_KEY,
  INFLOW_ENVIRONMENT: "sandbox",
  MPP_SECRET_KEY: FAKE_MPP_SECRET,
  BEAM_API_BASE: "http://python.test/",
  INTERNAL_PAID_API_SECRET: FAKE_INTERNAL_SECRET,
};

const URL_BASE = "http://beam.test/api/paid";

// ─── Fakes ───────────────────────────────────────────────────────────────

interface FakeMppOptions {
  valid?: boolean;
  settle?: "ok" | "refuse" | "throw";
  receiptThrows?: boolean;
}

function fakeMpp(opts: FakeMppOptions = {}) {
  const { valid = true, settle = "ok", receiptThrows = false } = opts;
  const state = {
    validateCalls: 0,
    chargeCalls: 0,
    settleAttempts: 0,
    settled: 0,
    prices: [] as MppPrice[],
    credentials: [] as string[],
  };
  const challenge = () =>
    new Response(null, { status: 402, headers: { "www-authenticate": 'Payment id="mpp-challenge"' } });
  const gateway: MppGateway = {
    async validateCredential(credential, price) {
      state.validateCalls++;
      state.prices.push(price);
      state.credentials.push(credential);
      if (!valid) throw new Error("invalid credential");
      return { reference: "chal_123" };
    },
    async charge(price, request): Promise<MppChargeResult> {
      state.chargeCalls++;
      state.prices.push(price);
      if (!request.headers.get("authorization")) return { status: 402, challenge: challenge() };
      state.settleAttempts++;
      if (settle === "throw") throw new Error("broadcast failed");
      if (settle === "refuse") return { status: 402, challenge: challenge() };
      state.settled++;
      return {
        status: 200,
        withReceipt: (res: Response) => {
          if (receiptThrows) throw new Error("receipt failed");
          const out = new Response(res.body, res);
          out.headers.set("payment-receipt", "receipt-abc");
          return out;
        },
      };
    },
  };
  return { gateway, state };
}

function fakeX402() {
  const state = { invoked: 0, settled: 0, cancelled: 0 };
  const middleware: MiddlewareHandler = async (c, next) => {
    state.invoked++;
    const signature = c.req.header("payment-signature");
    if (!signature || signature === "bad") {
      return new Response("{}", {
        status: 402,
        headers: { "content-type": "application/json", "payment-required": "x402-requirements" },
      });
    }
    await next();
    if (c.res.status >= 400) {
      state.cancelled++;
      return;
    }
    state.settled++;
    const res = new Response(c.res.body, c.res);
    res.headers.set("payment-response", "x402-settled");
    c.res = res;
  };
  return { middleware, state };
}

interface PythonReply {
  status: number;
  body?: unknown;
  headers?: Record<string, string>;
}

function fakePython(reply: PythonReply | (() => Promise<Response>) = { status: 200, body: { domain: "acme.com" } }) {
  const fetchImpl = vi.fn<(url: string | URL | Request, init?: RequestInit) => Promise<Response>>(async () => {
    if (typeof reply === "function") return reply();
    return new Response(reply.body === undefined ? "" : JSON.stringify(reply.body), {
      status: reply.status,
      headers: { "content-type": "application/json", ...(reply.headers ?? {}) },
    });
  });
  return fetchImpl;
}

interface SetupOptions {
  env?: Record<string, string | undefined>;
  mpp?: FakeMppOptions;
  python?: Parameters<typeof fakePython>[0];
  getPayments?: () => Promise<PaidPayments>;
}

function setup(opts: SetupOptions = {}) {
  const mpp = fakeMpp(opts.mpp);
  const x402 = fakeX402();
  const fetchImpl = fakePython(opts.python);
  const logs: PaidLogEvent[] = [];
  const getPayments = vi.fn(opts.getPayments ?? (async () => ({ mpp: mpp.gateway, x402: x402.middleware })));
  const app = createPaidApp({
    env: opts.env ?? ENV,
    getPayments,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    log: (e) => logs.push(e),
  });
  return { app, mpp, x402, fetchImpl, logs, getPayments };
}

function post(
  app: ReturnType<typeof setup>["app"],
  op: string,
  init: { body?: string; headers?: Record<string, string> } = {},
) {
  return app.request(`${URL_BASE}/${op}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    body: init.body ?? JSON.stringify({ ip: "203.0.113.9" }),
  });
}

const MPP_AUTH = { authorization: "Payment eyJjcmVkZW50aWFsIjoidGVzdCJ9" };
const X402_AUTH = { "payment-signature": "good" };

// ─── Gates ───────────────────────────────────────────────────────────────

describe("feature flag and config gates", () => {
  it.each([undefined, "false", "1", "TRUE"])("AGENT_PAID_ENABLED=%s → 404 on every path", async (flag) => {
    const { app, fetchImpl, getPayments } = setup({ env: { ...ENV, AGENT_PAID_ENABLED: flag } });
    expect((await post(app, "ip-company")).status).toBe(404);
    expect((await app.request(`${URL_BASE}/whatever`)).status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(getPayments).not.toHaveBeenCalled();
  });

  it("unknown op, GET, and bare base path → 404 JSON", async () => {
    const { app } = setup();
    for (const res of [
      await post(app, "not-an-op"),
      await app.request(`${URL_BASE}/ip-company`),
      await app.request(URL_BASE, { method: "POST" }),
    ]) {
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ error: "not_found" });
    }
  });

  it("enabled but missing config → 503 with names logged, never values", async () => {
    const { app, logs, fetchImpl } = setup({
      env: { ...ENV, INFLOW_API_KEY: undefined, INFLOW_ENVIRONMENT: undefined },
    });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(503);
    const text = await res.text();
    expect(JSON.parse(text)).toEqual({ error: "unavailable" });
    for (const secret of [FAKE_INTERNAL_SECRET, FAKE_MPP_SECRET, FAKE_INFLOW_KEY]) {
      expect(text).not.toContain(secret);
      expect(JSON.stringify(logs)).not.toContain(secret);
    }
    expect(logs).toContainEqual({
      event: "agent_paid_config_invalid",
      problems: ["INFLOW_API_KEY", "INFLOW_ENVIRONMENT"],
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("payments init failure → 503, and a later request retries init", async () => {
    let attempt = 0;
    const mpp = fakeMpp();
    const x402 = fakeX402();
    const { app, getPayments } = setup({
      getPayments: async () => {
        attempt++;
        if (attempt === 1) throw new Error(`boom ${FAKE_INFLOW_KEY}`);
        return { mpp: mpp.gateway, x402: x402.middleware };
      },
    });
    const first = await post(app, "ip-company");
    expect(first.status).toBe(503);
    expect(await first.text()).not.toContain(FAKE_INFLOW_KEY);
    const second = await post(app, "ip-company");
    expect(second.status).toBe(402);
    expect(getPayments).toHaveBeenCalledTimes(2);
  });

  it("wrong content-type → 415 before any payment work", async () => {
    const { app, getPayments } = setup();
    const res = await post(app, "ip-company", { headers: { "content-type": "text/plain" } });
    expect(res.status).toBe(415);
    expect(getPayments).not.toHaveBeenCalled();
  });

  it("accepts application/json with charset", async () => {
    const { app } = setup();
    const res = await post(app, "ip-company", { headers: { "content-type": "application/json; charset=utf-8" } });
    expect(res.status).toBe(402);
  });

  it("declared Content-Length over cap → 413 before any payment work", async () => {
    const { app, getPayments } = setup();
    const res = await post(app, "ip-company", { headers: { "content-length": String(MAX_BODY_BYTES + 1) } });
    expect(res.status).toBe(413);
    expect(getPayments).not.toHaveBeenCalled();
  });

  it("actual body over cap (no Content-Length) → 413 before any payment work", async () => {
    const { app, getPayments } = setup();
    const res = await post(app, "ip-company", { body: JSON.stringify({ ip: "x".repeat(MAX_BODY_BYTES) }) });
    expect(res.status).toBe(413);
    expect(getPayments).not.toHaveBeenCalled();
  });
});

// ─── Unpaid ──────────────────────────────────────────────────────────────

describe("unpaid request", () => {
  it("→ ONE 402 with x402 PAYMENT-REQUIRED and MPP WWW-Authenticate; Python not called", async () => {
    const { app, fetchImpl, mpp, x402 } = setup();
    const res = await post(app, "ip-company");
    expect(res.status).toBe(402);
    expect(res.headers.get("payment-required")).toBe("x402-requirements");
    expect(res.headers.get("www-authenticate")).toContain("Payment");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(x402.state.invoked).toBe(1);
    expect(mpp.state.settleAttempts).toBe(0);
  });

  it("refuses (503) and never calls Python if x402 lets the request through unpaid", async () => {
    const mpp = fakeMpp();
    const passthrough: MiddlewareHandler = async (_c, next) => {
      await next();
    };
    const { app, fetchImpl } = setup({ getPayments: async () => ({ mpp: mpp.gateway, x402: passthrough }) });
    const res = await post(app, "ip-company");
    expect(res.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

// ─── MPP ─────────────────────────────────────────────────────────────────

describe("MPP flow", () => {
  it("invalid credential → 402 challenge, Python NOT called, never settled", async () => {
    const { app, fetchImpl, mpp } = setup({ mpp: { valid: false } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(402);
    expect(res.headers.get("www-authenticate")).toContain("Payment");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(mpp.state.settleAttempts).toBe(0);
  });

  it("valid + Python 200 → settled once, receipt attached, result returned", async () => {
    const { app, fetchImpl, mpp } = setup({ python: { status: 200, body: { domain: "acme.com" } } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ domain: "acme.com" });
    expect(res.headers.get("payment-receipt")).toBe("receipt-abc");
    expect(mpp.state.validateCalls).toBe(1);
    expect(mpp.state.settleAttempts).toBe(1);
    expect(mpp.state.settled).toBe(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("passes the full 'Payment <credential>' header value to validate (mppx requires the scheme)", async () => {
    const { app, mpp } = setup({ python: { status: 200, body: { domain: "acme.com" } } });
    await post(app, "ip-company", { headers: { authorization: "  Payment eyJjcmVkZW50aWFsIjoidGVzdCJ9  " } });
    expect(mpp.state.credentials).toEqual(["Payment eyJjcmVkZW50aWFsIjoidGVzdCJ9"]);
  });

  it("binds validate and settle to the route scope and price", async () => {
    const { app, mpp } = setup({ python: { status: 200, body: { draft: "hi" } } });
    const res = await post(app, "outreach-draft", { headers: MPP_AUTH });
    expect(res.status).toBe(200);
    expect(mpp.state.prices).toEqual([
      { amount: "0.05", currency: "USDC", scope: "/api/paid/outreach-draft" },
      { amount: "0.05", currency: "USDC", scope: "/api/paid/outreach-draft" },
    ]);
  });

  it.each([
    [404, { error: "no_match" }, 404, { error: "no_match" }],
    [422, { detail: [{ loc: ["body", "ip"], msg: "bad", type: "value_error" }] }, 422, null],
    [502, { error: "upstream_error" }, 502, { error: "upstream_error" }],
    [503, { error: "unavailable" }, 503, { error: "unavailable" }],
    [429, { error: "rate_limited" }, 429, { error: "rate_limited" }],
  ])("valid + Python %i → NOT charged, status passed through", async (pyStatus, pyBody, status, body) => {
    const { app, mpp } = setup({ python: { status: pyStatus, body: pyBody } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(status);
    expect(await res.json()).toEqual(body ?? pyBody);
    expect(mpp.state.settleAttempts).toBe(0);
    expect(mpp.state.chargeCalls).toBe(0);
  });

  it("valid + Python 200 + settlement refused (402) → result NOT returned", async () => {
    const { app, mpp } = setup({ mpp: { settle: "refuse" }, python: { status: 200, body: { domain: "secret-result.com" } } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(402);
    expect(await res.text()).not.toContain("secret-result.com");
    expect(mpp.state.settled).toBe(0);
  });

  it("settlement throws → 502, result NOT returned, reconcile logged", async () => {
    const { app, logs } = setup({ mpp: { settle: "throw" }, python: { status: 200, body: { domain: "secret-result.com" } } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(502);
    expect(await res.text()).not.toContain("secret-result.com");
    expect(logs).toContainEqual({
      event: "agent_paid_reconcile",
      op: "ip-company",
      protocol: "mpp",
      status: "settle_unknown",
      reference: "chal_123",
    });
  });

  it("settled but receipt attach throws → still 200, reconcile logged without body/PII", async () => {
    const { app, logs } = setup({ mpp: { receiptThrows: true } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(200);
    const reconcile = logs.find((l) => l.event === "agent_paid_reconcile");
    expect(reconcile).toEqual({
      event: "agent_paid_reconcile",
      op: "ip-company",
      protocol: "mpp",
      status: "settled_response_failed",
      reference: "chal_123",
    });
    expect(JSON.stringify(logs)).not.toContain("203.0.113.9");
  });
});

// ─── x402 ────────────────────────────────────────────────────────────────

describe("x402 flow", () => {
  it("Python 200 → middleware settles, result returned", async () => {
    const { app, x402 } = setup();
    const res = await post(app, "ip-company", { headers: X402_AUTH });
    expect(res.status).toBe(200);
    expect(res.headers.get("payment-response")).toBe("x402-settled");
    expect(x402.state.settled).toBe(1);
  });

  it("Python 404 no_match → handler status ≥ 400, NO settlement", async () => {
    const { app, x402, fetchImpl } = setup({ python: { status: 404, body: { error: "no_match" } } });
    const res = await post(app, "ip-company", { headers: X402_AUTH });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "no_match" });
    expect(x402.state.invoked).toBe(1);
    expect(x402.state.settled).toBe(0);
    expect(x402.state.cancelled).toBe(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("invalid x402 payment → middleware's 402, Python NOT called", async () => {
    const { app, fetchImpl } = setup();
    const res = await post(app, "ip-company", { headers: { "payment-signature": "bad" } });
    expect(res.status).toBe(402);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

// ─── Python forwarding ───────────────────────────────────────────────────

describe("Python forwarding", () => {
  it("sends secret + client IP, raw body, manual redirect, timeout signal", async () => {
    const { app, fetchImpl } = setup();
    await post(app, "deep-research", {
      headers: { ...MPP_AUTH, "x-forwarded-for": "198.51.100.7, 10.0.0.1" },
      body: JSON.stringify({ full_name: "Ada" }),
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://python.test/internal/v1/paid/deep-research");
    const headers = new Headers(init?.headers);
    expect(headers.get("x-beam-internal-secret")).toBe(FAKE_INTERNAL_SECRET);
    expect(headers.get("x-beam-client-ip")).toBe("198.51.100.7");
    expect(headers.get("authorization")).toBeNull();
    expect(init?.redirect).toBe("manual");
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(new TextDecoder().decode(init?.body as Uint8Array)).toBe(JSON.stringify({ full_name: "Ada" }));
  });

  it("always sends X-Beam-Client-IP (unknown when absent)", async () => {
    const { app, fetchImpl } = setup();
    await post(app, "ip-company", { headers: MPP_AUTH });
    const init = fetchImpl.mock.calls[0][1];
    expect(new Headers(init?.headers).get("x-beam-client-ip")).toBe("unknown");
  });

  it("never forwards Python response headers or leaks the secret", async () => {
    const { app } = setup({
      python: { status: 200, body: { domain: "acme.com" }, headers: { "set-cookie": "a=b", "x-internal": "1" } },
    });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("x-internal")).toBeNull();
    expect(await res.text()).not.toContain(FAKE_INTERNAL_SECRET);
  });

  it("redirect from Python → 502, not charged", async () => {
    const { app, mpp } = setup({ python: { status: 302, body: {}, headers: { location: "http://evil.test" } } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(502);
    expect(mpp.state.settleAttempts).toBe(0);
  });

  it("timeout → 502 upstream_error, not charged", async () => {
    const { app, mpp, logs } = setup({
      python: async () => {
        throw Object.assign(new Error("timed out"), { name: "TimeoutError" });
      },
    });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "upstream_error" });
    expect(mpp.state.settleAttempts).toBe(0);
    expect(logs).toContainEqual({ event: "agent_paid_upstream_error", op: "ip-company", kind: "timeout" });
  });

  it("Python gate 404 (not no_match) → 503, not charged", async () => {
    const { app, mpp } = setup({ python: { status: 404, body: { detail: "Not Found" } } });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(503);
    expect(mpp.state.settleAttempts).toBe(0);
  });

  it("non-JSON Python 200 → 502, not charged", async () => {
    const { app, mpp } = setup({ python: async () => new Response("<html>", { status: 200 }) });
    const res = await post(app, "ip-company", { headers: MPP_AUTH });
    expect(res.status).toBe(502);
    expect(mpp.state.settleAttempts).toBe(0);
  });
});

// ─── Helpers ─────────────────────────────────────────────────────────────

describe("extractClientIp", () => {
  const h = (init: Record<string, string>) => new Headers(init);

  it.each([
    [{ "x-real-ip": "203.0.113.5" }, true, "203.0.113.5"],
    [{ "x-real-ip": "2001:db8::1" }, true, "2001:db8::1"],
    [{ "x-real-ip": "not-an-ip", "x-forwarded-for": "198.51.100.1" }, true, "unknown"],
    [{ "x-forwarded-for": "198.51.100.1" }, true, "unknown"],
    [{ "x-forwarded-for": " 198.51.100.1 , 10.0.0.1" }, false, "198.51.100.1"],
    [{ "x-forwarded-for": "evil, 10.0.0.1" }, false, "unknown"],
    [{ "x-real-ip": "203.0.113.5" }, false, "unknown"],
    [{}, false, "unknown"],
  ])("%j (vercel=%s) → %s", (headers, onVercel, expected) => {
    expect(extractClientIp(h(headers), onVercel)).toBe(expected);
  });

  it("uses x-real-ip when VERCEL=1", async () => {
    const { app, fetchImpl } = setup({ env: { ...ENV, VERCEL: "1" } });
    await post(app, "ip-company", {
      headers: { ...MPP_AUTH, "x-real-ip": "203.0.113.77", "x-forwarded-for": "1.1.1.1" },
    });
    expect(new Headers(fetchImpl.mock.calls[0][1]?.headers).get("x-beam-client-ip")).toBe("203.0.113.77");
  });
});

describe("readCappedBody", () => {
  function streamRequest(chunks: string[]): Request {
    const enc = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(enc.encode(c));
        controller.close();
      },
    });
    return new Request("http://x.test", { method: "POST", body, duplex: "half" } as RequestInit);
  }

  it("returns the bytes under the cap", async () => {
    const out = await readCappedBody(streamRequest(["ab", "cd"]), 4);
    expect(new TextDecoder().decode(out ?? new Uint8Array())).toBe("abcd");
  });

  it("returns null once streamed bytes exceed the cap", async () => {
    expect(await readCappedBody(streamRequest(["ab", "cde"]), 4)).toBeNull();
  });
});
