// Real InFlow BUYER SDK wiring for the reseller route (server-only).
//
// Hard rules (see INFLOW-INTEGRATION-PLAN.md task 70):
//  - InFlow-managed signing ONLY: no external EVM/SVM signer is ever registered,
//    so an offer InFlow cannot sign is simply not payable.
//  - Never patch globalThis.fetch: mppx is created with `polyfill: false` and we
//    call `createCredential` manually; the x402 client is used through
//    x402HTTPClient, which never touches fetch.
import { createInflowClient, type InflowClient } from "@inflowpayai/x402-buyer";
import { Mppx, inflow, tempo } from "@inflowpayai/mpp-buyer";
import type { BuyConfig } from "./buy-config";

export type { InflowClient };

/** Builds a credential for ONE pre-approved MPP challenge (price cap already enforced). */
export interface MppCredentialMaker {
  /**
   * @param response  402 response carrying only the `WWW-Authenticate` header(s).
   * @param challengeId  the challenge the caller approved; any other is refused.
   * @returns the full `Authorization` header value (`Payment <base64url>`).
   */
  createCredential(response: Response, challengeId: string, signal: AbortSignal): Promise<string>;
}

export interface BuyClients {
  getX402Client(config: BuyConfig): Promise<InflowClient>;
  createMppMaker(config: BuyConfig, timeoutMs: number): MppCredentialMaker;
}

/**
 * `fetchImpl` is ONLY for the InFlow API calls the SDKs make; tests inject a
 * fake InFlow API here. Production passes nothing (SDK default: globalThis.fetch,
 * read but never replaced).
 */
export function createBuyClients(fetchImpl?: typeof fetch): BuyClients {
  // createInflowClient primes the buyer capability cache with a network call,
  // so keep one client per (key, environment) and drop it on failure.
  const x402Clients = new Map<string, Promise<InflowClient>>();

  return {
    getX402Client(config) {
      const cacheKey = `${config.inflowEnvironment}:${config.inflowApiKey}`;
      let client = x402Clients.get(cacheKey);
      if (!client) {
        client = createInflowClient({
          apiKey: config.inflowApiKey,
          environment: config.inflowEnvironment,
          ...(fetchImpl ? { fetch: fetchImpl } : {}),
        });
        x402Clients.set(cacheKey, client);
        client.catch(() => x402Clients.delete(cacheKey));
      }
      return client;
    },

    createMppMaker(config, timeoutMs) {
      const params = {
        apiKey: config.inflowApiKey,
        environment: config.inflowEnvironment,
        // Bounds the pending → ready poll; pending approval = failure for us.
        timeoutMs,
        ...(fetchImpl ? { fetch: fetchImpl } : {}),
      };
      const inflowMethod = inflow(params);
      const tempoMethod = tempo(params);
      const mppx = Mppx.create({ methods: [inflowMethod, tempoMethod], polyfill: false });
      return {
        async createCredential(response, challengeId, signal) {
          const onAbort = () => {
            // Aborts creation/polling and fire-and-forget cancels the approval.
            inflowMethod.cleanup();
            tempoMethod.cleanup();
          };
          if (signal.aborted) onAbort();
          signal.addEventListener("abort", onAbort, { once: true });
          try {
            return await mppx.createCredential(response, undefined, {
              orderChallenges: (candidates) => candidates.filter((c) => c.challenge.id === challengeId),
            });
          } finally {
            signal.removeEventListener("abort", onAbort);
          }
        },
      };
    },
  };
}

let defaultClients: BuyClients | undefined;

export function getDefaultBuyClients(): BuyClients {
  defaultClients ??= createBuyClients();
  return defaultClients;
}
