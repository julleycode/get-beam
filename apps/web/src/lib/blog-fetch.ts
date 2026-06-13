import type { BlogPost, BlogPostListResponse } from "@/lib/api";

// Server-side fetchers for the PUBLIC blog. These hit P1's public endpoints
// (no auth) and use ISR. Distinct from the browser `api` singleton, which
// carries the user's bearer token and runs client-side.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Canonical public origin for canonical URLs, OG, sitemap.
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || "https://getbeam.fyi"
).replace(/\/$/, "");

const REVALIDATE_SECONDS = 300;

export async function fetchPublishedPosts(limit = 50): Promise<BlogPost[]> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/blog/posts?limit=${limit}`,
      { next: { revalidate: REVALIDATE_SECONDS } }
    );
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
