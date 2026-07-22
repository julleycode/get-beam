import { SITE_URL, fetchPublishedPosts } from "@/lib/blog-fetch";

// Serves /llms.txt (https://llmstxt.org/) — a curated, LLM-readable map of the
// public site. Dynamic like sitemap.ts: reflects the current published post set
// (no-store fetch) so a freshly published post shows up without a redeploy.
export const dynamic = "force-dynamic";

// llms.txt link descriptions must be single-line. Collapse whitespace and cap
// length so a long excerpt can't blow up the file or break the list format.
function oneLine(text: string | null, max = 160): string {
  if (!text) return "";
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

export async function GET(): Promise<Response> {
  // 100 is the blog API's max page size (?limit is capped at 100) — matches
  // sitemap.ts. Revisit with pagination if published-post count nears 100.
  const posts = await fetchPublishedPosts(100);

  const lines: string[] = [
    "# Beam",
    "",
    "> See who visits your site. Reach out on their turf.",
    "",
    "Beam is an AI agent that identifies anonymous website visitors, enriches their",
    "profiles (LinkedIn, Twitter, job and company info), and drafts retargeting",
    "outreach across email and social. Built for indie makers and DTC founders —",
    "Clay.com meets Retention.com, but simpler and cheaper. Anti-bot by design: the",
    "AI drafts, the human approves and sends. Beam never auto-sends.",
    "",
    "## Pages",
    "",
    `- [Home](${SITE_URL}/): What Beam is, how visitor identification and outreach drafting work.`,
    `- [Pricing](${SITE_URL}/pricing): Plans, quotas, and what each tier includes.`,
    `- [Blog](${SITE_URL}/blog): Guides on visitor identification, retargeting, and outreach.`,
  ];

  if (posts.length > 0) {
    lines.push("", "## Blog posts", "");
    for (const post of posts) {
      const desc = oneLine(post.excerpt || post.meta_description);
      const suffix = desc ? `: ${desc}` : "";
      lines.push(`- [${post.title}](${SITE_URL}/blog/${post.slug})${suffix}`);
    }
  }

  lines.push("", "## Optional", "", `- [Sitemap](${SITE_URL}/sitemap.xml): Full list of indexable URLs.`, "");

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400",
    },
  });
}
