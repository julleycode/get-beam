import { NextResponse } from "next/server";

// Bare-path handler for the citation-watermark probe (Handoff Detection H4,
// Step A / PREP). Mints a fresh self-describing token and 302-redirects to the
// tokenized page. force-dynamic so every hit mints a new token (no caching).
export const dynamic = "force-dynamic";

// Self-describing token scheme: "p" + base36(unix-seconds) — e.g. "p1abc2xy".
// Decoding it (strip leading "p", parseInt(rest, 36), *1000) recovers the exact
// mint time, so the token found in a returned citation link tells us when that
// fetch was served — no server-side logging needed. Decode is a manual/optional
// analysis step (see plan A2 YAGNI note); we intentionally ship mint only.
function mintToken(): string {
  return "p" + Math.floor(Date.now() / 1000).toString(36);
}

export function GET(req: Request): Response {
  const token = mintToken();
  return NextResponse.redirect(new URL(`/pricing-overview/${token}`, req.url));
}
