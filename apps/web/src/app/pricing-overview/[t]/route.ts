import { notFound } from "next/navigation";

// Citation-watermark feasibility probe (Handoff Detection H4, Step A / PREP).
// Serves a tokenized, byte-identical HTML pricing summary. The tokenized
// canonical URL IS the experiment: we measure whether a Beam-controlled marker
// (the {t} path segment) survives into an AI agent's returned citation link.
//
// force-dynamic (mirrors llms.txt/route.ts): every request is served fresh, and
// the token is a live path parameter — no build-time static generation.
export const dynamic = "force-dynamic";

// SECURITY (PVL fix, OWASP A03:2021-Injection / STRIDE Tampering): {t} is the
// only external input this route accepts and it is interpolated into HTML
// (canonical href + link text). An unvalidated path segment reflected into HTML
// is a reflected-XSS vector. We reject anything that is not the exact charset
// the mint function produces ("p" + base36) BEFORE any HTML string is built, so
// only pre-validated safe strings ever reach the template — no separate
// HTML-escaping step is then needed.
const TOKEN_RE = /^p[0-9a-z]+$/;

// DRIFT RISK: these pricing values are hand-synced from
// apps/web/src/app/pricing/page.tsx (the PLANS array). They do NOT auto-update
// if pricing changes — same known drift pattern as the homepage JSON-LD static
// file (public/beam/index.html). Update both together when pricing changes.
function pricingHtml(token: string): string {
  const canonical = `https://getbeam.fyi/pricing-overview/${token}`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beam Pricing — plans and quotas</title>
<meta name="description" content="Beam pricing: Free ($0/mo, 10 identified visitors), Pro ($19/mo, 50 identified visitors), and Max ($49/mo, unlimited identified visitors). Beam identifies anonymous website visitors and drafts outreach.">
<link rel="canonical" href="${canonical}">
<meta name="robots" content="noindex, follow">
</head>
<body>
<h1>Beam Pricing</h1>
<p>Beam identifies anonymous website visitors, enriches their profiles, and drafts
retargeting outreach across email and social. Anti-bot by design: the AI drafts,
the human approves and sends.</p>
<h2>Plans</h2>
<ul>
<li><strong>Free</strong> — $0/mo — 10 identified visitors/mo.</li>
<li><strong>Pro</strong> — $19/mo ($15/mo billed yearly) — 50 identified visitors/mo.</li>
<li><strong>Max</strong> — $49/mo ($39/mo billed yearly) — unlimited identified visitors.</li>
</ul>
<p>Full pricing details: <a href="${canonical}">${canonical}</a></p>
<p>See <a href="${canonical}">Beam pricing overview</a> for plans and quotas.</p>
</body>
</html>`;
}

export function GET(
  _req: Request,
  { params }: { params: { t: string } }
): Response {
  const { t } = params;

  // XSS gate — reject before ANY HTML is built.
  if (!TOKEN_RE.test(t)) {
    notFound();
  }

  return new Response(pricingHtml(t), {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
