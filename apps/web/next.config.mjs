/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
  // Let the Vercel CDN cache public blog HTML, but ONLY for requests that carry no
  // Clerk session cookie.
  //
  // Why the cookie guard is not optional: blog HTML embeds Clerk's SSR state
  // (initialState / sessionId / userId). Anonymous requests render those as null, but a
  // signed-in visitor's HTML carries their real session identifiers. Caching such a
  // response publicly would hand one user's session state to every other visitor. The
  // `missing:` matcher means any request bearing __session or __client_uat skips these
  // headers entirely and keeps the framework's existing no-store behaviour.
  //
  // Why we need this at all: <ClerkProvider> lives in the root layout and, in
  // @clerk/nextjs 5.7.6, calls headers()/auth() unconditionally — which opts every route
  // in the app into dynamic rendering. The real fix is moving ClerkProvider out of the
  // root layout; that is a separate, larger change. This rule is a stopgap so crawlers
  // hit the edge instead of a full origin render.
  //
  // PROVEN INEFFECTIVE, measured 2026-08-07. After deploy, ~30 polls over roughly 14
  // minutes against /blog and a blog post URL never saw Cache-Control change from the
  // framework's `private, no-cache, no-store, max-age=0, must-revalidate`, and Vary never
  // gained Cookie (it stayed Next's RSC value) — so this rule did not apply at all, rather
  // than being partially overridden. Next.js overrides next.config headers() on
  // dynamically rendered App Router routes. The block is kept as a record so the same dead
  // end is not retried. Delete it once <ClerkProvider> moves out of the root layout and
  // these routes render statically again — at that point re-test this rule or remove it
  // outright.
  //
  // s-maxage=300 intentionally matches REVALIDATE_SECONDS in src/lib/blog-fetch.ts
  // (not imported — next.config runs outside the TS path alias).
  async headers() {
    const clerkCookies = [
      { type: "cookie", key: "__session" },
      { type: "cookie", key: "__client_uat" },
    ];
    const cacheHeaders = [
      {
        key: "Cache-Control",
        value: "public, max-age=0, s-maxage=300, stale-while-revalidate=86400",
      },
      { key: "Vary", value: "Cookie" },
    ];
    // "/blog/:path*" does not match the bare "/blog", so both sources are needed.
    return ["/blog", "/blog/:path*"].map((source) => ({
      source,
      missing: clerkCookies,
      headers: cacheHeaders,
    }));
  },
  async rewrites() {
    return {
      // Serve the static Beam marketing landing page at the root.
      beforeFiles: [
        { source: "/", destination: "/beam/index.html" },
        { source: "/onboarding", destination: "/beam/onboarding.html" },
      ],
    };
  },
};

export default nextConfig;
