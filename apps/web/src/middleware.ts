import { NextResponse } from "next/server";
import type { NextRequest, NextFetchEvent } from "next/server";
import { shouldFireFetchBeacon, fireFetchBeacon } from "@/lib/fetch-beacon";

// NOTE: /onboarding used to 307 non-US visitors to /login, on the premise that
// the demo needs US-only identity resolution. The canary funnel replaced that
// premise: geo comes from the CALLER's own IP (works worldwide) and the catch is
// a fingerprint match, so nothing in it is US-gated. The gate only hid a working
// funnel from every non-US visitor. Do not reintroduce a country check here.

// Clerk middleware is only active when NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is set.
// Without it, all routes are publicly accessible (local dev without Clerk).
let handler: (req: NextRequest, ev: NextFetchEvent) => NextResponse | Promise<NextResponse>;

if (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { clerkMiddleware, createRouteMatcher } = require("@clerk/nextjs/server");
  const isPublicRoute = createRouteMatcher([
    "/",            // public Beam marketing landing page
    "/onboarding(.*)",  // public aha-before-commit onboarding
    "/login(.*)",
    "/signup(.*)",
    "/sign-in(.*)",
    "/sign-up(.*)",
    "/pricing(.*)",
    "/blog(.*)",    // public marketing blog (SEO). /dashboard/blog stays protected.
    "/.well-known/(.*)",  // public agent-discovery manifests (ai-plugin.json)
    "/pricing-overview(.*)",  // public citation-watermark probe page (H4) — must never 302 to /sign-in
  ]);
  handler = clerkMiddleware((auth: () => { protect: () => void }, request: NextRequest) => {
    if (!isPublicRoute(request)) {
      auth().protect();
    }
  });
} else {
  handler = () => NextResponse.next();
}

export default function middleware(req: NextRequest, ev: NextFetchEvent) {
  // H5: fire-and-forget server-side AI-fetch beacon. Pure detection first, then
  // a background POST via ev.waitUntil — it NEVER awaits, NEVER changes the
  // response, and stays OUT of the Clerk callback. Dormant unless the server-only
  // shared secret is present. Guarded so a helper bug can never break auth/redirect.
  try {
    const beaconPayload = shouldFireFetchBeacon(req);
    if (beaconPayload && process.env.BEAM_FETCH_BEACON_SECRET) {
      ev.waitUntil(fireFetchBeacon(beaconPayload));
    }
  } catch {
    // Never let the beacon disturb the request path.
  }

  // Beacon above is a pure side-effect on this return.
  return handler(req, ev);
}

export const config = {
  matcher: [
    // Skip Next.js internals and all static files. `xml`/`txt` matter: without
    // them, Clerk protects /sitemap.xml and /robots.txt (they aren't public
    // routes) and returns 404 to crawlers — SEO metadata routes must stay open.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest|xml|txt)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
