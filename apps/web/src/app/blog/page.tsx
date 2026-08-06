import type { Metadata } from "next";
import { REVALIDATE_SECONDS, SITE_URL, fetchPublishedPosts } from "@/lib/blog-fetch";
import { PostList } from "@/components/blog/post-list";

// ISR instead of force-dynamic: a publish/unpublish now shows within a 5-minute
// window rather than instantly, and in exchange the HTML is CDN-cacheable.
// force-dynamic made every request a cache MISS — slow TTFB for crawlers.
// Literal, not the imported constant: Next statically analyses this export and
// rejects non-literal values.
export const revalidate = 300;

// The layout supplies the "| Beam" title template, so don't repeat the suffix.
export const metadata: Metadata = {
  title: "Blog",
  description:
    "Guides on website visitor identification, retargeting, and turning anonymous traffic into pipeline.",
  alternates: { canonical: `${SITE_URL}/blog` },
  openGraph: { type: "website" },
};

export default async function BlogIndexPage() {
  // Fetch up to the API max (100) so every published post is linked from the
  // index. The default 50 left later posts orphaned from the index HTML, which
  // leaves Google with "Discovered - currently not indexed".
  const posts = await fetchPublishedPosts(100, undefined, {
    revalidate: REVALIDATE_SECONDS,
  });

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight">Blog</h1>
      <p className="mt-2 text-muted-foreground">
        Turning anonymous website traffic into pipeline.
      </p>
      <PostList posts={posts} />
    </div>
  );
}
