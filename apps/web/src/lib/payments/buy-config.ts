// Reseller BUY configuration (server-only).
//
// Beam pays a third-party reseller (Locus Apollo people-enrichment) per call via
// InFlow, over x402 or MPP. The internal route /api/internal/buy/* is called
// server-to-server by apps/api only. Env is read LAZILY (per request) so a
// missing variable can only produce a 503 on that route — never a build break.
import { isPositiveDecimal, type InflowEnvironment } from "./paid-config";

if (typeof window !== "undefined") {
  throw new Error("buy-config is server-only");
}

export const BUY_BASE_PATH = "/api/internal/buy";

export const DEFAULT_APOLLO_URL_X402 = "https://apollo.x402.paywithlocus.com/apollo/people-enrichment";
export const DEFAULT_APOLLO_URL_MPP = "https://apollo.mpp.paywithlocus.com/apollo/people-enrichment";
export const DEFAULT_MAX_PRICE_USD = "0.05";

export type ResellerProtocolSetting = "x402" | "mpp" | "auto";

export interface BuyConfig {
  inflowApiKey: string;
  inflowEnvironment: InflowEnvironment;
  internalSecret: string;
  apolloUrlX402: string;
  apolloUrlMpp: string;
  protocol: ResellerProtocolSetting;
  /** USD decimal string, e.g. "0.05". Offers above it are never paid. */
  maxPriceUsd: string;
}

export type BuyConfigResult =
  | { ok: true; config: BuyConfig }
  /** `problems` holds env VARIABLE NAMES only — never values. */
  | { ok: false; problems: string[] };

type Env = Readonly<Record<string, string | undefined>>;

/** RESELLER_BUY_ENABLED must be exactly "true"; anything else keeps the route dark (404). */
export function isBuyEnabled(env: Env = process.env): boolean {
  return env.RESELLER_BUY_ENABLED === "true";
}

function httpsOrHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

export function loadBuyConfig(env: Env = process.env): BuyConfigResult {
  const problems: string[] = [];

  // A Seller account can also buy, so fall back to the seller key.
  const inflowApiKey = (env.INFLOW_BUYER_API_KEY?.trim() || env.INFLOW_API_KEY?.trim()) ?? "";
  if (!inflowApiKey) problems.push("INFLOW_BUYER_API_KEY");

  const internalSecret = env.INTERNAL_PAID_API_SECRET?.trim() ?? "";
  if (!internalSecret) problems.push("INTERNAL_PAID_API_SECRET");

  // Required with NO default: the InFlow SDKs default to production.
  const rawEnvironment = env.INFLOW_ENVIRONMENT?.trim();
  const inflowEnvironment: InflowEnvironment | undefined =
    rawEnvironment === "sandbox" || rawEnvironment === "production" ? rawEnvironment : undefined;
  if (!inflowEnvironment) problems.push("INFLOW_ENVIRONMENT");

  const apolloUrlX402 = env.RESELLER_APOLLO_URL_X402?.trim() || DEFAULT_APOLLO_URL_X402;
  if (!httpsOrHttpUrl(apolloUrlX402)) problems.push("RESELLER_APOLLO_URL_X402");
  const apolloUrlMpp = env.RESELLER_APOLLO_URL_MPP?.trim() || DEFAULT_APOLLO_URL_MPP;
  if (!httpsOrHttpUrl(apolloUrlMpp)) problems.push("RESELLER_APOLLO_URL_MPP");

  const rawProtocol = env.RESELLER_PROTOCOL?.trim() || "auto";
  const protocol: ResellerProtocolSetting | undefined =
    rawProtocol === "x402" || rawProtocol === "mpp" || rawProtocol === "auto" ? rawProtocol : undefined;
  if (!protocol) problems.push("RESELLER_PROTOCOL");

  const maxPriceUsd = env.RESELLER_MAX_PRICE_USD?.trim() || DEFAULT_MAX_PRICE_USD;
  if (!isPositiveDecimal(maxPriceUsd)) problems.push("RESELLER_MAX_PRICE_USD");

  if (problems.length > 0 || !inflowEnvironment || !protocol) return { ok: false, problems };
  return {
    ok: true,
    config: { inflowApiKey, inflowEnvironment, internalSecret, apolloUrlX402, apolloUrlMpp, protocol, maxPriceUsd },
  };
}
