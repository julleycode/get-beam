// Reseller BUY route: apps/api asks Beam's web tier to pay a reseller (Locus
// Apollo) via InFlow. Server-to-server only — shared-secret auth, dormant (404)
// unless RESELLER_BUY_ENABLED=true. See src/lib/payments/buy-handler.ts.
import { handle } from "hono/vercel";
import { createBuyApp } from "@/lib/payments/buy-handler";
import { getDefaultBuyClients } from "@/lib/payments/buy-clients";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const handler = handle(createBuyApp({ getClients: getDefaultBuyClients }));

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
export const HEAD = handler;
