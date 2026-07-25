import { NextResponse } from "next/server";
import type { NextRequest, NextFetchEvent } from "next/server";
import { shouldFireFetchBeacon, fireFetchBeacon } from "@/lib/fetch-beacon";

// Non-US visitors can't be identity-resolved yet (Beam only resolves US IPs),
// so the onboarding "aha" demo falls flat for them — route them straight to
// /login. US, and unknown country (e.g. localhost / geo miss), keep onboarding.
// x-vercel-ip-country is set automatically on every Vercel request (no config).
function geoRedirect(req: NextRequest): NextResponse | null {
  if (req.nextUrl.pathname !== "/onboarding") return null;
  const country = req.headers.get("x-vercel-ip-country");
  return country && country !== "US"
    ? NextResponse.redirect(new URL("/login", req.url))
    : null;
}

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

  // Geo check runs first (covers every onboarding CTA at once); otherwise fall
  // through to Clerk auth. Beacon above is a pure side-effect on this return.
  return geoRedirect(req) ?? handler(req, ev);
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
