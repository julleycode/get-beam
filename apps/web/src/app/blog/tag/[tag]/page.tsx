import type { Metadata } from "next";
import Link from "next/link";
import { REVALIDATE_SECONDS, fetchPublishedPosts, SITE_URL } from "@/lib/blog-fetch";
import { PostList } from "@/components/blog/post-list";

// ISR instead of force-dynamic: a publish shows within 5 minutes instead of
// instantly, in exchange for CDN-cacheable HTML (force-dynamic made every
// crawler hit a cache MISS). Literal value — Next statically analyses it.
export const revalidate = 300;

type Params = { params: { tag: string } };

function decodeTag(raw: string): string {
  return decodeURIComponent(raw);
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const tag = decodeTag(params.tag);
  const title = `Posts tagged “${tag}”`;
  const description = `Beam blog articles about ${tag}: visitor identification, retargeting, and turning anonymous traffic into pipeline.`;
  return {
    title,
    description,
    alternates: { canonical: `${SITE_URL}/blog/tag/${encodeURIComponent(tag)}` },
    openGraph: { type: "website", title, description },
  };
}

export default async function BlogTagPage({ params }: Params) {
  const tag = decodeTag(params.tag);
  const posts = await fetchPublishedPosts(50, tag, {
    revalidate: REVALIDATE_SECONDS,
  });

  return (
    <div>
      <Link href="/blog" className="text-sm text-muted-foreground hover:text-foreground">
        ← All posts
      </Link>
      <h1 className="mt-4 font-serif text-3xl font-semibold tracking-tight">
        Tagged <span className="text-[hsl(345,100%,45%)]">{tag}</span>
      </h1>
      <p className="mt-2 text-muted-foreground">
        {posts.length} {posts.length === 1 ? "post" : "posts"}
      </p>
      <PostList posts={posts} />
    </div>
  );
}
