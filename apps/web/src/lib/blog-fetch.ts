import type { BlogPost, BlogPostListResponse } from "@/lib/api";

// Server-side fetchers for the PUBLIC blog. These hit P1's public endpoints
// (no auth). Distinct from the browser `api` singleton, which carries the
// user's bearer token and runs client-side.
//
// The list fetcher defaults to no-store (freshest possible list) but callers
// rendering a public page should opt into ISR via `{ revalidate }`. A single
// no-store fetch marks the WHOLE route dynamic, which silently overrides any
// `export const revalidate` on the page and makes every request a CDN MISS —
// slow TTFB for Googlebot and wasted crawl budget. Individual post pages keep
// the same short ISR window (they change rarely, and a brand-new slug renders
// on-demand anyway).

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Canonical public origin for canonical URLs, OG, sitemap.
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || "https://getbeam.fyi"
).replace(/\/$/, "");

// Default social card for every App Router page that doesn't supply its own.
// The static marketing pages (public/beam/*.html) hard-code the same path.
export const OG_IMAGE = `${SITE_URL}/beam/social-share.png`;
export const OG_IMAGE_WIDTH = 1122;
export const OG_IMAGE_HEIGHT = 636;

export const REVALIDATE_SECONDS = 300;

export async function fetchPublishedPosts(
  limit = 50,
  tag?: string,
  opts?: { revalidate?: number }
): Promise<BlogPost[]> {
  try {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (tag) qs.set("tag", tag);
    const res = await fetch(`${API_BASE}/api/v1/blog/posts?${qs.toString()}`, {
      // Opting in keeps the calling route statically renderable; omitting it
      // preserves the old always-fresh behaviour for non-page callers.
      ...(opts?.revalidate !== undefined
        ? { next: { revalidate: opts.revalidate } }
        : { cache: "no-store" as const }),
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
