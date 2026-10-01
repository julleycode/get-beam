// Real InFlow SDK wiring for the agent-paid API (MPP + x402), lazily built once.
//
// process.exit guard: @x402/core's `attachBackgroundInitHandler` calls
// `process.exit(1)` when the background facilitator sync started by
// `paymentMiddlewareFromConfig` / `paymentMiddleware` (syncFacilitatorOnStart
// = true, the default) rejects with a FacilitatorCapabilityError or
// RouteConfigurationError. On a serverless function that would kill the
// instance. So we never use those entry points: we build the
// x402HTTPResourceServer ourselves, `await initialize()` inside our own
// try/catch (a failure rejects the cached promise → 503 + retry on the next
// request), and hand the ALREADY-initialized server to
// `paymentMiddlewareFromHTTPServer(..., syncFacilitatorOnStart = false)`, which
// skips both the background init and the exit handler.
import { Mppx, inflow } from "@inflowpayai/mpp-seller";
import {
  createInflowFacilitator,
  createInflowSellerClient,
  inflowAccepts,
  inflowSchemeRegistrations,
} from "@inflowpayai/x402-seller";
import {
  paymentMiddlewareFromHTTPServer,
  x402HTTPResourceServer,
  x402ResourceServer,
} from "@x402/hono";
import type { MppChargeResult, MppGateway, MppPrice, PaidPayments } from "./paid-handler";
import { PAID_OPS, type PaidConfig } from "./paid-config";

type RoutesConfig = ConstructorParameters<typeof x402HTTPResourceServer>[1];

async function buildPayments(config: PaidConfig): Promise<PaidPayments> {
  const { inflowApiKey: apiKey, inflowEnvironment: environment } = config;

  const facilitator = createInflowFacilitator({ environment, apiKey });
  const seller = await createInflowSellerClient({ environment, apiKey });
  const registrations = await inflowSchemeRegistrations(seller);

  const routes: Record<string, { accepts: Awaited<ReturnType<typeof inflowAccepts>> }> = {};
  for (const op of PAID_OPS) {
    const route = config.routes[op];
    routes[`POST ${route.path}`] = {
      accepts: await inflowAccepts(seller, { price: `${route.price} USDC` }),
    };
  }

  const resourceServer = new x402ResourceServer([facilitator]);
  for (const { network, server } of registrations) {
    resourceServer.register(network, server);
  }
  const httpServer = new x402HTTPResourceServer(resourceServer, routes as RoutesConfig);
  await httpServer.initialize();
  const x402 = paymentMiddlewareFromHTTPServer(httpServer, undefined, undefined, false);

  const mppx = Mppx.create({
    methods: [inflow({ apiKey, environment })],
    secretKey: config.mppSecretKey,
  });

  const mpp: MppGateway = {
    async charge(price: MppPrice, request: Request): Promise<MppChargeResult> {
      const result = await mppx.charge({
        amount: price.amount,
        currency: price.currency,
        scope: price.scope,
      })(request);
      if (result.status === 402) return { status: 402, challenge: result.challenge };
      return { status: 200, withReceipt: (response: Response) => result.withReceipt(response) };
    },
    async validateCredential(credential: string, price: MppPrice) {
      const validation = await mppx.validateCredential(credential, {
        request: { amount: price.amount, currency: price.currency },
        scope: price.scope,
      });
      const id: unknown = (validation.challenge as { id?: unknown }).id;
      return { reference: typeof id === "string" ? id : undefined };
    },
  };

  return { mpp, x402 };
}

let cached: Promise<PaidPayments> | undefined;

/** Lazy singleton. A failed init is NOT cached, so a later request can retry. */
export function getPaidPayments(config: PaidConfig): Promise<PaidPayments> {
  cached ??= buildPayments(config).catch((err: unknown) => {
    cached = undefined;
    throw err;
  });
  return cached;
}
