import type { MetadataRoute } from "next";
import { SITE_URL, fetchPublishedPosts } from "@/lib/blog-fetch";

// Dynamic: reflects the current published set (no-store fetch), so a freshly
// published post appears in the sitemap immediately — Google picks it up on the
// next sitemap recrawl with no manual "request indexing" needed.
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // 100 is the blog API's max page size (?limit is capped at 100). Asking for
  // more returns HTTP 422, which would drop every post from the sitemap. Revisit
  // with pagination if the published-post count ever approaches 100.
  const posts = await fetchPublishedPosts(100);

  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/pricing`, changeFrequency: "monthly", priority: 0.8 },
    { url: `${SITE_URL}/blog`, changeFrequency: "daily", priority: 0.9 },
  ];

  const postRoutes: MetadataRoute.Sitemap = posts.map((post) => ({
    url: `${SITE_URL}/blog/${post.slug}`,
    lastModified: post.published_at || post.created_at,
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  const tags = Array.from(new Set(posts.flatMap((p) => p.tags ?? []))).sort();
  const tagRoutes: MetadataRoute.Sitemap = tags.map((tag) => ({
    url: `${SITE_URL}/blog/tag/${encodeURIComponent(tag)}`,
    changeFrequency: "weekly",
    priority: 0.5,
  }));

  return [...staticRoutes, ...postRoutes, ...tagRoutes];
}
