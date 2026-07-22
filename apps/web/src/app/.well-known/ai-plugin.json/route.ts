// Serves /.well-known/ai-plugin.json — a static manifest for AI/plugin-discovery
// agents. Anti-bot by design: no machine-callable interface section and no schema
// endpoint advertised. Discovery agents are pointed at the curated /llms.txt map
// instead. Fully static (no fetch), unlike llms.txt which is force-dynamic.
export const dynamic = "force-static";

// contact_email + legal_info_url confirmed from live site content:
//   hello@getbeam.fyi — support address used in sign-in/sign-up pages
//   /beam/privacy.html — privacy page linked from the homepage footer
const manifest = {
  schema_version: "v1",
  name_for_human: "Beam",
  name_for_model: "beam",
  description_for_human:
    "See who visits your site. Beam identifies anonymous website visitors, enriches their profiles, and drafts retargeting outreach.",
  description_for_model:
    "Beam identifies anonymous website visitors, enriches their profiles (LinkedIn, Twitter, job and company info), and drafts retargeting outreach across email and social. Anti-bot by design: the AI drafts, the human approves and sends. For a human-readable site map see https://getbeam.fyi/llms.txt.",
  contact_email: "hello@getbeam.fyi",
  legal_info_url: "https://getbeam.fyi/beam/privacy.html",
  auth: { type: "none" },
};

export async function GET(): Promise<Response> {
  return new Response(JSON.stringify(manifest, null, 2), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
