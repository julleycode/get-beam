import type { BlogPost, BlogPostListResponse } from "@/lib/api";

// Server-side fetchers for the PUBLIC blog. These hit P1's public endpoints
// (no auth). Distinct from the browser `api` singleton, which carries the
// user's bearer token and runs client-side.
//
// The list is fetched fresh (no-store) so a publish/unpublish shows on /blog
// immediately — a cached list would lag the publish by the revalidate window.
// Individual post pages keep a short ISR window (they change rarely, and a
// brand-new slug renders on-demand anyway).

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Canonical public origin for canonical URLs, OG, sitemap.
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || "https://getbeam.fyi"
).replace(/\/$/, "");

const REVALIDATE_SECONDS = 300;

export async function fetchPublishedPosts(
  limit = 50,
  tag?: string
): Promise<BlogPost[]> {
  try {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (tag) qs.set("tag", tag);
    const res = await fetch(`${API_BASE}/api/v1/blog/posts?${qs.toString()}`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = (await res.json()) as BlogPostListResponse;
    return data.posts;
  } catch {
    // API unreachable (e.g. during a build with no backend) → empty list.
    return [];
  }
}
export async function fetchPublishedPost(slug: string): Promise<BlogPost | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/blog/posts/${encodeURIComponent(slug)}`,
      { next: { revalidate: REVALIDATE_SECONDS } }
    );
    if (!res.ok) return null;
    return (await res.json()) as BlogPost;
  } catch {
    return null;
  }
}
