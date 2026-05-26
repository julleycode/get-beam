import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Clerk middleware is only active when NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is set.
// Without it, all routes are publicly accessible (local dev without Clerk).
let middleware: (req: NextRequest) => NextResponse | Promise<NextResponse>;

if (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { clerkMiddleware, createRouteMatcher } = require("@clerk/nextjs/server");
  const isPublicRoute = createRouteMatcher([
    "/login(.*)",
    "/sign-in(.*)",
    "/sign-up(.*)",
  ]);
  middleware = clerkMiddleware((auth: () => { protect: () => void }, request: NextRequest) => {
    if (!isPublicRoute(request)) {
      auth().protect();
    }
  });
} else {
  middleware = () => NextResponse.next();
}

export default middleware;

export const config = {
  matcher: [
    // Skip Next.js internals and all static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
