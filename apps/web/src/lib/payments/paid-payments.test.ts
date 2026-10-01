import { describe, it, expect, vi, beforeEach } from "vitest";

// All SDK modules are mocked — no InFlow/network calls.
const sdk = vi.hoisted(() => ({
  createInflowSellerClient: vi.fn(),
  initialize: vi.fn(),
  paymentMiddlewareFromHTTPServer: vi.fn(),
  mppxCreate: vi.fn(),
}));

vi.mock("@inflowpayai/x402-seller", () => ({
  createInflowFacilitator: vi.fn(() => ({})),
  createInflowSellerClient: sdk.createInflowSellerClient,
  inflowAccepts: vi.fn(async (_seller: unknown, opts: { price: string }) => [{ price: opts.price }]),
  inflowSchemeRegistrations: vi.fn(async () => [{ network: "eip155:1", server: {} }]),
}));

vi.mock("@x402/hono", () => ({
  x402ResourceServer: class {
    register = vi.fn();
  },
  x402HTTPResourceServer: class {
    routes: unknown;
    constructor(_server: unknown, routes: unknown) {
      this.routes = routes;
    }
    initialize = sdk.initialize;
  },
  paymentMiddlewareFromHTTPServer: sdk.paymentMiddlewareFromHTTPServer,
}));

vi.mock("@inflowpayai/mpp-seller", () => ({
  Mppx: { create: sdk.mppxCreate },
  inflow: vi.fn(() => ({})),
}));

import { loadPaidConfig } from "./paid-config";

function config() {
  const result = loadPaidConfig({
    INFLOW_API_KEY: "test-inflow-key-not-real",
    INFLOW_ENVIRONMENT: "sandbox",
    MPP_SECRET_KEY: "m".repeat(32),
    BEAM_API_BASE: "https://api.example.test",
    INTERNAL_PAID_API_SECRET: "test-internal-secret-not-real",
  });
  if (!result.ok) throw new Error("bad test config");
  return result.config;
}

describe("getPaidPayments", () => {
  beforeEach(() => {
    vi.resetModules();
    sdk.createInflowSellerClient.mockReset().mockResolvedValue({});
    sdk.initialize.mockReset().mockResolvedValue(undefined);
    sdk.paymentMiddlewareFromHTTPServer.mockReset().mockReturnValue(async () => undefined);
    sdk.mppxCreate.mockReset().mockReturnValue({ charge: vi.fn(), validateCredential: vi.fn() });
  });

  it("initializes x402 itself and disables the SDK's background init (process.exit path)", async () => {
    const { getPaidPayments } = await import("./paid-payments");
    await getPaidPayments(config());
    expect(sdk.initialize).toHaveBeenCalledTimes(1);
    const [httpServer, , , syncOnStart] = sdk.paymentMiddlewareFromHTTPServer.mock.calls[0];
    expect(syncOnStart).toBe(false);
    expect(Object.keys((httpServer as { routes: Record<string, unknown> }).routes)).toEqual([
      "POST /api/paid/enrich-email",
      "POST /api/paid/ip-company",
      "POST /api/paid/deep-research",
      "POST /api/paid/outreach-draft",
    ]);
  });

  it("caches the instance but resets after a failure so the next call retries", async () => {
    const { getPaidPayments } = await import("./paid-payments");
    sdk.initialize.mockRejectedValueOnce(new Error("facilitator down"));
    await expect(getPaidPayments(config())).rejects.toThrow("facilitator down");
    const first = await getPaidPayments(config());
    const second = await getPaidPayments(config());
    expect(first).toBe(second);
    expect(sdk.initialize).toHaveBeenCalledTimes(2);
  });
});
