import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Markdown } from "@/components/blog/markdown";
import {
  SITE_URL,
  fetchPublishedPost,
  fetchPublishedPosts,
} from "@/lib/blog-fetch";

export const revalidate = 300;

type Params = { params: { slug: string } };

// Pre-render known published slugs at build; new ones render on-demand (ISR).
export async function generateStaticParams() {
  const posts = await fetchPublishedPosts();
  return posts.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const post = await fetchPublishedPost(params.slug);
  if (!post) return { title: "Post not found" };

  const canonical = post.canonical_url || `${SITE_URL}/blog/${post.slug}`;
  const description = post.meta_description || post.excerpt || undefined;
  const images = post.og_image_url ? [{ url: post.og_image_url }] : undefined;

  return {
    title: post.meta_title || post.title,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: post.meta_title || post.title,
      description,
      url: canonical,
      images,
      publishedTime: post.published_at || undefined,
      authors: [post.author_name],
    },
    twitter: {
      card: "summary_large_image",
      title: post.meta_title || post.title,
      description,
      images: post.og_image_url ? [post.og_image_url] : undefined,
    },
  };
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function BlogPostPage({ params }: Params) {
  const post = await fetchPublishedPost(params.slug);
  if (!post) notFound();

  const canonical = post.canonical_url || `${SITE_URL}/blog/${post.slug}`;
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: post.title,
    description: post.meta_description || post.excerpt || undefined,
    datePublished: post.published_at || undefined,
    dateModified: post.published_at || undefined,
    author: { "@type": "Organization", name: post.author_name },
    image: post.og_image_url || post.cover_image_url || undefined,
    mainEntityOfPage: { "@type": "WebPage", "@id": canonical },
    url: canonical,
  };

  return (
    <article>
      {/* JSON-LD structured data (our own data, not user raw HTML) */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <a href="/blog" className="text-sm text-muted-foreground hover:text-foreground">
        ← All posts
      </a>

      <h1 className="mt-4 font-serif text-4xl font-semibold leading-tight tracking-tight">
        {post.title}
      </h1>

      <div className="mt-3 flex items-center gap-3 text-sm text-muted-foreground">
        <span>{post.author_name}</span>
        {post.published_at && (
          <>
            <span aria-hidden>·</span>
            <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>
          </>
        )}
        {post.reading_time_minutes && (
          <>
            <span aria-hidden>·</span>
            <span>{post.reading_time_minutes} min read</span>
          </>
        )}
      </div>

      {post.tags && post.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {post.tags.map((t) => (
            <a
              key={t}
              href={`/blog/tag/${encodeURIComponent(t)}`}
              className="rounded-full bg-secondary px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              {t}
            </a>
          ))}
        </div>
      )}

      {post.cover_image_url && (
        // Plain <img> avoids next/image remote-host config (P2 scope decision).
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={post.cover_image_url}
          alt={post.title}
          className="mt-6 w-full rounded-xl border border-[rgba(43,37,48,0.08)]"
        />
      )}

      <div className="mt-8">
        <Markdown>{post.body_markdown}</Markdown>
      </div>
    </article>
  );
}
