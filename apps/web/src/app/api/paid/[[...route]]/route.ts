// Agent-paid API: external AI agents pay (MPP or x402 via InFlow) per call.
// Dormant (404 everywhere) unless AGENT_PAID_ENABLED=true. See
// src/lib/payments/paid-handler.ts for the charging invariant.
import { handle } from "hono/vercel";
import { createPaidApp } from "@/lib/payments/paid-handler";
import { getPaidPayments } from "@/lib/payments/paid-payments";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const handler = handle(createPaidApp({ getPayments: getPaidPayments }));

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
export const HEAD = handler;
