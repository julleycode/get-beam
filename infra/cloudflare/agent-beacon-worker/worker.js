/**
 * Beam server-side AI-fetch beacon, as a Cloudflare Worker.
 *
 * WHY THIS EXISTS AT ALL
 * The Beam pixel is JavaScript. ChatGPT-User, Claude-User and Perplexity-User
 * fetch a page's HTML and leave without running a line of it, so the pixel can
 * never observe them. Whatever sits in front of the origin is the only thing
 * that sees those requests, which on Cloudflare means a Worker. It reads the
 * User-Agent, tells Beam, and gets out of the way.
 *
 * DEPLOY (route it at the site you want watched, e.g. splittrip.nhantown.com/*):
 *   wrangler secret put BEAM_FETCH_BEACON_SECRET
 *   wrangler deploy
 *
 * The Worker mirrors apps/web/src/lib/fetch-beacon.ts. Keep the token list in
 * sync with `_ON_DEMAND_TOKENS` in apps/api/services/agent_classifier.py — the
 * API will 204 anything it does not recognise, so a drift here costs signal
 * silently rather than erroring.
 */

// On-demand fetchers only: a real person is waiting on this request right now.
// Index crawlers (GPTBot, ClaudeBot, PerplexityBot) are deliberately absent —
// beaconing them would flood the tab with robot traffic and drown the signal
// that a human is behind the fetch. The API records index-tier from other
// paths; this Worker is about the on-demand moment.
const ON_DEMAND_UA_TOKENS = [
  "chatgpt-user",
  "oai-searchbot",
  "claude-user",
  "claude-searchbot",
  "perplexity-user",
];

// Never a document fetch worth reporting. Without this, one AI page view turns
// into dozens of rows (every JS chunk, font and image), and `page_paths` on the
// rollup becomes unreadable.
const STATIC_EXT_RE =
  /\.(?:html?|css|m?js|json|jpe?g|webp|png|gif|svg|ico|txt|xml|csv|docx?|xlsx?|zip|woff2?|ttf|map|webmanifest)$/i;

function matchOnDemandUa(userAgent) {
  if (!userAgent) return false;
  const ua = userAgent.toLowerCase();
  return ON_DEMAND_UA_TOKENS.some((t) => ua.includes(t));
}

function isTopLevelDocumentPath(pathname) {
  if (pathname.startsWith("/api/") || pathname === "/api") return false;
  if (pathname.startsWith("/_next") || pathname.startsWith("/assets")) return false;
  return !STATIC_EXT_RE.test(pathname);
}

export default {
  async fetch(request, env, ctx) {
    // Serve the page FIRST and unconditionally. The beacon is bookkeeping; a
    // visitor — human or AI — must never wait on it or be affected by it.
    const response = fetch(request);

    try {
      if (request.method === "GET" && env.BEAM_FETCH_BEACON_SECRET) {
        const ua = request.headers.get("user-agent");
        const url = new URL(request.url);
        if (matchOnDemandUa(ua) && isTopLevelDocumentPath(url.pathname)) {
          // waitUntil, not await: the fetch is fire-and-forget, but the Worker
          // must not be torn down before it leaves. Without this the beacon is
          // cancelled the moment the response streams, and the tab stays empty
          // for reasons nothing logs.
          ctx.waitUntil(
            fetch(`${env.BEAM_API_BASE}/api/v1/agents/fetch-beacon`, {
              method: "POST",
              headers: {
                "content-type": "application/json",
                "x-beam-fetch-secret": env.BEAM_FETCH_BEACON_SECRET,
              },
              body: JSON.stringify({
                site_id: env.BEAM_SITE_ID,
                user_agent: ua,
                path: url.pathname,
              }),
            }).catch(() => {}),
          );
        }
      }
    } catch {
      // A bug in the beacon must never take the site down with it.
    }

    return response;
  },
};
