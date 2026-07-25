// Server-side AI-fetch beacon helpers (Handoff Detection H5).
//
// Runs inside the getbeam.fyi edge middleware. `shouldFireFetchBeacon` is a
// PURE decision (no I/O) that returns a beacon payload ONLY for a real
// top-level-document GET from a recognized on-demand AI fetcher; everything
// else returns null. `fireFetchBeacon` performs the fire-and-forget POST and
// swallows all errors. Neither ever alters the middleware response.
//
// The on-demand token set MIRRORS the API `_ON_DEMAND_TOKENS`
// (apps/api/services/agent_classifier.py). Google/Gemini is INDEX-tier there
// (KG-3, unverified fetch UA) so it is deliberately NOT fired here — the API
// would 204 it anyway; promote once a real on-demand UA is confirmed.

import type { NextRequest } from "next/server";

export const ON_DEMAND_UA_TOKENS = [
  "chatgpt-user",
  "oai-searchbot",
  "claude-user",
  "claude-searchbot",
  "perplexity-user",
] as const;

export interface FetchBeaconPayload {
  site_id: string;
  user_agent: string;
  path: string;
  token: string | null;
}

// Static-asset extensions: never a document fetch worth beaconing. Mirrors the
// spirit of the middleware `config.matcher` static-file skip list.
const STATIC_EXT_RE =
  /\.(?:html?|css|m?js|json|jpe?g|webp|png|gif|svg|ico|txt|xml|csv|docx?|xlsx?|zip|woff2?|ttf|map|webmanifest)$/i;

// Only the tokenized probe page carries a decodable mint-time token.
const TOKEN_PATH_RE = /^\/pricing-overview\/(p[0-9a-z]+)$/;

export function matchOnDemandUa(userAgent: string | null | undefined): boolean {
  if (!userAgent) return false;
  const ua = userAgent.toLowerCase();
  return ON_DEMAND_UA_TOKENS.some((t) => ua.includes(t));
}

export function isTopLevelDocumentPath(pathname: string, search: string): boolean {
  // Middleware `config.matcher` also runs for /(api|trpc) — MUST exclude them.
  if (pathname === "/api" || pathname.startsWith("/api/")) return false;
  if (pathname === "/trpc" || pathname.startsWith("/trpc/")) return false;
  if (pathname.startsWith("/_next")) return false;
  if (STATIC_EXT_RE.test(pathname)) return false;
  // Next.js RSC prefetch marker (`?_rsc=...`) — never a real document fetch.
  if (search.includes("_rsc")) return false;
  return true;
}

export function extractToken(pathname: string): string | null {
  const m = pathname.match(TOKEN_PATH_RE);
  return m ? m[1] : null;
}

// Pure decision over primitives — the unit-tested surface (no NextRequest).
export function matchFetchBeacon(input: {
  method: string;
  userAgent: string | null | undefined;
  pathname: string;
  search: string;
  siteId: string;
}): FetchBeaconPayload | null {
  if (input.method !== "GET") return null;
  if (!matchOnDemandUa(input.userAgent)) return null;
  if (!isTopLevelDocumentPath(input.pathname, input.search)) return null;
  return {
    site_id: input.siteId,
    user_agent: input.userAgent as string,
    path: input.pathname,
    token: extractToken(input.pathname),
  };
}

export function shouldFireFetchBeacon(req: NextRequest): FetchBeaconPayload | null {
  return matchFetchBeacon({
    method: req.method,
    userAgent: req.headers.get("user-agent"),
    pathname: req.nextUrl.pathname,
    search: req.nextUrl.search,
    siteId: process.env.BEAM_SITE_ID ?? "",
  });
}

export async function fireFetchBeacon(payload: FetchBeaconPayload): Promise<void> {
  const secret = process.env.BEAM_FETCH_BEACON_SECRET;
  const apiBase = process.env.BEAM_API_BASE;
  // Dormant unless BOTH the shared secret and the API base are configured
  // (server-only env). Never ships the secret to the browser.
  if (!secret || !apiBase) return;
  try {
    await fetch(`${apiBase.replace(/\/$/, "")}/api/v1/agents/fetch-beacon`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-beam-fetch-secret": secret,
      },
      body: JSON.stringify(payload),
      // Short bound so a slow/hung API never holds the edge waitUntil open.
      signal: AbortSignal.timeout(1500),
    });
  } catch {
    // Fire-and-forget: swallow ALL errors (timeout/abort/network). The beacon
    // must never affect the user's request or surface an error.
  }
}
