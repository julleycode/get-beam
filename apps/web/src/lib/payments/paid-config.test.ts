import { describe, it, expect } from "vitest";
import { isPaidEnabled, isPositiveDecimal, loadPaidConfig } from "./paid-config";

const ENV: Record<string, string> = {
  INFLOW_API_KEY: "test-inflow-key-not-real",
  INFLOW_ENVIRONMENT: "sandbox",
  MPP_SECRET_KEY: "m".repeat(32),
  BEAM_API_BASE: "https://api.example.test/",
  INTERNAL_PAID_API_SECRET: "test-internal-secret-not-real",
};

describe("isPaidEnabled", () => {
  it("is true only for exactly 'true'", () => {
    expect(isPaidEnabled({ AGENT_PAID_ENABLED: "true" })).toBe(true);
    for (const v of [undefined, "", "1", "TRUE", "yes"]) {
      expect(isPaidEnabled({ AGENT_PAID_ENABLED: v })).toBe(false);
    }
  });
});

describe("loadPaidConfig", () => {
  it("builds the route table with default prices and timeouts", () => {
    const result = loadPaidConfig(ENV);
    if (!result.ok) throw new Error(result.problems.join(","));
    const { config } = result;
    expect(config.beamApiBase).toBe("https://api.example.test");
    expect(config.routes["enrich-email"]).toEqual({
      op: "enrich-email",
      path: "/api/paid/enrich-email",
      pythonPath: "/internal/v1/paid/enrich-email",
      price: "0.05",
      timeoutMs: 30_000,
    });
    expect(config.routes["ip-company"].price).toBe("0.02");
    expect(config.routes["deep-research"]).toMatchObject({ price: "0.25", timeoutMs: 60_000 });
    expect(config.routes["outreach-draft"].price).toBe("0.05");
  });

  it("honours price overrides", () => {
    const result = loadPaidConfig({ ...ENV, PAID_PRICE_IP_COMPANY: "0.1" });
    expect(result.ok && result.config.routes["ip-company"].price).toBe("0.1");
  });

  it("INFLOW_ENVIRONMENT has no default (SDK default is production)", () => {
    const result = loadPaidConfig({ ...ENV, INFLOW_ENVIRONMENT: undefined });
    expect(result).toEqual({ ok: false, problems: ["INFLOW_ENVIRONMENT"] });
    expect(loadPaidConfig({ ...ENV, INFLOW_ENVIRONMENT: "prod" }).ok).toBe(false);
  });

  it("reports every problem by NAME only", () => {
    const result = loadPaidConfig({
      MPP_SECRET_KEY: "short",
      BEAM_API_BASE: "ftp://nope",
      PAID_PRICE_DEEP_RESEARCH: "-1",
    });
    expect(result).toEqual({
      ok: false,
      problems: [
        "INFLOW_API_KEY",
        "INTERNAL_PAID_API_SECRET",
        "INFLOW_ENVIRONMENT",
        "MPP_SECRET_KEY",
        "BEAM_API_BASE",
        "PAID_PRICE_DEEP_RESEARCH",
      ],
    });
    expect(JSON.stringify(result)).not.toContain("short");
  });

  it("MPP_SECRET_KEY needs >= 32 bytes", () => {
    expect(loadPaidConfig({ ...ENV, MPP_SECRET_KEY: "m".repeat(31) }).ok).toBe(false);
    expect(loadPaidConfig({ ...ENV, MPP_SECRET_KEY: "m".repeat(32) }).ok).toBe(true);
  });
});

describe("isPositiveDecimal", () => {
  it.each(["0.05", "1", "10.12345678"])("accepts %s", (v) => expect(isPositiveDecimal(v)).toBe(true));
  it.each(["0", "0.0", "-1", "1e3", "abc", "", "0.123456789", ".5"])("rejects %s", (v) =>
    expect(isPositiveDecimal(v)).toBe(false),
  );
});
