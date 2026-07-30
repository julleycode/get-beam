/**
 * Beam server-side AI-fetch beacon, as Cloudflare Pages middleware.
 *
 * Runs on every request to this Pages project before the static asset is served.
 * Preferred over a standalone Worker + route: Pages Functions are part of the
 * deployment, so there is no separate route to drift, and no requirement that the
 * hostname be proxied by a DNS record we do not control. That requirement is what
 * broke splittrip.nhantown.com — its host (appdeploy.ai) de-registers any domain
 * whose DNS stops pointing directly at them, so it can never sit behind a Worker
 * route. A Pages-hosted site has no such conflict.
 *
 * Env (wrangler.toml [vars] + one secret):
 *   BEAM_API_BASE            https://beam-api.nhantown.com  (FULL api host)
 *   BEAM_SITE_ID             site_...
 *   BEAM_FETCH_BEACON_SECRET must equal the API's BEAM_FETCH_BEACON_SECRET
 */

// On-demand fetchers only: a real person is waiting on this request right now.
// Index crawlers (GPTBot, ClaudeBot, PerplexityBot) are deliberately excluded —
// beaconing them would bury the human-intent signal under routine robot traffic.
// Mirrors _ON_DEMAND_TOKENS in apps/api/services/agent_classifier.py; the API
// silently 204s anything it does not recognise, so drift costs signal quietly.
const ON_DEMAND_UA_TOKENS = [
  "chatgpt-user",
  "oai-searchbot",
  "claude-user",
  "claude-searchbot",
  "perplexity-user",
];

// Assets are never a document fetch worth reporting. Without this one AI page
// view becomes a dozen rows and `page_paths` on the rollup turns to noise.
const STATIC_EXT_RE =
  /\.(?:css|m?js|jpe?g|webp|png|gif|svg|ico|woff2?|ttf|map|webmanifest)$/i;

function matchOnDemandUa(userAgent) {
  if (!userAgent) return false;
  const ua = userAgent.toLowerCase();
  return ON_DEMAND_UA_TOKENS.some((t) => ua.includes(t));
}

export async function onRequest(context) {
  const { request, env, next, waitUntil } = context;

  // Serve first, unconditionally. The beacon is bookkeeping — no visitor, human
  // or AI, should ever wait on it or be affected by it failing.
  const response = next();

  try {
    if (request.method === "GET" && env.BEAM_FETCH_BEACON_SECRET) {
      const url = new URL(request.url);
      const ua = request.headers.get("user-agent");
      if (matchOnDemandUa(ua) && !STATIC_EXT_RE.test(url.pathname)) {
        // waitUntil, not await: fire-and-forget, but the runtime must not tear
        // the request down before the POST leaves. Without it the beacon is
        // cancelled as soon as the response streams and the Agents tab stays
        // empty with nothing anywhere explaining why.
        waitUntil(
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
    // A bug in the beacon must never take the page down with it.
  }

  return response;
}
